# Polar-GIS 地图瓦片加载稳定性修复与 S-57 航道专题信息开发任务书

## 0. 角色与总体目标

你是一名熟悉 Vue 3、TypeScript、OpenLayers 10、FastAPI、PostgreSQL/PostGIS、GeoServer/GWC、GDAL、IHO S-57 电子海图及前端性能优化的高级全栈开发工程师。

现在需要基于最新代码仓库：

https://github.com/shifengdongma/polar-gis

完成以下三项任务：

**任务 A：修复海冰密集度时间轴切换后图层长时间空白、无法及时恢复的问题。**

**任务 B：修复地图工作台长时间运行后，底图出现局部或大面积瓦片空白、只有刷新整个浏览器页面才能恢复的问题。**

**任务 C：开发 S-57 航道专题信息提取、查询、搜索、定位和独立地图显示功能，提高真实电子海图数据的交互性。**

三个任务均必须以真实源码分析为前提，不允许只加刷新按钮或在前端加入假数据。

### 硬性约束

- 不破坏当前项目已有的 S-57 导入、更新链、批量加载、GeoServer/GWC、Render Bundle、smart/standard/overview 渲染模式。
- 不影响已实现的海冰时间轴、海冰密集度与厚度、风浪流环境叠加。
- 不影响航路绘制、航点编辑、航路选择、智能规划、风险栅格和规划结果展示。
- 不修改已有路线数据持久化格式，除非严格证明需要迁移并提供兼容方案。
- 不通过频繁 `window.location.reload()` 或销毁重建整个 OpenLayers Map 掩盖问题。
- 不在没有真实证据时声称已经找到根因。
- 不制造虚假的 S-57 航道要素或航道名称。
- 需要提供可复现测试、实际验证结果和未验证事项。
- 不擅自 commit 或 push。

# 第一部分：代码与运行基线审计

## 1. 确认最新代码

首先执行：

```
git status
git branch --show-current
git log -8 --oneline
```

检查：

```
master
```

当前最新提交与开发工作区是否一致。

本任务编写时，GitHub 已观察到：

```
9e9eff0c7a05669af15cc93a27d069e8f266016e
```

该提交已经修改环境数据预热和加载性能。

如果执行任务时 HEAD 更新，应以更新后的实际代码为准，并将差异写入审计报告。

读取：

```
CLAUDE.md
README.md

frontend/src/views/MapWorkspaceView.vue
frontend/src/composables/useIceOverlay.ts
frontend/src/composables/useEnvironmentOverlays.ts
frontend/src/utils/mapIce.ts
frontend/src/utils/tileRequestQueue.ts
frontend/src/utils/tileCache.ts
frontend/src/utils/mapRenderScheduler.ts
frontend/src/utils/mapRenderBundles.ts
frontend/src/utils/mapTileMerger.ts
frontend/src/utils/basemaps.ts
frontend/src/api/ice.ts

backend/app/services/ice.py
backend/app/api/ice.py
backend/app/core/config.py

backend/app/services/s57.py
backend/app/services/s57_layer_catalog.py
backend/app/services/s57_batch.py
backend/app/services/importer.py
backend/app/api/layers.py
backend/app/api/projects.py

frontend/src/utils/s57ObjectNames.ts
frontend/src/types/index.ts

deploy/compose.yml
deploy/nginx/default.conf

docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
```

注意：部分文件可能已改名或不存在，必须根据实际仓库结构确认。

先记录两项现有稳定性问题的完整代码调用链。

# 第二部分：海冰时间轴空白问题修复

## 2. 当前已确认的源码结构

`frontend/src/composables/useIceOverlay.ts` 当前具有以下机制：

```
selectedDate
    ↓
watch(selectedDate)
    ↓
refreshLayers()
    ↓
abortStaleTileLoads()
    ↓
tileGeneration++
    ↓
AbortController.abort()
    ↓
TileLayer.setSource(new XYZ(...))
    ↓
createIceTileLoadFunction()
    ↓
LRUTileCache
    ↓
TileRequestQueue.fetch()
    ↓
HTTP /api/v1/ice/.../tile
    ↓
Blob
    ↓
URL.createObjectURL()
    ↓
image.src
    ↓
OpenLayers tile LOADED
```

原有问题曾经是并发冷加载引起请求堆积，历史修复已经加入：

```
per-date single-flight
IceService grid warm-up
TileRequestQueue
LRUTileCache
AbortController
TileState.EMPTY
指数退避
```

本次不得直接删除这些机制，而应通过测试找出其生命周期中的真实异常。

## 3. 必须检查的潜在问题

### 3.1 全局 tileGeneration 是否误伤有效请求

当前：

```
function abortStaleTileLoads() {
  tileGeneration += 1
  for (const controller of tileControllers) {
    controller.abort()
  }
  tileControllers.clear()
}
```

这一机制使用单个代次号控制当前冰情加载。

分析以下场景：

```
日期 A 正在请求
    ↓
用户切换 B
    ↓
A 被取消
    ↓
B 开始请求
    ↓
用户切换 C
    ↓
B 被取消
    ↓
用户立即切回 B
```

检查：

- 当前 Source 对应的 generation 是否正确；
- abort 后队列中的旧任务是否全部移除；
- 是否存在取消 A 时误取消 B 的情况；
- 旧请求结束后是否会设置新瓦片的状态；
- 快速重复选择同一日期会不会产生悬空的 LOADING；
- `refreshLayers()` 是否被多个 watcher 重复调用；
- 透明度变化是否错误触发重建；
- 当前字段不可用与空数据是否被误认为网络故障。

重点检查 OpenLayers 实际状态：

```
IDLE
LOADING
LOADED
ERROR
EMPTY
```

不要把 `EMPTY` 当作一个可以无条件重试的普通错误。

### 3.2 检查请求中止后重试定时器

当前海冰加载器使用：

```
window.setTimeout(tryLoad, delay)
```

实现指数退避。

必须检查：

- 旧 Source 被替换后重试定时器是否仍然存在；
- 已被取消的任务是否还能重新排队；
- timer 在 dispose 时是否清理；
- 最后一次重试失败时是否一定结束 LOADING；
- 网络恢复后当前可见瓦片是否有重新请求机会。

建议使用：

```
AbortSignal
generation
retryTimer
tile state
source identity
```

形成统一的请求生命周期。

但不要只依赖增大超时或增大重试次数解决空白。

### 3.3 检查缓存 Blob 与图片解码

当前加载链：

```
fetch()
→ response.blob()
→ URL.createObjectURL()
→ image.src
```

检查：

- response 类型是否真的是 image/png；
- Blob 是否为空；
- 是否存在 200 OK 但返回 HTML；
- 图片 `onerror` 是否处理；
- objectURL 是否在正确的时机 revoke；
- 图片已解码但 tile 状态未进入 LOADED；
- 解码失败是否导致永久 LOADING；
- URL 使用后是否发生内存泄漏。

必须让每一个加载尝试最终进入明确状态：

```
LOADED
ERROR
或合法的中止/销毁状态
```

而不是无期限等待。

### 3.4 检查 TileRequestQueue

重点分析：

```
frontend/src/utils/tileRequestQueue.ts
```

现有队列采用：

```
maxConcurrent
maxQueue
inFlight
queue
AbortSignal
```

实现并发限制。

需要专项测试：

```
1. 排队期间 abort
2. fetch 过程中 abort
3. 连续 abortAll
4. 连续 reset
5. 队列达到上限
6. 已排队任务取消
7. 新请求在旧请求取消后立即进入
8. inFlight 不出现负数
9. inFlight 不超过 maxConcurrent
10. queued 不会长期不下降
```

特别检查 `abortAll()`：

```
for (const req of this.queue) {
  req.reject(...)
}
this.queue.length = 0
```

这一实现只拒绝队列任务，并不自动中止所有在飞 fetch。

调用方必须正确持有 AbortController。

同时注意 Promise 被 reject 后，必须清理监听器和队列引用。

不要在重试逻辑中无限生成定时器与请求。

## 4. 建立海冰请求诊断能力

建议新增开发环境诊断工具：

```
frontend/src/utils/tileDiagnostics.ts
```

为每次海冰瓦片加载记录：

```
interface TileDiagnosticEvent {
  layer: string
  sourceKey: string
  date?: string
  projection: string
  generation: number
  url: string
  status: string
  attempts: number
  durationMs: number
  aborted: boolean
  error?: string
}
```

同时记录：

```
tileloadstart
tileloadend
tileloaderror

queue.pending
queue.queued
cache.size
cache.bytes

currentDate
source identity
```

要求：

- 默认生产环境关闭详细日志；
- 开发环境可开启；
- 日志有数量上限；
- 不打印认证令牌和敏感 URL 参数；
- 不记录完整海冰网格数据。

## 5. 后端海冰性能核查

检查：

```
backend/app/services/ice.py
```

重点验证：

```
网格索引
元数据缓存
文件变更检测
日期网格缓存
per-date single-flight
瓦片缓存
Grid warm-up
```

结合最新导航环境服务：

```
backend/app/navigation/environment/providers/ice.py
backend/app/navigation/environment/service.py
```

确认是否复用同一 `IceService`，避免同一大 NetCDF 文件被两个服务重复完整加载。

检查：

```
内存峰值
重复网格读入
锁竞争
线程池等待
缓存命中率
文件 IO
```

如果瓦片请求经过 Nginx，还要验证：

```
HTTP 状态码
响应时间
Content-Type
Cache-Control
502/503/504
```

不允许仅凭浏览器看到空白就调整 numpy 渲染算法。

## 6. 修复目标

最终至少实现：

```
切换日期
→ 旧的无效请求及时退出
→ 新日期请求及时执行
→ 当前可见瓦片正常显示
```

如果当前日期加载失败：

```
有限次数自动重试
→ 仍失败则展示明确状态
→ 用户可独立重试当前冰情图层
```

不允许要求用户：

```
F5
Ctrl+R
关闭整个地图工作台
```

才能恢复。

### 注意

当用户切换到确实无数据的日期时，应展示无数据状态，而不是重试无效瓦片。

不得生成虚假的海冰数据来填补空白。

# 第三部分：底图长时间运行后空白问题修复

## 7. 当前底图创建机制

Polar-GIS 当前：

```
MapWorkspaceView.vue
```

中包含：

```
createConfiguredBaseLayers()
applyBaseMapVisibility()
selectBaseMap()
buildMap()
switchProjection()
```

配置底图：

```
XYZ
WMTS
```

备用底图：

```
OSM
```

当前 `createConfiguredBaseLayers()` 为每个底图创建独立 TileLayer。

必须从这里开始调查。

## 8. 首先判断空白属于哪一层

进入地图后一段时间，出现空白时，必须通过开发者工具和 OpenLayers 状态判断：

```
A. 底图 TileLayer 本身空白

B. 底图正常，但 S-57 海图层空白

C. 底图与 S-57 都空白

D. OpenLayers canvas 渲染异常

E. 请求成功，但资源没有正确显示
```

具体记录：

```
空白区域坐标
当前 zoom
当前 CRS
底图 ID
底图 URL
TileLayer visible
Source 是否存在
TileState
Network HTTP 状态
请求耗时
是否存在跨域错误
是否有 WebGL/Canvas 错误
```

不能将这五类问题统一处理成“重新加载底图”。

## 9. 排查底图请求失败

对于：

```
XYZ
WMTS
OSM
```

分别检查：

```
HTTP 429
HTTP 403
HTTP 404
HTTP 500
HTTP 502
HTTP 503
HTTP 504
网络中断
DNS
CORS
超时
图片解码
服务端限流
```

如果使用第三方公共底图：

- 核查服务条款；
- 核查请求频率限制；
- 核查投影与瓦片矩阵；
- 核查 attribution；
- 不要使用未经授权的镜像地址；
- 不要通过无限重试规避提供方限流。

对于 404，要先判断是否代表该瓦片确实不存在，避免无限重试。

## 10. 底图重试和恢复机制

参考已有海图瓦片加载器：

```
createRetryTileLoadFunction()
```

但不能直接全量复制。

应抽取可共享的通用能力：

```
TileFetchPolicy
TileRetryPolicy
TileLoadLifecycle
```

允许：

```
有限次数重试
超时控制
状态诊断
请求取消
独立恢复当前 Source
```

底图的加载优先级应高于可选环境叠加请求，以免海冰或 S-57 大量请求排队时导致底图长期空白。

如果调整共享队列，需要测试：

```
高优先级请求不会长期饥饿
低优先级请求不会永久饥饿
并发总数受控
```

同时评估浏览器原生图片加载器与 fetch 加载器在 CORS、凭证和缓存上的差异。

## 11. 避免长期 ERROR 状态不恢复

OpenLayers 某些失败瓦片可能保留 ERROR 状态，需要通过合理的 source refresh 或局部重新请求恢复。

允许新增：

```
retryFailedVisibleTiles()
```

但必须满足：

```
只处理当前可见的失败瓦片
不重建整个 Map
不清空全部业务图层
不重置航线
不重置地图中心和 zoom
不重复创建监听器
```

不能简单每隔 10 秒：

```
source.refresh()
```

因为这样会导致持续流量、缓存失效和闪烁。

建议采用：

```
错误事件触发
→ 指定次数的恢复
→ 根据失败率退避
→ 恢复成功后停止
```

支持手动：

```
重新加载当前底图
```

作为最后的用户可控恢复方式。

## 12. 核查投影切换

当前系统支持：

```
EPSG:3857
EPSG:3413
```

`applyBaseMapVisibility()` 根据当前 CRS 筛选配置底图。

必须确认：

- 当前投影是否有可用底图；
- 切换投影后是否错误保留旧底图 ID；
- 旧 Source 是否仍然被引用；
- fallbackBaseLayer 是否只在允许的情况下启用；
- `setView()` 后 XYZ/WMTS 的 TileGrid 是否符合投影；
- 是否出现错误 extent 导致瓦片被认为在视口外；
- 底图隐藏后再次显示是否能够正确恢复。

不允许把 EPSG:3857 的普通瓦片 URL 强行当作 EPSG:3413 原生瓦片使用。

## 13. 核查 S-57 渲染链与底图的关系

必须检查：

```
Render Bundle
TileWMS Merger
GWC
mapRenderScheduler
viewport scheduling
```

确认是否存在：

```
S-57 大量瓦片请求
→ 全局队列饱和
→ 底图无法及时显示
```

或者：

```
renderMode 切换
→ S-57 Bundle dispose
→ 错误影响底图
```

底图不能进入 S-57：

```
runtimeLayers
selectedLayerIds
attachedLayerIds
activeLayerIds
warmingLayerIds
suspendedLayerIds
```

等状态集合。

任何模式下：

```
standard
smart
overview
```

底图均应正常工作。

## 14. 检查资源泄漏

长时间使用后空白，还应检查：

```
Object URL 未释放
TileLayer 重复创建
XYZ Source 重复创建
事件监听器未卸载
定时器堆积
未完成的 fetch
WebGL context
Canvas 内存
大量缓存 Blob
```

使用浏览器 Performance/Memory 工具进行前后对比。

重点测试：

```
保持页面运行 30 分钟
连续平移缩放
重复切换底图
重复切换投影
连续切换海冰日期
反复开关环境图层
```

资源消耗不应持续无界增长。

# 第四部分：S-57 航道要素提取与分类

## 15. 功能定位

新增功能名建议：

```
S-57 航道专题信息
```

这是现有海图图层加载的扩展功能。

目标不是通过图像识别从海图 PNG 中“抓取”航道，而是从真实 S-57 数据经 GDAL 导入后的 PostGIS 要素表和属性中查询航道相关对象。

必须保留对象类别、属性和几何之间的原始语义。

## 16. 重点研究 S-57 对象

参考当前前端：

```
frontend/src/utils/s57ObjectNames.ts
```

已存在名称映射：

```
FAIRWY - 航道
RECTRC - 推荐航路
NAVLNE - 航行线
TWRTPT - 双向航路段
TSSLPT - 交通分隔线
TSSBND - 交通分隔带边界
TSEZNE - 交通分隔区域
CTNARE - 航道管制区域
DRGARE - 疏浚区域
CANALS - 运河
```

同时审查：

```
TSSRON
ACHARE
BERTHS
PILPNT
RESARE
DEPARE
DEPCNT
SOUNDG
```

其中后面部分只能作为相关或辅助对象，不能全部直接标注为“航道”。

必须按实际 S-57 对象目录和当前文件支持情况区分：

```
航道与推荐路线
交通分隔制
航行限制与管制
航道环境辅助要素
```

对象代码应逐个核对现有 GDAL/S-57 解析结果和权威对象定义，不能只凭中文名称推测语义。

## 17. 修正当前后端专题分类覆盖不完整的问题

当前：

```
backend/app/services/s57_layer_catalog.py
```

已有：

```
CORE_CHART
NAVIGATION_RECOMMENDED
OPTIONAL_THEMATIC
METADATA_QUALITY
```

以及：

```
_ROUTING
```

但当前 `_ROUTING` 主要涵盖：

```
TSSBND
TSSLPT
TSEZNE
TSSRON
```

没有形成全面的航道对象分类。

本次建议新增独立分类定义，例如：

```
S57_WATERWAY_OBJECT_CLASSES = frozenset({
    "FAIRWY",
    "RECTRC",
    "NAVLNE",
    "TWRTPT",
    "TSSLPT",
    "TSSBND",
    "TSEZNE",
    "TSSRON",
    "CTNARE",
    "DRGARE",
    "CANALS",
})
```

注意：此集合仅是待核对的候选集合，正式实现必须逐类确认定义及对象用途。

同时增加更细分类元数据，例如：

```
fairway
recommended_route
navigation_line
traffic_separation
controlled_area
dredged_area
canal
```

分类规则要能扩展，但不应改变原有 S-57 核心海图加载档案的语义。

## 18. S-57 数据提取方式

优先使用已经导入的 PostGIS 数据。

现有链路：

```
S-57 .000 + 更新文件
        ↓
GDAL / ogr2ogr
        ↓
PostgreSQL geo schema
        ↓
Layer metadata
        ↓
GeoServer
```

应该在此基础上构建：

```
航道专题分类
        ↓
关联原始 Layer
        ↓
查询原始要素表
        ↓
返回属性 + GeoJSON
        ↓
前端专题显示
```

不建议每次用户搜索都重新打开原始 `.000` 文件并执行 `ogrinfo`。

如果某些 S-57 属性在导入时未保留，应分析导入配置并增加兼容处理。

不得为了实现搜索而重新导入覆盖全部已有数据库表。

## 19. 需要提取的属性

根据各个 S-57 对象实际具备的字段动态提取。

候选字段包括：

```
RCID
OBJNAM
NOBJNM
INFORM
NINFOM
CAT*
STATUS
RESTRN
CONDTN
DATSTA
DATEND
SCAMIN
QUASOU
```

以及相关对象可能存在的：

```
DRVAL1
DRVAL2
```

注意：

- 不是每个对象都具备这些字段；
- 字段名应以 GDAL 实际导入后的列名为准；
- `DRVAL1/DRVAL2` 等深度字段不可一律解释为航道保证水深；
- `CAT*` 类属性要结合对应对象的属性定义解释，不能仅依据相同前缀统一翻译；
- `RCID`、对象 ID、数据集 ID、图层 ID 不能混为同一个标识。

建议在服务层建立：

```
属性原始值
字段定义
显示中文名
解释值
来源
```

的只读转换逻辑。

原始字段不得丢失。

## 20. 处理真实文件的特殊情况

必须覆盖：

```
同一对象在多个 ENC Cell 中出现
基础文件与更新链
对象删除/更新
同名不同要素
无名称但有几何的航道对象
只有属性没有可渲染几何的对象
不同几何类型
S-57 属性缺失
```

特别要求：

**不能将空间相邻的多个 FAIRWY 或 NAVLNE 对象自行拼接成一条连续安全航路。**

S-57 中的航道、推荐航路和交通分隔对象，与智能规划算法生成的路径不是同一概念。

本次只做真实对象的查询与展示。

# 第五部分：航道信息查询 API

## 21. 复用当前属性查询基础

当前：

```
backend/app/api/layers.py
```

已有：

```
POST /api/v1/layers/{layerId}/features/search
```

支持：

```
字段白名单
属性过滤
bbox
分页
GeoJSON Geometry
```

新功能应在此基础上实现项目级跨图层搜索。

不建议让前端对全部 S-57 图层分别发一次查询请求后再合并结果，这会造成大量 HTTP 请求和数据库压力。

## 22. 新增航道专题 API

建议：

```
GET /api/v1/projects/{projectId}/s57-waterways/catalog
```

返回：

```
支持的航道相关对象类别
中文名
实际存在数量
对应图层
是否可查询
```

新增：

```
POST /api/v1/projects/{projectId}/s57-waterways/search
```

支持：

```
{
  "keyword": "航道名称",
  "objectClasses": [
    "FAIRWY",
    "RECTRC",
    "NAVLNE"
  ],
  "bbox": null,
  "page": 1,
  "pageSize": 20
}
```

再新增：

```
GET /api/v1/projects/{projectId}/s57-waterways/{featureId}
```

返回某个真实对象的详细信息。

实际 ID 应设计为可唯一定位：

```
项目
数据集/版本
图层
源要素
```

的稳定复合标识或服务端生成的 opaque ID。

不要直接把 RCID 当成全局唯一主键。

## 23. 安全和数据一致性

查询必须：

- 校验用户是否有权访问项目；
- 只查询该项目已关联且允许查询的图层；
- 使用当前有效的数据集版本；
- 对表名和字段名进行白名单校验；
- SQL 值使用参数绑定；
- 限制分页大小；
- 限制 bbox 范围和响应数据量；
- 对缺失或失效图层优雅降级；
- 防止 SQL 注入。

不得从前端传入未经校验的：

```
schema
table
column
```

直接拼接 SQL。

必须复用当前项目的认证和图层访问控制逻辑。

## 24. 查询性能

对于大规模全球海图：

```
多个 ENC Cell
多个 FAIRWY Layer
大量 Feature
```

必须支持分页与空间范围过滤。

需要时增加适当的空间索引或属性索引。

但不能在每次搜索时创建索引。

跨图层查询应考虑：

```
COUNT
LIMIT
OFFSET
```

的性能。

如果最终需要统一索引表，应先分析是否值得增加数据库迁移。

建议优先做不破坏现有数据的联邦式查询，再根据实测性能决定是否增加物化索引。

# 第六部分：前端航道专题信息 UI

## 25. 新增功能入口

建议在现有海图图层面板增加：

```
航道专题
```

入口。

示意：

```
图层目录

├── 底图
├── S-57 海图图层
├── 海冰
├── 环境叠加
└── 航道专题
```

展开：

```
航道专题

[搜索航道名称或属性]

对象类别：
☑ 航道
☑ 推荐航路
☑ 航行线
☑ 交通分隔制
☐ 管制区域
☐ 疏浚区域

[搜索]
[清空]
```

具体样式必须服从当前 Polar-GIS 现有 UI。

## 26. 搜索结果

建议：

```
搜索结果 23 条

航道要素 A
类型：FAIRWY
来源：某 ENC Cell
[定位] [详情] [显示]

推荐航路 B
类型：RECTRC
来源：某 ENC Cell
[定位] [详情] [显示]
```

当 OBJNAM/NOBJNM 不存在时，显示：

```
未命名航道要素
```

并附上：

```
类别
来源
对象标识
```

不能生成假名称。

支持：

```
按对象类型过滤
按名称搜索
当前视口内搜索
分页
清空筛选
```

## 27. 独立专题显示

新增：

```
S57WaterwayOverlay
```

使用一个独立：

```
VectorLayer
```

展示用户选择的航道专题对象。

只加载当前搜索结果、当前视口或用户选中的有限要素。

不要把全世界所有航道一次性作为 GeoJSON 加到浏览器。

地图样式可参考：

```
航道面：半透明青蓝色
推荐航路：蓝色线
航行线：青色虚线
交通分隔制：黄色或橙色
选中对象：高亮描边
```

具体配色需与现有海图风格协调，并和已有航路绘制图层保持明显区别。

## 28. 地图定位

用户点击：

```
定位
```

时：

```
获取 Geometry
        ↓
确认源 CRS
        ↓
转换为当前 Map CRS
        ↓
计算 extent
        ↓
map.getView().fit()
```

必须考虑左右面板展开状态。

定位对象时不改变：

```
地图投影
已选海图
海冰日期
航路草稿
规划结果
```

## 29. 航道要素详情

点击详情应展示：

```
中文对象类别
S-57 原始对象代码
名称
原始属性
中文属性解释
来源 ENC
数据集版本
几何类型
空间范围
更新时间（如数据可证实）
```

对于属性缺失：

```
未提供
```

不要随意填入默认值。

对于需要查阅的属性，可以增加：

```
原始属性 / 中文解释
```

双视图。

## 30. 与原有航线的区别

航道专题：

```
S-57 原始海图要素
```

航路绘制：

```
用户手动绘制
```

智能规划：

```
算法生成的候选路径
```

三者必须完全区分。

航道专题的 Feature 不得自动写入：

```
routesStore
```

也不得被当前航路：

```
Draw
Modify
Select
```

意外修改。

## 31. 地图交互互斥

当前地图已有：

```
航路选中
要素识别
风险网格点选
气象查询
海冰 hover
```

新增航道专题点选时，必须统一处理优先级。

建议只在：

```
航道专题选择模式开启
```

时优先处理航道要素。

同时保证用户仍然可以：

```
平移
缩放
切换投影
关闭专题
```

不能添加新的全局点击监听器导致一次点击重复触发多个功能。

# 第七部分：完整测试计划

## 32. 海冰稳定性测试

至少增加：

```
useIceOverlay.test.ts
tileRequestQueue.test.ts
```

重点覆盖：

```
A → B → C 快速切换
A → B → A
连续切换 30 次
连续切换 100 次
请求中 abort
排队中 abort
网络 429
网络 502
网络 503
网络 504
图片解码失败
过期响应返回
关闭图层中止请求
重复打开图层
投影切换中止请求
```

不能只检查 `setSource()` 被调用。

必须验证最终当前瓦片实际进入可显示状态。

## 33. 底图稳定性测试

至少增加：

```
MapWorkspaceBasemap.test.ts
```

或与现有测试结构相匹配的文件。

覆盖：

```
XYZ 首次加载
XYZ 失败重试
WMTS Capabilities 失败
底图切换
长时间运行
EPSG:3413/3857
第三方服务临时不可用
底图手动恢复
恢复后 source 正常
```

对第三方服务失效的测试应通过 Mock/本地测试服务完成，而非向公共底图提供商进行高强度压力测试。

## 34. S-57 航道测试

建议：

```
backend/tests/test_s57_waterway_catalog.py
backend/tests/test_s57_waterway_api.py

frontend/src/components/S57WaterwayPanel.test.ts
frontend/src/composables/useS57Waterways.test.ts
frontend/src/utils/mapS57Waterway.test.ts
```

覆盖：

```
FAIRWY
RECTRC
NAVLNE
TWRTPT
TSSLPT
TSSBND
TSEZNE
```

并覆盖：

```
无名称
多数据集
重复 RCID
字段缺失
图层不存在
非空间对象
bbox 查询
分页
权限
SQL 注入防护
GeoJSON
双投影显示
搜索后定位
专题关闭后卸载
```

## 35. 端到端回归

必须真实执行：

```
cd frontend
npm run typecheck
npm test
npm run build
```

以及：

```
cd backend
pytest
```

再根据仓库已有部署命令验证：

```
cd deploy
docker compose config
docker compose ps
```

重点场景：

```
S-57 + 海冰时间轴
S-57 + 航道专题
S-57 + 智能规划航线
海冰 + 航道专题
风险栅格 + 航道专题
航路绘制 + 航道专题
海图批量加载 + 长时间地图浏览
```

不能只通过静态单元测试宣布浏览器空白问题已经修复。

# 第八部分：执行阶段

按下面四个独立阶段完成。

## 阶段一：诊断与海冰修复

首先复现海冰时间轴空白。

输出：

```
复现步骤
实际日志
根因证据
修复代码
新测试
```

优先修复：

```
generation
AbortController
retry timer
TileState
queue lifecycle
Source refresh
```

不能为了修复海冰破坏 S-57 TileRequestQueue。

## 阶段二：底图长期稳定性修复

调查：

```
XYZ/WMTS
第三方 Tile 服务
缓存
请求队列
Source ERROR
Canvas
投影
资源泄漏
```

实现有界重试与局部恢复。

不要修改现有 S-57 图层分类。

## 阶段三：航道专题功能

先后端：

```
对象分类
项目内图层解析
属性搜索
详情接口
```

再前端：

```
航道专题入口
搜索面板
结果列表
地图独立叠加
选中高亮
详情弹窗
```

对于未提供航道对象的 S-57 数据集，应正确显示：

```
当前数据未检索到航道专题要素
```

不得构造假数据。

## 阶段四：联合回归与文档

验证现有全功能。

更新：

```
docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
```

记录：

```
根因
修改
测试
效果
限制
```

# 第九部分：最终验收标准

## A. 海冰时间轴

达到：

```
连续快速切换日期
→ 当前日期瓦片正常加载
→ 不出现长期永久空白
→ 无须浏览器刷新
```

## B. 底图

达到：

```
地图保持长时间运行
→ 地图平移缩放正常
→ 临时网络错误后可恢复
→ 不依赖浏览器 F5
```

## C. S-57 航道

达到：

```
导入真实 S-57 文件
→ 找到已存在的航道相关要素
→ 通过名称/类别检索
→ 返回真实属性
→ 地图定位
→ 独立显示
→ 点选详情
```

## D. 无回归

以下功能必须保持：

```
S-57 批量加载
智能渲染模式
GWC
海冰
环境叠加
智能规划
路线比较
风险评估
航路编辑
测量
截图
打印
```

## 最终交付报告

请按以下结构输出：

1. 当前仓库 HEAD 和 Git 状态。
2. 三项任务的实际根因/现有功能分析。
3. 关键修复说明。
4. 新增及修改文件清单。
5. 海冰请求生命周期修复说明。
6. 底图恢复机制说明。
7. S-57 航道对象分类与真实数据证据。
8. 航道查询 API。
9. 航道专题 UI 与地图交互。
10. 前后端测试结果。
11. 浏览器长期运行测试结果。
12. Docker/Nginx/GeoServer 验证。
13. 性能前后对比。
14. 未验证场景与残留问题。
15. `git diff --stat`。
16. 推荐 Git Commit 信息。

不要编造成功结果。

没有真实数据验证的功能，必须明确标记未验证。

不要自动提交或推送代码。

**本次任务最终要求不是简单消除一两次空白，而是使 Polar-GIS 的地图瓦片加载具备可靠的请求生命周期、故障恢复和可诊断能力；同时让真实 S-57 航道数据从静态海图升级为可搜索、可定位、可查询、可高亮的交互式专题信息。**