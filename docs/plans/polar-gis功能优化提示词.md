你是一名熟悉 Vue 3、TypeScript、OpenLayers 10、FastAPI、SQLAlchemy、PostgreSQL/PostGIS、GeoServer、GeoWebCache、WMS、WMTS和S-57电子海图的高级全栈GIS工程师。

现在需要对现有Polar-GIS项目进行“海图批量加载性能优化”。

当前问题是：用户在地图工作台中批量选择并加载一定数量的S-57海图数据集后，浏览器页面出现明显卡顿、交互响应变慢、地图瓦片长时间空白、部分瓦片加载失败或加载缓慢。

必须在不改变当前系统总体架构、不删除现有功能、不改变S-57导入和版本模型的前提下完成优化。

# 一、开始前必须阅读

完整阅读：

- CLAUDE.md
- docs/02-system-design.md
- docs/03-data-design.md
- docs/04-api-design.md
- docs/05-ui-ux-design.md
- docs/09-system-architecture.md
- docs/10-work-log.md
- docs/11-work-summary.md
- docs/12-user-manual.md

重点分析：

- frontend/src/views/MapWorkspaceView.vue
- frontend/src/utils/mapLayerBatch.ts
- frontend/src/api/projects.ts
- frontend/src/api/client.ts
- frontend/src/types/index.ts
- frontend/src/styles.css
- backend/app/api/projects.py
- backend/app/api/layers.py
- backend/app/services/geoserver.py
- backend/app/services/importer.py
- backend/app/services/s57_layer_catalog.py
- backend/app/services/s57_basemap.py
- backend/app/core/config.py
- deploy/compose.yml
- deploy/.env.example
- Nginx配置文件
- GeoServer和GeoWebCache现有配置

先输出当前代码中的真实加载链路、性能瓶颈和影响文件，不得直接根据提示词假设函数名称和实现。

# 二、现有实现必须保留

当前系统已经具备：

1. 数据集级懒加载。
2. `POST /api/v1/projects/{projectId}/map-layers/resolve`批量解析接口。
3. `core_chart`、`navigation_recommended`和`all_spatial`加载档案。
4. 每批创建5个WMS图层、批间间隔200ms。
5. 候选图层超过40层确认、超过120层阻止。
6. 单图层失败隔离。
7. 批量加载取消。
8. 按数据集、搜索结果和全部海图图层卸载。
9. 非空间图层自动过滤。
10. `attachWmsLayer()`和`detachWmsLayer()`或其等价实现。
11. TileWMS加载状态监听。
12. 加载状态300ms延迟显示。
13. 属性查询和要素识别AbortController。
14. EPSG:3857和EPSG:3413投影切换。
15. GeoServer和GeoWebCache。
16. 全球海图概览Layer Group：
    `polar_global_enc_overview`
17. 全球概览WMTS底图。
18. 属性查询直接访问PostGIS，不依赖GeoServer WFS。

所有上述功能必须保留。

不得：

- 更换OpenLayers。
- 引入Mapbox或MapLibre替换现有地图。
- 改为前端直接解析S-57。
- 删除独立业务WMS图层。
- 删除属性查询、透明度、图例、排序和卸载功能。
- 取消数据集懒加载。
- 新增微服务或消息队列。
- 重写S-57导入流程。
- 把全部业务图层永久合并成一个不可控制的图层。
- 把全球概览WMTS用于要素查询。
- 破坏全球海图底图现有功能。
- 把真实海图文件提交到Git。

# 三、首先增加性能诊断

在修改加载策略前，增加轻量性能统计，避免只凭感觉调整参数。

## 3.1 前端统计

在地图工作台维护：

```
interface MapTilePerformanceStats {
  activeLayerCount: number
  attachedLayerCount: number
  suspendedLayerCount: number
  pendingTileCount: number
  loadedTileCount: number
  failedTileCount: number
  retriedTileCount: number
  averageTileDurationMs: number
  p95TileDurationMs: number
  currentGeneration: number
}
```

统计：

- 每个图层的tileloadstart数量；
- tileloadend数量；
- tileloaderror数量；
- 首块瓦片加载时间；
- 当前等待瓦片数；
- 最近60秒平均加载时间；
- 最近60秒失败数；
- 当前OpenLayers业务图层对象数；
- 当前真正激活请求的图层数。

默认不在普通用户界面长期展示详细调试数据。

开发环境可在地图状态区域增加折叠式“性能详情”，生产环境只显示：

```
活动图层 12
等待瓦片 18
失败瓦片 1
```

不得在控制台持续打印每个瓦片请求。

## 3.2 服务端诊断

检查Nginx和GeoServer日志。

增加或确认记录：

- request time；
- upstream response time；
- HTTP状态码；
- GeoServer WMS/GWC请求路径；
- GWC命中和未命中；
- 超时；
- 502、504；
- 请求图片大小。

不得把Cookie、Authorization或GeoServer密码写入日志。

# 四、建立双通道渲染模式

新增地图渲染模式：

```
type ChartRenderMode =
  | 'standard'
  | 'smart'
  | 'overview'
```

## 4.1 standard

完全保持原有行为：

- 用户打开的业务图层都创建独立WMS；
- 保留现有兼容模式；
- 不自动暂停用户要求显示的图层；
- 显示性能风险提示。

## 4.2 smart

批量加载默认推荐使用该模式。

行为：

1. 低缩放级别优先显示全球概览WMTS。
2. 只激活与当前视口相交的业务图层。
3. 只激活适用于当前比例尺的业务图层。
4. 控制正在首次加载的图层并发数。
5. 移出视口的图层进入休眠。
6. 休眠图层一段时间后按LRU卸载。
7. 用户选择状态不变。
8. 图层进入休眠不等于用户关闭图层。
9. 用户放大或移动到图层范围后自动恢复。
10. 保留所有原有图层操作。

## 4.3 overview

只显示已登记的全球海图概览WMTS，不创建批量业务WMS。

该模式用于：

- 全球或北极大范围浏览；
- 快速定位；
- 低性能设备；
- 大批量海图选择后的预览。

Overview模式不支持对WMTS直接进行属性查询。用户需要切换到smart或standard并放大后查询业务图层。

# 五、区分用户选择状态和实际渲染状态

当前系统不能再只用一个`loadedLayerIds`表示全部状态。

增加或整理为：

```
selectedLayerIds: Set<string>
attachedLayerIds: Set<string>
activeLayerIds: Set<string>
warmingLayerIds: Set<string>
suspendedLayerIds: Set<string>
failedLayerIds: Map<string, string>
manuallyForcedLayerIds: Set<string>
```

语义：

- selected：用户要求显示。
- attached：已经创建OpenLayers对象。
- active：当前处于可见并允许发起瓦片请求。
- warming：正在等待首批瓦片。
- suspended：用户仍选择，但由于视口、比例尺或渲染预算暂时休眠。
- manuallyForced：用户明确要求强制显示，不受智能休眠限制。
- failed：加载失败。

原有单图层开关继续控制selected状态。

不得让自动休眠修改用户的选择开关。

图层行增加小型状态文字：

```
已显示
加载中
视口外休眠
比例尺外休眠
等待加载
加载失败
```

# 六、新增视口和比例尺感知调度器

新建：

```
frontend/src/utils/mapRenderScheduler.ts
frontend/src/utils/mapRenderScheduler.test.ts
```

实现纯函数和调度逻辑。

核心函数建议：

```
buildRenderPlan()
isLayerInViewport()
isLayerInScaleRange()
sortRenderCandidates()
selectActiveLayers()
selectLayersForWarmup()
selectLayersForEviction()
```

输入至少包括：

```
interface RenderPlanInput {
  selectedLayers: ResolvedMapLayer[]
  currentProjection: string
  viewExtent: Extent
  zoom: number
  resolution: number
  attachedLayerIds: ReadonlySet<string>
  activeLayerIds: ReadonlySet<string>
  warmingLayerIds: ReadonlySet<string>
  manuallyForcedLayerIds: ReadonlySet<string>
  renderMode: ChartRenderMode
}
```

输出：

```
interface RenderPlan {
  activate: string[]
  attach: string[]
  suspend: string[]
  detach: string[]
  remainActive: string[]
  overviewVisible: boolean
  reasonByLayerId: Map<string, string>
}
```

# 七、视口范围裁剪

必须使用resolve API已经返回的图层extent。

在当前投影下：

1. 将图层范围转换到当前地图投影。
2. 使用OpenLayers extent相交判断。
3. 图层范围与当前视口完全不相交时：
   - 不创建新图层；
   - 已创建图层设置为休眠；
   - 不发送瓦片请求。
4. 给视口范围增加少量缓冲区，避免轻微平移导致频繁启停。

建议：

```
VIEWPORT_BUFFER_RATIO = 0.2
```

即在当前视口四周增加约20%的缓冲。

必须正确处理：

- EPSG:3857；
- EPSG:3413；
- 跨越180度经线的数据；
- extent缺失；
- extent转换失败。

extent缺失时不能直接判定为视口外，可按较低优先级处理。

# 八、比例尺分级显示

扩展`s57_layer_catalog.py`中的规则，但保持它仍然是后端分类事实来源。

增加可选渲染提示：

```
min_scale_denominator
max_scale_denominator
low_zoom_visible
render_cost
```

使用现有`layers.metadata_json["s57"]`保存，不强制新增数据库列。

旧数据没有这些字段时动态计算。

建议规则方向：

## 8.1 低缩放概览层

低缩放只允许：

```
SEAARE
DEPARE
ICEARE
LNDARE
COALNE
DEPCNT
```

其中等深线应设置合理的最小显示比例尺，避免全球范围绘制大量细线。

## 8.2 中缩放层

逐步启用：

```
UNSARE
CTNARE
RESARE
HRBARE
SLCONS
推荐航路和分道通航对象
```

## 8.3 高缩放细节层

仅在较大比例尺启用：

```
SOUNDG
LIGHTS
FOGSIG
BOY*
BCN*
TOPMAR
WRECKS
OBSTRN
UWTROC
```

特别是：

- SOUNDG不得在全球或大范围低缩放级别全部绘制。
- 灯标、浮标和顶标不得在低缩放级别大量堆叠。
- MAGVAR、SBDARE等专题对象默认不进入智能概览模式。

具体比例尺不能仅凭提示词写死。

实现前应结合：

- 数据集compilationScale；
- 项目minZoom/maxZoom；
- S-57对象类别；
- 当前已有SLD；
- EPSG:3857和EPSG:3413分辨率；

确定默认值，并将默认值集中维护。

前端和GeoServer样式不能分别维护两套相互冲突的比例尺规则。

# 九、智能渲染预算

新增可配置常量：

```
SMART_MAX_ACTIVE_WMS_LAYERS = 20
SMART_MAX_WARMING_LAYERS = 3
SMART_MAX_ATTACHED_WMS_LAYERS = 40
SMART_SUSPEND_EVICT_DELAY_MS = 30000
SMART_RECONCILE_DEBOUNCE_MS = 150
```

含义：

- active：当前真正可见和请求瓦片的业务图层。
- warming：正在等待首块瓦片的图层。
- attached：已经存在OpenLayers对象，包括休眠对象。

规则：

1. 同时首次加载的图层最多3个。
2. 一个图层首块瓦片成功、失败或超过设定超时后，才允许下一个图层进入warming。
3. 已经完成首屏加载的图层不占warming名额。
4. 当前视口候选图层超过20个时：
   - 按displayPriority排序；
   - 核心层优先；
   - 用户手动强制层优先；
   - 当前视口覆盖率高的层优先；
   - 低优先级层进入等待或休眠；
   - 界面明确显示“因性能保护暂停N层”。
5. 用户可以点击“强制显示全部”，切换到standard模式。
6. standard模式继续保留120层硬限制。
7. 智能模式不得静默隐藏图层，必须显示状态和原因。

这些参数应集中在`mapLayerBatch.ts`或新的配置文件中，不得散落在组件里。

# 十、地图移动和缩放优化

监听：

- movestart；
- moveend；
- change；
- 当前投影变化。

要求：

## 10.1 movestart

- 不执行大规模图层增删。
- 不重复重建computed数据。
- 不主动清空已有瓦片。
- 保持已有画面，等待移动结束。
- 明确设置TileLayer不在交互过程中持续更新瓦片。

检查OpenLayers 10.6实际API后，合理配置：

```
updateWhileAnimating
updateWhileInteracting
preload
transition
```

不得使用不存在或已废弃的API。

## 10.2 moveend

使用150ms防抖后：

1. 计算新视口。
2. 构建RenderPlan。
3. 暂停视口外图层。
4. 恢复进入视口的图层。
5. 按warming队列加载新图层。
6. 不重复创建已attached图层。
7. 不重新请求没有变化的图层。

# 十一、休眠和LRU卸载

图层离开视口后先休眠，不立即销毁。

休眠方式应优先：

```
layer.setVisible(false)
```

休眠超过30秒，并且attached图层数超过40时，再按LRU调用现有`detachWmsLayer()`释放。

LRU依据：

- 最近进入视口时间；
- 最近显示时间；
- 是否用户强制；
- 是否核心图层；
- 是否正在查询或打开属性表。

以下图层不得被普通海图LRU清理：

- 底图；
- 全球海图概览WMTS；
- AIS；
- 气象；
- 测量；
- 选择高亮；
- 编辑图层；
- 当前属性查询高亮图层。

# 十二、充分使用全球概览WMTS

系统已经存在：

```
polar_global_enc_overview
```

以及对应GWC和BaseMap配置。

智能模式中：

1. 当缩放级别低于业务细节阈值时自动保持概览WMTS可见。
2. 业务WMS图层未准备完成时继续显示WMTS，避免地图出现大片空白。
3. 业务核心图层首批瓦片完成后，可根据配置降低概览WMTS透明度或隐藏。
4. 业务图层加载失败时不要清空概览WMTS。
5. 投影切换时使用对应投影的WMTS。
6. 如果EPSG:3413 WMTS不可用，保留原有底图并显示警告。
7. WMTS不计入业务活动图层数量。
8. WMTS不参与业务图层批量卸载。
9. WMTS不参与属性查询。

不得在低缩放时同时显示概览WMTS和所有对应核心WMS，避免重复渲染。

# 十三、业务WMS接入GeoWebCache

检查当前业务TileWMS URL。

在不影响原有GeoServer图层发布的前提下，优先让适合缓存的业务图层通过GeoWebCache服务加载，例如：

```
/geoserver/gwc/service/wms
```

或当前部署实际支持的等价地址。

要求：

1. 不在前端硬编码完整GeoServer域名。
2. 继续通过Nginx同源代理。
3. EPSG:3857使用正确GridSet。
4. EPSG:3413使用现有或已创建的北极GridSet。
5. OpenLayers瓦片网格必须与GWC对齐。
6. 设置`tiled=true`或GeoServer/GWC要求的等价参数。
7. 图层没有GWC配置时自动回退普通WMS。
8. 回退不能造成无限重试。
9. 缓存能力通过后端resolve响应返回，不由前端猜测。

扩展resolve响应中的可选字段：

```
renderTransport: 'gwc_wms' | 'wms'
tileServiceUrl: string
gridSet?: string
cacheable: boolean
```

这些字段为可选字段，保持旧客户端兼容。

不得向前端返回GeoServer管理员凭据。

# 十四、OpenLayers TileWMS配置优化

在现有`attachWmsLayer()`中统一创建Source和Layer。

检查并合理设置：

```
new TileWMS({
  url,
  params,
  serverType: 'geoserver',
  hidpi: false,
  transition: 0,
  crossOrigin: 'anonymous'
})
```

是否支持以及具体字段以项目当前OpenLayers 10.6类型定义为准。

优化目标：

1. 关闭不必要的高DPI重复渲染，避免高分屏请求过大瓦片。
2. 不预加载额外缩放级别瓦片。
3. 减少透明瓦片淡入合成开销。
4. 继续支持地图截图所需的CORS。
5. 保留透明PNG。
6. 不把空白透明瓦片误判为加载失败。

`preload`保持0或项目当前最小值。

不得把所有图层缓存无限增大。

检查OpenLayers当前版本中Tile缓存配置实际归属，采用类型安全方式设置有限缓存。

# 十五、瓦片请求取消和重试

现有TileWMS图片请求无法完全依赖普通Axios AbortController。

检查当前TileWMS加载方式。

在必要时实现统一的`tileLoadFunction`：

1. 使用fetch加载瓦片。
2. 使用AbortController记录到图层级请求集合。
3. 图层卸载、休眠或投影切换时取消未完成请求。
4. 成功后生成Object URL。
5. 图片完成或取消后及时`URL.revokeObjectURL()`。
6. 保持同源凭据策略。
7. 保持浏览器缓存。
8. 避免内存泄漏。

重试规则：

- 只重试网络错误、429、502、503、504。
- 404不重试。
- 普通透明瓦片不重试。
- 最多重试2次。
- 退避时间例如300ms、1000ms。
- 图层已经休眠或generation变化后不再重试。
- 切换投影后的旧请求结果不得写入新投影图层。

如果自定义fetch会破坏CORS、截图或浏览器缓存，则保留原TileWMS加载方式，仅实现错误统计和有限的source refresh。

不得为了重试无限添加随机查询参数，避免绕过GWC缓存。

# 十六、投影切换双缓冲

当前系统切换投影时会重建视图和必要图层。

优化为：

1. 增加`renderGeneration`。
2. 投影切换时旧generation停止接收状态更新。
3. 创建新投影图层时先进入warming。
4. 至少一个核心图层或新投影WMTS首块瓦片成功后，再移除旧显示层。
5. 设置合理超时。
6. 超时后显示新投影，但保留明确错误提示。
7. 旧瓦片请求全部取消。
8. 不复用不同投影的错误瓦片缓存。
9. selectedLayerIds保持不变。
10. suspended和active状态根据新视图重新计算。

避免投影切换期间整张地图长时间全白。

# 十七、GeoServer样式优化

检查现有S-57 SLD。

为高密度图层增加比例尺规则：

- SOUNDG仅在较大比例尺显示。
- LIGHTS、BOY、BCN、TOPMAR仅在适当比例尺显示。
- DEPCNT按比例尺减少细级别等深线。
- COALNE和LNDARE可在低缩放显示。
- WRECKS、OBSTRN和UWTROC在过小比例尺下关闭。
- 标签使用冲突避免和合理间距。
- 不在低缩放绘制大量文字。
- 不在低缩放绘制复杂点符号。

SLD规则应使用：

```
<MinScaleDenominator>
<MaxScaleDenominator>
```

不得依赖前端单方面隐藏。

前端比例尺控制用于减少请求，SLD比例尺控制用于减少GeoServer渲染压力，两者应使用同一后端规则来源生成或校验。

# 十八、PostGIS优化

检查所有GeoServer空间表。

确保：

1. 有效几何图层存在GiST空间索引。
2. 非空间图层不发布WMS。
3. 导入完成并创建索引后执行ANALYZE。
4. 大型更新完成后只分析本次涉及表。
5. 不在Web请求线程执行长时间VACUUM FULL。
6. 查询和GeoServer使用正确SRID。
7. 不在每个瓦片请求中执行无索引ST_Transform过滤。
8. nativeBoundingBox和latLonBoundingBox有效。
9. GeoServer数据存储连接池大小与PostgreSQL最大连接数匹配。

在importer中增加或确认：

```
CREATE INDEX ... USING GIST (geom);
ANALYZE schema.table;
```

必须使用安全的标识符引用，不拼接未验证的用户输入。

# 十九、可选的低缩放简化数据

只有在完成前端调度、GWC和比例尺SLD后仍然性能不足时，再实现该阶段。

可为高复杂度线面图层生成简化视图或物化视图：

```
geo_generalized
```

候选对象：

- COALNE
- LNDARE
- DEPARE
- DEPCNT
- ICEARE

使用：

- ST_SimplifyPreserveTopology；
- 合理网格吸附；
- 有效性检查。

要求：

1. 原始表保持不变。
2. 查询和导出继续访问原始图层。
3. 简化层仅用于低缩放渲染。
4. 版本更新成功后异步重建。
5. 简化层生成失败不影响原始数据集有效版本。
6. 不在本阶段实现复杂矢量瓦片架构。

# 二十、Nginx和部署优化

检查Nginx代理。

确认或增加：

- GeoServer upstream keepalive；
- 合理的connect/read/send timeout；
- HTTP/2；
- 静态和瓦片响应缓存头透传；
- 不对PNG重复gzip；
- 不缓存4xx和5xx错误；
- 保留完整查询字符串作为缓存键；
- 限制单客户端异常高并发；
- 记录upstream响应时间。

如增加Nginx proxy_cache：

1. 仅针对公开且可缓存的GWC瓦片。
2. 不缓存管理API。
3. 不缓存带用户权限差异的业务响应。
4. 不缓存错误响应。
5. GWC仍然是主要瓦片缓存，Nginx只作为短期热点缓存。
6. 更新数据集版本后必须能失效旧缓存。

检查GeoServer容器JVM配置。

不要直接写死超大堆内存。

根据容器内存设置可配置环境变量，并在文档中说明。

# 二十一、UI调整

在批量加载确认框增加：

```
渲染模式：
○ 智能渲染（推荐）
○ 标准渲染
○ 仅概览底图
```

智能渲染说明：

```
仅加载当前视口和当前比例尺需要的海图图层，
大范围浏览时优先使用缓存概览底图。
```

批量进度区域增加：

- 用户已选择图层数；
- 当前活动图层数；
- 休眠图层数；
- 等待加载图层数；
- 瓦片失败数；
- 当前模式。

增加操作：

- 切换智能/标准模式；
- 强制显示当前休眠图层；
- 恢复智能调度；
- 清理休眠图层缓存；
- 查看性能详情。

保持当前紧凑深色图层面板风格。

不得增加大型全宽性能面板。

# 二十二、兼容性要求

1. 原有单图层开关行为保留。
2. 原有透明度调节保留。
3. 原有图层排序保留。
4. 原有属性表保留。
5. 原有要素识别保留。
6. 原有批量加载接口保留。
7. 原有40/120限制保留。
8. 原有批量取消保留。
9. 原有卸载方式保留。
10. 原有投影切换保留。
11. 原有全球概览底图保留。
12. 原有普通底图保留。
13. 原有AIS、气象、测量和高亮图层保留。
14. 旧数据无新metadata时继续动态回退。
15. 新增响应字段全部为向后兼容的可选字段。
16. 优先不增加数据库迁移。
17. 渲染规则优先写入现有metadata_json。
18. standard模式必须能恢复到优化前的显示语义。

# 二十三、建议修改文件

前端：

```
frontend/src/views/MapWorkspaceView.vue
frontend/src/utils/mapLayerBatch.ts
frontend/src/utils/mapRenderScheduler.ts
frontend/src/utils/mapRenderScheduler.test.ts
frontend/src/api/projects.ts
frontend/src/types/index.ts
frontend/src/styles.css
```

后端：

```
backend/app/services/s57_layer_catalog.py
backend/app/services/geoserver.py
backend/app/services/importer.py
backend/app/api/projects.py
backend/app/schemas.py
backend/app/core/config.py
backend/tests/test_s57_layer_catalog.py
backend/tests/test_project_map_layers.py
backend/tests/test_importer.py
```

部署：

```
deploy/compose.yml
deploy/.env.example
deploy/nginx.conf
```

文档：

```
docs/02-system-design.md
docs/04-api-design.md
docs/05-ui-ux-design.md
docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
```

实际路径以仓库为准。

# 二十四、前端测试

新增测试：

1. 图层在视口外时不进入active。
2. 图层进入视口后恢复active。
3. 图层离开视口后进入suspended。
4. extent缺失时不会错误永久隐藏。
5. 比例尺不满足时不创建瓦片请求。
6. 用户强制图层优先。
7. 核心图层优先于专题图层。
8. 同时warming图层不超过3个。
9. 首块瓦片完成后启动下一图层。
10. warming超时后继续队列。
11. active图层不超过配置预算。
12. standard模式保持旧语义。
13. overview模式不创建业务WMS。
14. 智能模式低缩放使用概览WMTS。
15. LRU不卸载底图和辅助图层。
16. 投影切换后旧generation响应被忽略。
17. 旧瓦片请求被取消。
18. Tile错误最多重试2次。
19. 404不重试。
20. 卸载图层后Object URL被释放。
21. 批量取消停止后续图层warming。
22. 属性表打开的图层不会被LRU清理。
23. 切换模式不改变selectedLayerIds。
24. 原有mapLayerBatch测试继续通过。

# 二十五、后端测试

新增测试：

1. resolve返回extent。
2. resolve返回比例尺提示。
3. resolve返回renderTransport。
4. GWC可用时返回gwc_wms。
5. GWC不可用时回退wms。
6. 不暴露GeoServer管理员凭据。
7. core_chart低缩放规则正确。
8. SOUNDG低缩放不可见。
9. 未知对象回退规则不变。
10. 旧metadata动态补全。
11. 新导入写入渲染提示。
12. 空间索引创建。
13. 导入后执行ANALYZE。
14. 非空间层不发布WMS。
15. GeoServer BBox配置仍有效。
16. GWC配置失败不影响普通WMS。
17. 全球概览Layer Group不受影响。
18. 现有全部测试继续通过。

# 二十六、性能验收

在相同硬件、网络和测试范围下，对优化前后进行对比。

测试场景：

## 场景A：10个海图数据集，核心模式

记录：

- 首次可交互时间；
- 首屏核心瓦片完成时间；
- 总请求数；
- 瓦片失败数；
- GeoServer平均响应时间；
- 浏览器主线程长任务；
- 内存占用。

## 场景B：20个海图数据集，推荐模式

验证：

- 智能模式不发生长时间页面冻结；
- 地图拖动仍可响应；
- 视口外图层进入休眠；
- 同时warming不超过3层；
- 大范围使用WMTS；
- 放大后业务WMS逐步出现。

## 场景C：投影切换

验证：

- EPSG:3857切换EPSG:3413；
- 切换期间不出现长时间全白；
- 旧瓦片结果不污染新投影；
- WMTS失败时业务功能仍可用。

## 场景D：缓存命中

分别测试：

- GWC冷缓存；
- GWC热缓存；
- 相同区域第二次访问。

建议验收目标：

- 智能模式活动业务WMS默认不超过20层；
- 首次并行warming不超过3层；
- 地图拖动时不产生持续大批新图层创建；
- 热缓存瓦片明显快于冷缓存；
- 连续操作不出现明显内存持续增长；
- 单个图层失败不造成整图空白；
- 批量加载期间图层面板仍可交互；
- 原有功能回归测试全部通过。

性能数值必须记录真实测试结果，不能在交付报告中伪造。

# 二十七、实施顺序

第一阶段：

- 分析现有真实代码。
- 增加性能统计。
- 建立优化前基准。
- 不改变渲染行为。

第二阶段：

- 实现视口相交判断。
- 实现比例尺判断。
- 实现selected/active/suspended状态分离。
- 实现RenderPlan纯函数和测试。

第三阶段：

- 实现warming并发调度。
- 实现休眠和LRU。
- 实现smart/standard/overview模式。
- 接入全球概览WMTS。

第四阶段：

- 接入GWC业务瓦片路径。
- 优化TileWMS参数。
- 实现请求取消和有限重试。
- 实现投影切换双缓冲。

第五阶段：

- 优化SLD比例尺规则。
- 确认PostGIS空间索引和ANALYZE。
- 调整GeoServer、GWC和Nginx配置。

第六阶段：

- 执行性能测试和回归测试。
- 根据真实数据调整预算参数。
- 更新所有相关文档。

只有前五个阶段仍无法满足性能要求时，才实施低缩放简化视图。

# 二十八、最终交付报告

完成后必须输出：

1. 根因分析。
2. 优化前性能基准。
3. 修改文件列表。
4. 新增文件列表。
5. 数据库是否迁移。
6. 前端渲染调度说明。
7. smart/standard/overview模式说明。
8. 视口裁剪说明。
9. 比例尺规则说明。
10. warming和LRU说明。
11. GWC接入说明。
12. TileWMS配置说明。
13. GeoServer和PostGIS优化说明。
14. 自动化测试命令和结果。
15. 性能对比数据。
16. 回归测试结果。
17. 已知限制。
18. 回滚方法。

不得只输出“优化完成”。

每项结论必须给出实际代码位置、实际测试结果和实际配置。