# Polar-GIS海图批量加载深度性能优化——分阶段AI开发提示词

------

# 一、所有阶段共同遵守的项目基线

你是一名熟悉Python 3.12、FastAPI、SQLAlchemy 2.0、PostgreSQL/PostGIS、GDAL/OGR、GeoServer、GeoWebCache、Vue 3、TypeScript、OpenLayers 10.6、Element Plus、Nginx和Docker Compose的高级WebGIS工程师。

当前项目为Polar-GIS极地海洋环境信息平台。

## 1. 当前实际架构

后端：

- FastAPI模块化单体。
- PostgreSQL 16 + PostGIS 3.4。
- GeoServer + GeoWebCache。
- API进程与独立Worker进程共享同一代码库。
- Worker通过PostgreSQL任务表领取任务。
- 不使用消息队列。
- S-57通过GDAL/OGR导入PostGIS。
- 每个数据集保留版本链、当前有效版本和原始源文件。
- 属性查询直接查询PostGIS，不通过GeoServer WFS。

前端：

- Vue 3 + TypeScript。
- OpenLayers 10.6。
- TileWMS、WMTS和XYZ图层。
- EPSG:3857和EPSG:3413。
- `MapWorkspaceView.vue`为核心地图工作台。
- 已存在批量解析、批量加载、批量取消和精确卸载。

## 2. 当前已完成的优化

不得重复实现以下功能：

1. 数据集级懒加载。
2. `POST /api/v1/projects/{projectId}/map-layers/resolve`。
3. `core_chart`、`navigation_recommended`和`all_spatial`。
4. 40层二次确认和120层硬限制。
5. `standard`、`smart`、`overview`三种渲染模式。
6. 视口范围裁剪。
7. 比例尺过滤。
8. `selected/attached/active/warming/suspended/failed/manuallyForced`状态分离。
9. `mapRenderScheduler.ts`纯函数调度器。
10. warming预算、活动预算和LRU卸载。
11. 智能模式活动图层预算30层。
12. warming上限10层。
13. attached上限60层。
14. moveend 150ms防抖。
15. 瓦片加载时间和错误统计。
16. TileWMS失败重试。
17. 图层动态zIndex。
18. Vue Set状态使用`shallowRef`。
19. HTTP/2。
20. Nginx GeoServer瓦片proxy_cache。
21. 静态资源缓存头。
22. GeoServer JVM内存和G1GC配置。
23. 导入后创建GiST空间索引并执行ANALYZE。
24. S-57空间图层自动启用GWC。
25. 全球概览Layer Group：
    `polar_global_enc_overview`
26. 全球概览WMTS底图。
27. 非空间图层不发布WMS。
28. 属性查询和Identify请求取消。
29. S-57分类事实来源：
    `backend/app/services/s57_layer_catalog.py`

## 3. 所有阶段的硬性约束

不得：

- 更换OpenLayers。
- 引入Mapbox或MapLibre替换现有地图。
- 删除独立业务图层。
- 删除属性查询、导出、图例、透明度和排序功能。
- 改变S-57导入和版本链语义。
- 修改当前有效版本的原子切换原则。
- 让前端直接读取S-57文件。
- 将全球概览WMTS用于属性查询。
- 新增微服务或消息队列。
- 在API请求线程执行长时间GeoServer、GDAL、缓存预热或简化数据任务。
- 提交真实ENC数据、缓存文件、凭据或`.env`。
- 使用`docker compose down -v`。
- 伪造性能测试数据。

必须：

- 保留`standard`模式作为完整兼容回退。
- 所有新增API均为加法变更。
- 优先复用现有模型和metadata_json。
- 无法复用时才新增数据库迁移。
- 每个阶段都单独提交、测试、文档更新和验收。
- 所有失败不得破坏当前有效图层、底图或数据版本。
- 每阶段开始前先检查真实代码，不能直接假定提示词中的函数和行号存在。

## 4. 每阶段统一开始步骤

执行每个阶段前：

1. 阅读：
   - `CLAUDE.md`
   - `docs/02-system-design.md`
   - `docs/03-data-design.md`
   - `docs/04-api-design.md`
   - `docs/05-ui-ux-design.md`
   - `docs/09-system-architecture.md`
   - `docs/10-work-log.md`
   - `docs/11-work-summary.md`
   - `docs/12-user-manual.md`
2. 检查Git状态。
3. 确认当前分支。
4. 检查当前全部测试结果。
5. 输出真实加载链路和本阶段实际影响文件。
6. 建立本阶段优化前性能基准。
7. 不得直接修改尚未阅读的代码。

## 5. 统一性能基准场景

每阶段完成前后均使用相同场景：

### 场景A

- 10个S-57数据集。
- `core_chart`。
- EPSG:3857。
- 冷缓存和热缓存各一次。

### 场景B

- 20个S-57数据集。
- `navigation_recommended`。
- 连续平移、缩放60秒。

### 场景C

- 30个以上数据集。
- 智能模式。
- EPSG:3857切换EPSG:3413。

记录：

- 当前逻辑图层数量。
- 当前OpenLayers TileLayer数量。
- 首屏请求数量。
- 首屏可见时间。
- 首屏完整时间。
- 平均瓦片耗时。
- P95瓦片耗时。
- 失败瓦片数。
- 重试次数。
- GeoServer CPU和内存。
- PostgreSQL活动连接。
- 浏览器长任务。
- 浏览器内存。
- GWC命中率。
- Nginx缓存命中率。

------

# 第二部分：第一阶段提示词——组合图层渲染通道

## 阶段目标

在保留所有逻辑图层、独立查询、独立导出和标准模式的前提下，将智能模式下大量独立TileWMS请求，压缩为少量语义组合TileWMS请求。

本阶段是后续优化的最高优先级。

当前问题的本质是：

```text
30个独立图层 × 当前视口瓦片数量
= 大量独立HTTP请求
= 大量GeoServer渲染任务
= 大量PostGIS空间查询
= 浏览器大量Canvas合成
```

目标是将智能模式常见的20～30个活动业务图层压缩成约3～6个组合渲染图层。

## 1. 设计原则

建立两套同时存在但职责不同的图层模型。

### 1.1 逻辑图层

继续保留现有：

- layerId。
- datasetId。
- objectClass。
- 单层开关。
- 图层顺序。
- 图例。
- 属性查询。
- 导出。
- 元数据。
- 选择状态。

逻辑图层不因组合渲染而消失。

### 1.2 渲染图层

智能模式下，由多个逻辑图层组成少量渲染Bundle。

默认语义分组：

```text
area_fill
  SEAARE
  DEPARE
  ICEARE
  LNDARE
  UNSARE
  CTNARE
  RESARE
  HRBARE

line_structure
  COALNE
  DEPCNT
  NAVLNE
  FAIRWY
  TSSBND
  TSSLPT
  SLCONS
  其他线型航路与边界

hazard_detail
  WRECKS
  OBSTRN
  UWTROC
  SOUNDG

navigation_aid
  LIGHTS
  FOGSIG
  BOY*
  BCN*
  TOPMAR
  RTPBCN

optional_other
  未归入以上类别且允许显示的对象
```

最终分组规则必须从后端S-57分类事实来源派生，不得在前端复制另一套对象集合。

## 2. 两级组合策略

### 2.1 动态多图层WMS

优先实现。

通过一次WMS GetMap请求携带逗号分隔的：

```text
LAYERS=layerA,layerB,layerC
STYLES=styleA,styleB,styleC
```

实现一个Bundle对应一个TileWMS。

优点：

- 不需要为每次选择创建GeoServer持久资源。
- 不新增数据库表。
- 立即减少浏览器请求数量。
- Nginx可以按完整URL缓存相同组合。

要求：

1. 保持LAYERS和STYLES顺序严格对齐。
2. 按现有displayPriority和zIndex语义稳定排序。
3. 一次Bundle图层数量设置安全上限，例如20。
4. 超过上限拆成多个Bundle。
5. URL长度超过安全值时自动拆分。
6. 不允许前端提交任意GeoServer图层名。
7. 后端必须从项目权限范围内生成组合计划。

### 2.2 稳定组合Layer Group

仅用于稳定、重复出现的组合：

- 项目默认核心海图组合。
- 项目默认推荐海图组合。
- 全球概览组合。
- 管理员明确保存的渲染预设。

使用确定性名称：

```text
project_{projectCode}_{profile}_{projection}_{hash8}
```

不得为每一次地图移动或临时选择创建GeoServer Layer Group。

## 3. 新增后端渲染计划服务

建议新增：

```text
backend/app/services/map_render_plan.py
backend/tests/test_map_render_plan.py
```

提供纯函数和业务函数：

```python
build_map_render_plan(...)
build_render_bundles(...)
select_standalone_layers(...)
bundle_cache_key(...)
```

新增加法API：

```http
POST /api/v1/projects/{projectId}/map-render/plan
```

请求：

```json
{
  "layerIds": ["uuid"],
  "profile": "core_chart",
  "projection": "EPSG:3857",
  "renderMode": "smart",
  "viewExtent": [-180, -90, 180, 90],
  "zoom": 6
}
```

请求中的layerIds只能是当前已发布项目中可访问的图层。

响应示例：

```json
{
  "generation": "hash",
  "bundles": [
    {
      "bundleId": "area_fill:abc123",
      "bucket": "area_fill",
      "layerIds": ["uuid1", "uuid2"],
      "layerNames": [
        "polar_gis:layer_a",
        "polar_gis:layer_b"
      ],
      "styles": [
        "polar_gis:style_a",
        "polar_gis:style_b"
      ],
      "zIndex": 10,
      "opacity": 1,
      "extent": [],
      "minZoom": null,
      "maxZoom": null,
      "transport": "wms_multi",
      "serviceUrl": "/geoserver/polar_gis/wms",
      "cacheKey": "sha256"
    }
  ],
  "standaloneLayers": [],
  "summary": {
    "logicalLayerCount": 30,
    "bundleCount": 4,
    "standaloneCount": 2,
    "estimatedRequestReductionRatio": 0.8
  }
}
```

不得返回GeoServer管理员凭据。

## 4. 哪些图层必须保持独立

以下情况不能合并，必须作为standaloneLayer：

1. 用户修改了单层透明度。
2. 用户应用了临时自定义样式。
3. 用户手动强制显示。
4. 正在进行图层级调试。
5. 图层服务不支持组合请求。
6. 图层投影或格式不兼容。
7. 图层使用不同图像格式。
8. 图层需要与Bundle不同的过滤参数。
9. 图层当前处于编辑状态。
10. 管理员明确设置`renderStandalone=true`。

## 5. 单层透明度兼容

组合图层无法直接支持Bundle内部每层不同透明度。

采用“提升为独立覆盖层”策略：

1. 用户修改某逻辑图层透明度。
2. 将该层从原Bundle移除。
3. 防抖重建原Bundle。
4. 将该层作为独立TileWMS加载。
5. 用户恢复默认透明度后，可重新并入Bundle。
6. 用户选择状态保持不变。

不得直接把整个Bundle透明度改成该单层透明度。

## 6. 图层开关兼容

用户关闭Bundle内某个逻辑图层时：

1. 更新selectedLayerIds。
2. 重新计算Bundle。
3. 使用200ms左右防抖。
4. 新Bundle首块瓦片成功前保留旧Bundle。
5. 新Bundle成功后替换旧Bundle。
6. 失败时继续保留旧Bundle并显示错误。

避免每次单层开关出现整片空白。

## 7. 属性查询兼容

属性查询继续使用现有PostGIS接口。

点击地图时：

- 不对Bundle调用统一GetFeatureInfo。
- 使用逻辑图层注册表判断可查询层。
- 继续调用现有identify或属性查询API。
- 查询层范围与当前视口、比例尺和用户选择保持一致。
- Bundle仅负责视觉显示。

## 8. 前端运行时模型

建议新增：

```text
frontend/src/utils/mapRenderBundles.ts
frontend/src/utils/mapRenderBundles.test.ts
```

状态：

```ts
interface RenderBundleRuntime {
  config: RenderBundleConfig
  layer: TileLayer<TileWMS> | null
  status: 'idle' | 'warming' | 'active' | 'failed' | 'replacing'
  generation: number
  pendingReplacement?: RenderBundleRuntime
}
```

新增集合：

```ts
activeBundleIds
warmingBundleIds
failedBundleIds
```

原有逻辑图层状态继续存在。

## 9. 与三种模式的关系

### standard

完全保持独立WMS。

不得使用Bundle。

### smart

默认使用Bundle。

特殊图层使用standalone。

### overview

继续只显示全球概览WMTS。

不得创建业务Bundle。

## 10. GeoServer和Nginx要求

1. 动态组合WMS继续走同源Nginx代理。
2. 不绕过现有认证与网络边界。
3. Nginx缓存键必须包含完整请求参数。
4. 缓存不同LAYERS、STYLES、CRS和版本组合。
5. 不缓存GetCapabilities。
6. 不缓存错误响应。
7. 数据版本切换后Bundle cacheKey必须变化。
8. 不依赖手动清空全部缓存解决版本问题。

## 11. 建议影响文件

后端：

```text
backend/app/services/map_render_plan.py
backend/app/api/projects.py
backend/app/schemas.py
backend/app/services/s57_layer_catalog.py
backend/tests/test_map_render_plan.py
backend/tests/test_projects.py
```

前端：

```text
frontend/src/views/MapWorkspaceView.vue
frontend/src/utils/mapRenderBundles.ts
frontend/src/utils/mapRenderBundles.test.ts
frontend/src/utils/mapRenderScheduler.ts
frontend/src/api/projects.ts
frontend/src/types/index.ts
frontend/src/styles.css
```

部署：

```text
deploy/nginx/default.conf
```

## 12. 自动化测试

后端测试：

1. 30个逻辑图层能生成不超过配置数量的Bundle。
2. LAYERS与STYLES顺序严格一致。
3. 不同zIndex类别不会错误合并。
4. 不同投影不会合并。
5. 不同透明度不会合并。
6. 项目外图层被拒绝。
7. 非空间图层不会进入Bundle。
8. 不可用图层不会进入Bundle。
9. 相同输入生成相同bundleId和cacheKey。
10. 数据版本变化后cacheKey变化。
11. URL过长时自动拆分。
12. 旧resolve API不受影响。

前端测试：

1. smart模式使用Bundle。
2. standard模式继续独立WMS。
3. overview模式不创建Bundle。
4. 单层关闭触发Bundle替换。
5. 替换过程中旧Bundle保持显示。
6. 新Bundle首块瓦片后原子替换。
7. 单层透明度变化后提升为standalone。
8. 恢复默认透明度后重新并入Bundle。
9. 属性查询仍以逻辑图层执行。
10. Bundle卸载不影响底图和辅助图层。
11. 投影切换后旧Bundle响应被忽略。
12. 批量取消停止后续Bundle加载。

## 13. 验收目标

场景B中：

- 逻辑图层约30层时，实际业务TileWMS数量目标不超过6～10个。
- 首屏瓦片请求数量比独立WMS模式减少60%以上。
- 地图拖动时主线程长任务明显减少。
- 属性查询、透明度、图例、排序和单层开关均保持可用。
- standard模式显示结果与优化前一致。

## 14. 回滚

增加前端配置：

```env
VITE_ENABLE_RENDER_BUNDLES=false
```

或等价运行配置。

关闭后：

- smart模式暂时回退原有独立WMS调度器。
- 不删除任何数据。
- 不修改任何当前有效版本。
- 不影响全球概览WMTS。

## 15. 阶段交付

完成后输出：

1. 实际根因。
2. 实际修改文件。
3. Bundle分组规则。
4. API契约。
5. 逻辑层和渲染层关系。
6. 测试结果。
7. 优化前后请求数量。
8. 首屏性能对比。
9. 已知限制。
10. 回滚方法。

第一阶段未通过验收前，不进入第二阶段。

------

# 第三部分：第二阶段提示词——自适应背压与空间调度优化

## 阶段目标

在第一阶段组合渲染基础上，将固定的warming和active预算改为根据实时性能动态调整的自适应背压机制。

当前固定值：

```text
warming = 10
active = 30
attached = 60
```

固定高并发在GeoServer较慢时可能造成：

- 请求大量排队。
- 503或504增加。
- 瓦片重试形成二次压力。
- GeoServer CPU持续满载。
- PostgreSQL连接池拥塞。

本阶段不再盲目提高固定预算。

## 1. 自适应控制模型

新增：

```text
frontend/src/utils/adaptiveRenderBudget.ts
frontend/src/utils/adaptiveRenderBudget.test.ts
```

输入：

```ts
interface AdaptiveBudgetInput {
  currentWarmingLimit: number
  currentActiveLimit: number
  pendingTileCount: number
  averageTileDurationMs: number
  p95TileDurationMs: number
  errorRate: number
  retryRate: number
  recentSuccessfulTiles: number
  recentFailedTiles: number
  isInteracting: boolean
}
```

输出：

```ts
interface AdaptiveRenderBudget {
  warmingLimit: number
  activeLimit: number
  state: 'healthy' | 'busy' | 'degraded' | 'recovering'
  reason: string
}
```

## 2. 控制算法

采用简化AIMD思想：

### 健康状态

满足：

- P95低于目标阈值。
- 错误率低。
- pending数量可控。
- 最近窗口有持续成功。

则：

- 每个评估窗口最多增加1个warming名额。
- active预算缓慢增加。
- 不超过配置上限。

### 繁忙状态

满足任一：

- P95持续上升。
- pending瓦片超过阈值。
- GeoServer响应明显变慢。

则：

- 暂停增加并发。
- 保持或小幅降低warming。

### 降级状态

满足任一：

- 502、503、504明显增加。
- 网络失败率超过阈值。
- pending持续堆积。
- P95超过严重阈值。

则：

- warming预算立即按比例降低。
- 暂停低优先级Bundle。
- 停止自动重试低优先级瓦片。
- 保留概览WMTS和核心Bundle。

### 恢复状态

连续多个健康窗口后逐步恢复，不得瞬间恢复到最大值。

## 3. 配置边界

建议初始值：

```text
MIN_WARMING = 2
MAX_WARMING = 10
MIN_ACTIVE_BUNDLES = 4
MAX_ACTIVE_BUNDLES = 12
EVALUATION_WINDOW_MS = 3000
HEALTHY_WINDOWS_TO_INCREASE = 2
DEGRADED_COOLDOWN_MS = 10000
```

具体值必须由真实性能测试调整。

## 4. 避免重试风暴

现有瓦片最多重试2次。

新增约束：

1. 降级状态下，低优先级Bundle不重试。
2. 同一主机同时处于退避中的瓦片设置总上限。
3. 429遵守`Retry-After`。
4. 503/504采用带抖动指数退避。
5. 用户移动后，旧视口请求和重试全部取消。
6. generation变化后旧请求不再写入状态。
7. 不通过随机URL参数绕过缓存。
8. 同一瓦片避免多个Bundle运行时重复重试。

## 5. 引入空间索引

当前调度器每次moveend可能遍历全部逻辑图层。

当项目候选图层超过设定数量，例如100层时，引入R树空间索引。

建议：

```text
frontend/src/utils/layerExtentIndex.ts
frontend/src/utils/layerExtentIndex.test.ts
```

可采用成熟的轻量TypeScript R树库，也可以实现经过测试的不可变索引。

要求：

1. 索引保存转换后的投影extent。
2. EPSG:3857和EPSG:3413分别缓存。
3. projection变化时切换索引，不复用错误坐标。
4. extent缺失图层进入保守候选集合。
5. moveend只查询与20%缓冲视口相交的图层。
6. 数据集更新后局部重建。
7. 不在每次moveend重新转换全部extent。

## 6. Bundle优先级

调度顺序：

1. 当前用户手动强制的standalone层。
2. area_fill。
3. line_structure。
4. hazard_detail。
5. navigation_aid。
6. optional_other。

同一类别中：

1. 当前视口覆盖率较高。
2. displayPriority较高。
3. 缓存已命中或近期成功。
4. 距地图中心较近。
5. 稳定ID排序。

不得仅按返回顺序调度。

## 7. 交互过程控制

### movestart

- 暂停创建新Bundle。
- 取消尚未开始的warmup。
- 已显示瓦片继续保留。
- 不立即清空图层。
- 不执行LRU清理。

### moveend

- 150ms防抖。
- 查询空间索引。
- 构建新RenderPlan。
- 先加载area_fill。
- 再加载line_structure。
- 再加载细节。
- 根据当前预算逐步进入warming。

## 8. 渐进式画面替换

避免地图空白：

1. 旧视口Bundle暂时保留。
2. 新视口area_fill首块或首屏达到阈值后切换。
3. line和point继续渐进补齐。
4. 超时后保留概览WMTS。
5. 单个Bundle失败不清空其他Bundle。
6. 投影切换采用相同双缓冲语义。

## 9. 后端轻量健康提示

如果现有系统健康接口适合扩展，可增加不含敏感信息的渲染负载提示：

```json
{
  "mapRender": {
    "status": "healthy",
    "geoserverAvailable": true
  }
}
```

前端背压主要依据自身瓦片数据，不能依赖高频轮询后端。

不得每秒新增API健康请求。

## 10. 测试

1. 健康窗口后预算逐步增加。
2. 错误增加后预算快速降低。
3. 恢复时不会立即升到最大值。
4. pending过高时停止增加。
5. 降级状态低优先级Bundle停止重试。
6. 429遵守Retry-After。
7. generation变化取消旧请求。
8. R树只返回视口候选。
9. EPSG:3857和3413索引隔离。
10. extent缺失图层保守保留。
11. movestart不创建新Bundle。
12. moveend按语义顺序加载。
13. 旧画面在新画面准备前保持。
14. standard模式不使用自适应控制。
15. overview模式不创建业务Bundle。

## 11. 验收

- 高负载时503/504数量低于固定高并发方案。
- pending瓦片不会持续无限增长。
- GeoServer CPU峰值更平稳。
- 用户持续拖动时页面保持可操作。
- 地图不出现频繁全白。
- 热缓存环境下预算可自动恢复。
- 不损害第一阶段的请求压缩效果。

## 12. 回滚

配置：

```env
VITE_ADAPTIVE_RENDER_BUDGET=false
```

关闭后恢复固定预算，但保留第一阶段Bundle渲染。

------

# 第四部分：第三阶段提示词——多比例尺简化渲染数据

## 阶段目标

当前端请求数已经明显减少后，进一步降低单个瓦片的GeoServer和PostGIS渲染成本。

本阶段只为低、中缩放显示生成简化派生数据。

原始数据继续用于：

- 属性查询。
- Identify。
- 导出。
- 数据版本管理。
- 高缩放精细显示。
- 回滚。

## 1. 适用对象

首批只处理高复杂度线面对象：

```text
LNDARE
COALNE
DEPARE
DEPCNT
ICEARE
SEAARE
```

暂不处理：

- SOUNDG。
- LIGHTS。
- BOY*。
- BCN*。
- TOPMAR。
- WRECKS。
- OBSTRN。
- UWTROC。
- 其他点对象。

点对象继续依赖比例尺规则和组合渲染。

## 2. 派生数据架构

新增独立渲染Schema：

```text
geo_render
```

不得修改`geo`中的原始表。

为每个数据集当前有效版本生成：

```text
{source_table}__z_low__3857
{source_table}__z_mid__3857
{source_table}__z_low__3413
{source_table}__z_mid__3413
```

如果实际表名长度超过PostgreSQL限制，使用稳定短哈希。

## 3. 分级规则

不直接按固定经纬度容差简化。

必须在目标投影坐标中简化。

建议：

### low

用于全球或大范围：

- 简化误差约等于目标缩放级别2～4个屏幕像素。
- 只保留SLD渲染必需字段。
- 可以进行适当网格吸附。

### mid

用于区域浏览：

- 简化误差约等于1～2个屏幕像素。
- 保留更多几何细节。

### high

继续使用原始`geo`表。

具体阈值必须根据EPSG:3857和EPSG:3413的目标分辨率计算，不得把相同米数盲目用于全部层级。

## 4. 几何处理

建议处理链：

```sql
ST_Transform
→ ST_SnapToGrid
→ ST_SimplifyPreserveTopology
→ ST_MakeValid（必要时）
→ ST_CollectionExtract
→ ST_Multi（按原类型需要）
```

要求：

1. 多边形简化后保持拓扑尽可能有效。
2. 线对象不能被错误转成面。
3. 空几何和无效几何要记录但不能中断整个数据集。
4. 处理跨180度经线海图。
5. 记录输入和输出要素数量。
6. 记录输入和输出顶点数量。
7. 创建GiST索引。
8. 执行ANALYZE。
9. 不执行阻塞系统的`VACUUM FULL`。

## 5. 字段裁剪

读取当前SLD，确定真正用于渲染的属性字段。

派生表只保存：

- 主键或稳定要素ID。
- 几何。
- SLD渲染必需字段。
- 必要对象分类字段。
- 数据版本追踪字段。

不能未经检查删除SLD使用的属性。

## 6. 后台任务

不得在API线程生成简化表。

复用现有Worker和任务表。

优先检查：

- import_jobs是否支持扩展任务类型。
- S-57批次metadata是否可记录派生状态。
- 当前版本激活后的后处理钩子。

如果现有任务模型能复用，不新增表。

只有无法表达以下状态时才新增最小迁移：

```text
queued
running
succeeded
failed
cancelled
```

任务应支持：

- 重试。
- 取消。
- 幂等。
- 单数据集重建。
- 批量重建。
- 清理旧版本派生表。

## 7. 版本一致性

派生数据必须绑定datasetVersionId。

新版本流程：

```text
候选版本导入成功
→ 原始图层校验成功
→ 原子切换current_version
→ 异步生成新版本简化数据
→ 简化数据成功后更新渲染计划
→ 清理或延迟清理旧版本派生表
```

简化任务失败：

- 不回滚原始有效版本。
- 智能模式回退原始图层。
- 显示性能降级提示。
- 可单独重试。

## 8. GeoServer发布

简化表作为仅渲染图层发布。

命名包含：

- 数据集。
- 版本。
- 对象类。
- 层级。
- 投影。
- 稳定哈希。

不得覆盖原始GeoServer图层。

渲染计划API返回：

```json
{
  "sourceKind": "generalized",
  "generalizationLevel": "low",
  "sourceLayerId": "原始逻辑图层ID",
  "queryLayerId": "原始逻辑图层ID"
}
```

查询始终指向原始逻辑图层。

## 9. 与Bundle结合

Bundle规划时：

- 低缩放选择low派生层。
- 中缩放选择mid派生层。
- 高缩放选择原始层。
- 各层级使用不同cacheKey。
- 过渡时先加载新层级Bundle，再替换旧层级Bundle。

## 10. API

可增加管理员API：

```http
POST /api/v1/admin/datasets/{datasetId}/render-derivatives/rebuild
GET /api/v1/admin/datasets/{datasetId}/render-derivatives
DELETE /api/v1/admin/datasets/{datasetId}/render-derivatives/obsolete
```

普通地图API只返回可用结果，不暴露内部表名。

## 11. 测试

1. 原始表不被修改。
2. 低、中两个层级生成成功。
3. EPSG:3857和3413隔离。
4. 多边形仍为有效面类型。
5. 线仍为线类型。
6. 无效单要素不会中断全任务。
7. GiST索引存在。
8. ANALYZE执行。
9. 相同版本重复运行幂等。
10. 新版本使用新派生层。
11. 旧版本不会被新计划引用。
12. 简化失败自动回退原始层。
13. 属性查询仍访问原始层。
14. 导出内容不受影响。
15. 删除数据集时清理派生资源。
16. 版本回滚后选择对应版本派生资源或回退原始层。

## 12. 性能验收

记录：

- 原始与简化后的顶点数量。
- 原始与简化后的表大小。
- 冷缓存瓦片渲染时间。
- 热缓存瓦片时间。
- GeoServer CPU。
- PostgreSQL查询计划。
- 地图视觉差异。

验收要求：

- 低缩放核心轮廓无明显破坏。
- 不出现大面积几何裂缝。
- 不出现岸线严重偏移。
- 查询和导出结果不变。
- 低缩放冷缓存瓦片明显快于原始表。

## 13. 回滚

配置：

```env
ENABLE_GENERALIZED_RENDER_LAYERS=false
```

关闭后渲染计划全部回退原始GeoServer图层。

派生表可保留，不影响业务。

------

# 第五部分：第四阶段提示词——GeoWebCache深度缓存与预热

## 阶段目标

在Bundle和简化数据稳定后，优化缓存命中率、北极投影缓存、缓存预热和版本失效机制。

当前系统已经：

- 自动为S-57空间图层启用GWC。
- 使用Nginx proxy_cache。
- 具有全球概览WMTS。
- 支持EPSG:3857和EPSG:3413。

当前明确待完成：

- EPSG:3413 GridSet。
- SLD比例尺规则完善。
- 完整性能场景验收。

## 1. EPSG:3413 GridSet

检查现有`ensure_gridset()`。

创建稳定GridSet：

```text
polar_epsg_3413
```

参数必须基于：

- EPSG:3413官方投影定义。
- 当前系统北极项目extent。
- OpenLayers实际分辨率数组。
- 256×256瓦片。
- 当前支持缩放级别。

前端WMTS tileGrid必须与GWC完全一致。

不得由前端和后端各自计算两套不同分辨率。

后端提供或复用Capabilities解析结果。

## 2. 缓存对象

优先缓存：

1. 全球概览Layer Group。
2. 项目稳定核心Bundle Layer Group。
3. 项目稳定推荐Bundle Layer Group。
4. 多比例尺简化渲染层。
5. 高频独立核心图层。

不优先预热：

- 临时组合。
- 用户临时自定义样式。
- 高频变化过滤条件。
- 大量高缩放全球区域。
- optional_other。

## 3. 缓存版本化

不要依赖全局truncate解决版本更新。

缓存标识应包含：

- datasetVersionId。
- style版本或更新时间。
- projection。
- generalizationLevel。
- bundle hash。

新数据版本生成新图层或新cache namespace。

成功切换后：

- 新缓存生效。
- 旧缓存延迟清理。
- 失败时旧缓存继续可用。

## 4. Metatiling

为线、文字和符号配置合理metatiling。

建议测试：

```text
2×2
4×4
```

不要直接认定4×4一定最好。

配置gutter，避免：

- 标签被瓦片边缘截断。
- 点符号被裁剪。
- 粗线在边缘断裂。

分别测试：

- 面层。
- 线层。
- 点标层。
- 航标文字层。

## 5. 图片格式

测试：

- `image/png`
- `image/png8`

要求：

1. 保持透明度。
2. 保持S-57主要颜色和符号清晰度。
3. PNG8只有在视觉误差可接受且体积明显下降时启用。
4. 不使用JPEG处理透明海图覆盖层。
5. 不因格式变化破坏截图。

## 6. 空白瓦片

确认GWC能够缓存透明空白瓦片。

避免无数据区域反复请求PostGIS。

需要区分：

- 正常透明空白瓦片。
- GeoServer错误返回。
- 超时产生的空响应。

前端不得将正常透明瓦片记为失败。

## 7. 缓存预热任务

复用现有Worker。

新增或扩展任务：

```text
seed
truncate_extent
reseed
cleanup_obsolete
```

管理员API可为：

```http
POST /api/v1/admin/map-cache/seed
POST /api/v1/admin/map-cache/truncate
GET /api/v1/admin/map-cache/jobs/{id}
```

请求必须限制：

- 图层白名单。
- 投影。
- zoomFrom。
- zoomTo。
- extent。
- 并发数。
- 最大瓦片数。

不得允许普通用户发起全局高缩放预热。

## 8. 预热策略

全球概览：

- 只预热低缩放。
- 以实际海图覆盖extent为准。
- 不默认预热全世界空白区域。

区域核心Bundle：

- 预热项目初始extent。
- 预热常用中低缩放。
- 高缩放按需。

EPSG:3413：

- 只预热北极有效范围。
- 避免无意义的全球矩形范围。

## 9. 预热背压

预热任务不能压垮在线地图。

要求：

1. 可配置最大并发。
2. 可暂停和取消。
3. GeoServer在线请求繁忙时降低预热速率。
4. 记录成功、失败、跳过和预计瓦片数。
5. 设置任务超时。
6. 失败可以断点重试。
7. 不在API请求线程等待完成。

## 10. Nginx缓存协同

GWC为主缓存，Nginx为热点二级缓存。

调整要求：

1. 缓存键包含完整URI。
2. 不缓存管理REST。
3. 不缓存GetCapabilities。
4. 不缓存4xx和5xx。
5. 允许`stale-while-revalidate`或等价行为。
6. 数据版本化URL自然失效。
7. 响应增加便于诊断的缓存头：
   - `X-Proxy-Cache`
   - GWC相关命中信息（如可获取）
8. 不暴露内部服务器信息。

## 11. SLD比例尺规则

完成尚未实施的`MinScaleDenominator`和`MaxScaleDenominator`。

规则来源：

```text
backend/app/services/s57_layer_catalog.py
```

不得由SLD和前端各自维护不同阈值。

要求：

- SOUNDG只在大比例尺绘制。
- LIGHTS、BOY、BCN、TOPMAR限制低缩放绘制。
- WRECKS、OBSTRN、UWTROC限制低缩放绘制。
- DEPCNT在低缩放减少细级等深线。
- 文本标签设置冲突避免。
- 低缩放减少复杂符号。

## 12. GeoServer REST连接池

完成尚未实施的GeoServer HTTP客户端连接复用。

在`geoserver.py`中：

- 使用共享`httpx.Client`或等价生命周期客户端。
- 配置连接池。
- 配置connect/read/write/pool timeout。
- 关闭应用时释放。
- 重试仅限幂等REST操作。
- 不对非幂等发布操作盲目重试。

## 13. 测试

1. EPSG:3413 GridSet参数与前端tileGrid一致。
2. GWC可生成3413瓦片。
3. 缓存版本随数据版本变化。
4. 旧缓存不会污染新版本。
5. 空白瓦片可缓存。
6. 4xx/5xx不进入Nginx缓存。
7. 预热限制最大瓦片数。
8. 普通用户不能发起预热。
9. 预热可暂停、取消和恢复。
10. 缓存清理按图层和extent执行。
11. PNG8视觉测试通过后才启用。
12. SLD比例尺规则与分类目录一致。
13. GeoServer客户端复用连接。
14. 现有全球概览WMTS不受影响。

## 14. 验收

- EPSG:3413热缓存加载稳定。
- GWC热缓存响应明显快于冷缓存。
- 相同区域第二次访问请求大部分命中缓存。
- 数据更新后不出现旧海图瓦片。
- 缓存预热期间在线地图仍可正常使用。
- Nginx和GWC缓存职责清晰。

## 15. 回滚

- 禁用缓存预热，不禁用现有GWC。
- EPSG:3413 GridSet创建失败时只回退普通WMS。
- 关闭PNG8时恢复image/png。
- 关闭项目Bundle预热时保留按需缓存。
- 不删除当前有效底图。

------

# 第六部分：第五阶段提示词——GeoServer多实例渲染扩展

## 阶段启动条件

只有满足以下条件才实施：

1. 第一至第四阶段全部完成。
2. Bundle已显著减少请求数量。
3. 自适应背压正常工作。
4. 多比例尺简化已降低单瓦片成本。
5. GWC热缓存命中率正常。
6. 真实性能监控仍显示：
   - GeoServer CPU长期接近饱和；
   - JVM GC或渲染线程成为瓶颈；
   - PostgreSQL未成为主要瓶颈；
   - 网络带宽未成为主要瓶颈。

如果上述条件不成立，停止本阶段，不进行无依据的横向扩展。

## 阶段目标

在不改变前端API、FastAPI模块化单体和数据模型的情况下，将GeoServer在线渲染扩展为多个实例。

## 1. 部署拓扑

```text
Nginx
 ├─ /geoserver-render/ → geoserver-render-1
 │                    → geoserver-render-2
 └─ /geoserver-admin/  → geoserver-primary
```

职责：

### geoserver-primary

- REST发布。
- 样式管理。
- Layer Group管理。
- GWC管理。
- 管理员操作。

### render实例

- 只处理WMS/WMTS/GWC读取请求。
- 不直接接受管理REST。
- 共享相同PostGIS。
- 使用一致的GeoServer配置。

## 2. 配置同步方案

优先选择可控方案。

可选方式：

1. 共享只读GeoServer数据目录。
2. Primary发布后同步配置快照。
3. 容器启动时从版本化配置生成。

不得让多个实例无协调地同时写同一配置目录。

如果共享目录不安全，应采用：

```text
Primary写入
→ 配置版本生成
→ Render实例滚动更新
```

## 3. GWC缓存

必须明确缓存共享方式。

可选：

- 共享GWC磁盘缓存卷；
- 每实例独立缓存；
- 外部共享缓存。

个人开发和单机Docker环境优先：

- Primary和render实例共享只读或经过验证的GWC缓存目录；
- 写入协调必须安全。

如果共享写入存在风险，则各实例独立缓存，并由Nginx保持一致性哈希或粘性分配。

不得未经验证让多个GWC实例同时写入不支持并发的同一缓存目录。

## 4. Nginx负载均衡

新增upstream：

```nginx
upstream geoserver_render {
    least_conn;
    server geoserver-render-1:8080;
    server geoserver-render-2:8080;
    keepalive 64;
}
```

要求：

1. 地图GetMap、WMTS和GWC请求走render upstream。
2. GeoServer REST管理请求只走primary。
3. 健康检查失败自动摘除。
4. 保留完整查询字符串。
5. 保持Nginx缓存键不变。
6. 不对非幂等REST操作负载均衡。
7. 记录选择的upstream实例和响应时间，但不暴露给普通用户。

## 5. 数据库连接控制

增加实例后不能无节制放大PostgreSQL连接数。

必须计算：

```text
API连接
+ Worker连接
+ Primary GeoServer连接
+ Render实例连接
< PostgreSQL max_connections安全范围
```

每个GeoServer datastore设置：

- min connections。
- max connections。
- connection timeout。
- validate connections。
- prepared statements策略。

必须通过压力测试确定，不得直接复制过大的连接池。

## 6. JVM内存

多实例时重新分配容器内存。

例如总内存有限时，不得让每个实例继续使用4GB最大堆。

根据宿主机实际内存设置：

- Primary较小。
- Render实例按负载分配。
- 保留PostgreSQL、Backend、Worker、Nginx和系统内存。

不得造成宿主机交换或OOM。

## 7. 故障处理

1. 一个render实例停止时地图继续工作。
2. Primary停止时已有地图读取仍可工作。
3. Primary恢复后可以继续发布。
4. 配置同步失败时不让不一致实例加入upstream。
5. 新版本配置先在一个render实例验证，再滚动到其他实例。
6. 回滚配置时恢复上一稳定版本。

## 8. Docker Compose

仅在本阶段修改服务拓扑。

建议：

```text
geoserver-primary
geoserver-render-1
geoserver-render-2
```

保留单实例兼容配置：

```env
GEOSERVER_RENDER_REPLICAS=1
```

如果Docker Compose无法动态replicas，提供单实例和双实例两个profile。

## 9. 测试

1. 两个render实例均可读取相同图层。
2. 图层样式一致。
3. Layer Group一致。
4. 一个实例停止后请求继续成功。
5. Primary停止后现有地图仍能读取。
6. REST写操作只发送Primary。
7. Nginx不会把REST发布发送到render实例。
8. 数据库连接总量受控。
9. 缓存不发生损坏。
10. 配置版本不一致的实例不会接流量。
11. 单实例模式仍能启动。
12. 回滚到单实例不丢数据。

## 10. 性能验收

比较：

- 单实例冷缓存。
- 双实例冷缓存。
- 单实例热缓存。
- 双实例热缓存。
- 一个实例故障。

记录：

- 请求吞吐量。
- P95。
- CPU。
- JVM GC。
- PostgreSQL连接。
- 错误率。
- 缓存命中率。

只有冷缓存或实时渲染吞吐确有明显提升，才保留多实例。

热缓存性能主要取决于GWC和Nginx，不应把热缓存收益错误归因于GeoServer实例数量。

## 11. 回滚

1. Nginx upstream恢复Primary单节点。
2. 停止render实例。
3. 不删除PostGIS数据。
4. 不删除GeoServer配置。
5. 不删除GWC缓存。
6. 恢复原Docker Compose profile。

------

# 第七部分：阶段间门禁

必须严格按顺序实施。

## 第一阶段进入第二阶段的条件

- 实际TileWMS数量显著减少。
- 属性查询和单层操作正常。
- standard模式回归通过。

## 第二阶段进入第三阶段的条件

- 自适应预算没有造成频繁抖动。
- 503/504和pending数量下降。
- 渐进显示稳定。

## 第三阶段进入第四阶段的条件

- 简化几何视觉质量通过。
- 查询、导出和原始数据不受影响。
- 低缩放冷缓存性能明显改善。

## 第四阶段进入第五阶段的条件

- 缓存命中和失效机制正确。
- EPSG:3413缓存正常。
- 仍有明确单实例CPU瓶颈证据。

任何阶段未通过验收：

- 停止继续实施。
- 修复当前阶段。
- 不用后续复杂架构掩盖前一阶段问题。

# 第八部分：最终统一交付格式

每个阶段完成后，AI开发工具必须输出：

1. 阶段目标。
2. 优化前真实基准。
3. 根因分析。
4. 修改文件列表。
5. 新增文件列表。
6. 数据库迁移情况。
7. API变化。
8. 前端状态和交互变化。
9. GeoServer/GWC变化。
10. 自动化测试命令。
11. 测试数量与结果。
12. 性能测试环境。
13. 优化前后数据。
14. 回归测试结果。
15. 已知限制。
16. 回滚配置。
17. Git提交信息。
18. 文档更新位置。

不得仅输出“优化已经完成”。

不得用预计性能替代实际测试数据。