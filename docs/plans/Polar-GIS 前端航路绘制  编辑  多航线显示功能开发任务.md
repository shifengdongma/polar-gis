# Polar-GIS 前端航路绘制 / 编辑 / 多航线显示功能开发任务

你是一名熟悉 Vue 3、TypeScript、Pinia、Element Plus、OpenLayers 10、WebGIS 和 GIS 坐标投影的高级前端工程师。

请直接在当前 Polar-GIS 项目代码基础上完成本任务。

项目仓库：

```
https://github.com/shifengdongma/polar-gis
```

目标项目目录以当前实际仓库为准。

------

# 一、开发前必须先完成代码检查

在修改任何代码之前，先完整阅读并理解以下文件：

```text
frontend/src/views/MapWorkspaceView.vue
frontend/src/types/index.ts
frontend/src/stores/projects.ts
frontend/src/api/client.ts
frontend/src/utils/mapExtent.ts
frontend/src/styles.css
frontend/package.json

docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
docs/14-s57-version-update-and-route-drawing-research.md
```

特别检查 `MapWorkspaceView.vue` 中：

```text
buildMap()
switchProjection()
activateMeasure()
clearMeasure()
toggleAis()
reloadAisGeometry()
handleOverlayCommand()
onMounted()
onBeforeUnmount()
map.on('singleclick')
map.on('moveend')
measureSource
measureLayer
aisSource
aisLayer
```

还必须检查当前：

```text
WMS/GWC 图层加载
TileWMS 合并
Bundle 智能渲染
瓦片缓存
TileRequestQueue
批量海图加载
投影切换
AIS
测量功能
要素识别
气象查询
```

本任务不能破坏以上任何已有功能。

不要大规模重构 `MapWorkspaceView.vue`。

不要修改现有 S-57 数据导入、GeoServer、GWC、WMS Tile、Render Bundle、Tile Cache 和调度器逻辑。

------

# 二、本次功能定位

本次实现的是：

**“前端航路规划模拟 / Route Planning Sandbox”**

用于模拟未来正式航线规划模块。

本阶段只要求前端实现完整交互，不要求新增数据库表，也不要求修改 FastAPI 后端。

航路数据采用浏览器本地草稿保存。

后续正式航线规划开发时，再把本地持久化替换成后端 Route API。

因此：

```text
本阶段：
经纬度输入
    ↓
Pinia Route Store
    ↓
WGS84 航路点数据
    ↓
坐标转换
    ↓
OpenLayers LineString
    ↓
VectorLayer
```

未来：

```text
Route API
    ↓
Pinia Route Store
    ↓
保持现有地图绘制层不变
```

不得为了本功能修改现有业务数据库。

------

# 三、总体功能要求

必须完成以下能力：

1. 根据用户输入的经纬度坐标绘制航路。
2. 用户可以在地图上通过鼠标自由绘制航路。
3. 航路至少包含两个航路点。
4. 支持同时存在多条航路。
5. 多条航路可同时显示。
6. 每条航路可以单独显示/隐藏。
7. 可以选中某一条航路。
8. 选中的航路可以进入编辑状态。
9. 可以拖拽已有航路点修改航路。
10. 可以通过表格直接修改某个点的经纬度。
11. 可以增加航路点。
12. 可以删除航路点。
13. 可以删除整条航路。
14. 修改经纬度以后地图线路必须立即更新。
15. 地图拖动时航路同步移动。
16. 地图放大/缩小时航路同步缩放。
17. EPSG:3857 与 EPSG:3413 切换后航路位置保持正确。
18. 多条航路在投影切换后全部正确重建。
19. 航路不能进入现有 WMS/GWC 调度体系。
20. 航路功能关闭后不能影响原地图浏览。
21. 页面刷新后，本项目的本地航路草稿可以恢复。
22. 不同项目的航路草稿必须相互隔离。

------

# 四、数据模型设计

所有航路的真实业务坐标统一保存为：

```text
EPSG:4326
[longitude, latitude]
[经度, 纬度]
```

绝对不能保存 EPSG:3857 或 EPSG:3413 投影坐标作为业务数据。

在：

```text
frontend/src/types/index.ts
```

增加类似以下类型。

具体字段可以按照项目当前 TypeScript 风格调整：

```ts
export interface RoutePoint {
  id: string
  seq: number
  lon: number
  lat: number
}

export interface RouteDraft {
  id: string
  projectId: string
  name: string
  description?: string
  points: RoutePoint[]
  visible: boolean
  createdAt: string
  updatedAt: string
}

export type RouteInteractionMode =
  | 'idle'
  | 'draw'
  | 'edit'
```

如果实际项目已有相同/类似类型，则复用，不允许重复定义。

------

# 五、坐标规则

必须严格遵守：

```text
longitude = 经度 = lon
latitude  = 纬度 = lat

坐标数组：

[lon, lat]
```

合法范围：

```text
-180 <= lon <= 180
-90  <= lat <= 90
```

航路至少两个点。

所有输入必须做数值校验。

以下情况必须提示用户而不是产生错误几何：

```text
空值
非数字
NaN
Infinity
经度越界
纬度越界
航路点不足 2 个
```

错误输入不得写入 Route Store。

------

# 六、新增 mapRoute 工具模块

新增：

```text
frontend/src/utils/mapRoute.ts
```

把纯 GIS / 坐标逻辑放在这里，不要全部塞入 `MapWorkspaceView.vue`。

至少提供以下能力：

```ts
validateRoutePoint()

parseRouteCoordinateText()

buildRouteLineString()

routePointsToProjectedCoordinates()

projectedCoordinatesToRoutePoints()

calculateRouteLength()

normalizeRoutePoints()
```

核心函数：

```ts
buildRouteLineString(
  points: RoutePoint[],
  crs: string
): LineString
```

实现原则：

```ts
points
  .sort((a, b) => a.seq - b.seq)
  .map(point =>
    fromLonLat(
      [point.lon, point.lat],
      crs
    )
  )
```

最终：

```ts
new LineString(projectedCoordinates)
```

反向处理地图拖拽后的坐标时：

```ts
toLonLat(projectedCoordinate, currentCrs)
```

转换回：

```text
[lon, lat]
```

再写回 Route Store。

------

# 七、Pinia 航路 Store

新增：

```text
frontend/src/stores/routes.ts
```

采用项目现有 Pinia Setup Store 风格。

建议：

```ts
useRoutesStore()
```

核心状态至少包括：

```text
routes
activeRouteId
interactionMode
visibleRouteIds
```

建议接口：

```ts
createRoute()
createRouteFromPoints()

deleteRoute()

setActiveRoute()

updateRouteName()

replaceRoutePoints()

updateRoutePoint()

addRoutePoint()

removeRoutePoint()

toggleRouteVisibility()

showAllRoutes()

hideAllRoutes()

clearRoutes()

loadLocalRoutes()

saveLocalRoutes()
```

必须保证 Route Store 保存的是：

```text
EPSG:4326 经纬度
```

而不是当前地图投影坐标。

------

# 八、本地草稿持久化

本阶段不修改后端。

使用：

```text
localStorage
```

按项目 ID 隔离。

推荐 key：

```text
polar-gis:route-drafts:${projectId}:v1
```

例如：

```text
polar-gis:route-drafts:3c87...:v1
```

不要使用一个全局 key 保存所有项目。

读取 localStorage 时必须容错：

```text
JSON 格式错误
字段缺失
旧版本结构
points 非数组
非法经纬度
```

解析失败：

```text
忽略损坏数据
不要导致地图工作台无法加载
```

Route Store 每次重要修改后持久化：

```text
新增航路
删除航路
经纬度修改
拖拽修改
显隐改变
名称修改
增加/删除点
```

------

# 九、航路地图图层设计

航路必须使用 OpenLayers：

```text
VectorSource
+
VectorLayer
+
Feature<LineString>
```

不要：

```text
使用 HTML Canvas 手动画线
使用 SVG absolute overlay
使用 DOM line
使用固定屏幕坐标
```

否则地图缩放时会产生错位。

新增：

```ts
const routeSource = new VectorSource()
```

新增：

```ts
const routeLayer = new VectorLayer({
  source: routeSource,
  zIndex: ...
})
```

zIndex 必须：

```text
高于普通 S-57 WMS 图层

低于现有测量交互和重要交互覆盖层
```

参考当前：

```text
measureLayer zIndex = 100
aisLayer zIndex = 110
```

因此航路层建议：

```text
90 ~ 95
```

具体值结合当前代码决定。

------

# 十、多航路显示

一个 `VectorSource` 中允许存在多条：

```text
Feature<LineString>
```

每个 Feature 必须包含属性：

```text
routeId
routeName
routeType = 'route-draft'
```

例如：

```ts
feature.set('routeId', route.id)
feature.set('routeName', route.name)
feature.set('routeType', 'route-draft')
```

禁止每增加一条航路就创建完整的新地图实例。

原则上也不要为每条航路创建独立 `VectorLayer`。

使用：

```text
1 个 routeLayer
+
N 个 LineString Feature
```

即可。

例如：

```text
routeSource
 ├── Route A Feature
 ├── Route B Feature
 ├── Route C Feature
 └── Route D Feature
```

------

# 十一、航路样式

不同航路需要视觉上能够区分。

可以使用一个固定的小型颜色池，为 routeId 做稳定映射。

要求：

```text
同一条航路刷新后颜色尽量保持一致
不同航路尽量使用不同颜色
选中航路明显高亮
隐藏航路不渲染
编辑中的航路明显区别于普通航路
```

不要生成随机颜色导致每次刷新颜色变化。

样式函数建议：

```ts
function routeStyle(feature, resolution) {
    ...
}
```

普通航路建议：

```text
线宽：2~3 px
```

选中航路：

```text
线宽：4~5 px
```

可以增加轻微外描边提高海图背景下的可见度。

------

# 十二、地图缩放适配——重要

必须理解本需求：

“航线随着地图放大缩小”

指的是：

```text
地图 zoom in
→ 航路在地图上的空间长度同步放大

地图 zoom out
→ 航路在地图上的空间长度同步缩小
```

这个效果应由：

```text
OpenLayers VectorLayer
+
LineString
+
View resolution
```

自然完成。

禁止监听 zoom 后人工计算所有点的屏幕坐标。

禁止用 CSS transform 缩放航路。

正常情况下：

```text
不需要 moveend 重建航路
不需要 zoomend 重建航路
```

只有：

```text
投影改变
```

才重新根据 WGS84 坐标生成 LineString。

线宽可以保持像素级稳定，以保证不同缩放级别下仍然看得清。

如需要轻微视觉变化，可以使用 `resolution` 对线宽做有限范围调整，例如：

```text
最小 2px
最大 5px
```

但不得无限放大。

------

# 十三、自由绘制航路

增加：

```text
“开始绘制航路”
```

功能。

使用 OpenLayers：

```ts
Draw
```

类型：

```ts
LineString
```

用户流程：

```text
点击“新建航路”
        ↓
输入航路名称
        ↓
点击“地图绘制”
        ↓
鼠标单击添加航路点
        ↓
继续单击添加点
        ↓
双击完成
        ↓
生成 RouteDraft
        ↓
地图显示航路
        ↓
自动保存本地草稿
```

Draw 完成后：

必须把当前投影坐标：

```text
EPSG:3857
或
EPSG:3413
```

使用：

```ts
toLonLat()
```

转换为：

```text
EPSG:4326
```

再存 Store。

绝对不要直接把 OpenLayers 平面坐标保存到业务数据。

------

# 十四、经纬度输入绘制

除鼠标绘制外，还必须允许用户直接输入点位。

例如：

```text
航路 A

点 1：
经度：120.123456
纬度：72.123456

点 2：
经度：122.553200
纬度：73.182300

点 3：
经度：125.783200
纬度：74.032100
```

至少提供：

```text
添加点
删除点
修改经度
修改纬度
```

修改坐标后：

```text
Route Store 更新
→ 当前 Route Feature geometry 更新
→ 地图立即变化
```

不允许要求用户刷新地图。

------

# 十五、支持批量粘贴坐标

为了方便测试，增加简单的坐标文本输入功能。

格式支持：

```text
120.123456,72.123456
121.332211,72.553321
123.553211,73.021133
125.821133,74.122311
```

一行一个点：

```text
lon,lat
```

解析后形成：

```text
RoutePoint[]
```

非法行必须明确提示：

```text
第 N 行坐标格式错误
```

不能静默生成错误航路。

允许用户：

```text
覆盖当前点位
```

或至少提供：

```text
“应用坐标”
```

功能。

------

# 十六、拖拽修改航路

必须增加：

```ts
Modify
```

interaction。

不是重新实现拖拽算法。

使用 OpenLayers 官方 Modify interaction。

当用户选中某条航路并点击：

```text
“编辑航路”
```

后：

只允许修改：

```text
当前 activeRoute
```

不能拖动其他航路。

推荐使用：

```ts
Collection<Feature>
```

维护当前可修改 Feature：

```text
activeModifyFeatures
```

然后：

```ts
new Modify({
  features: activeModifyFeatures
})
```

这样即使地图上同时显示 10 条航路，也只能拖动当前选中的一条。

------

# 十七、拖拽完成后的数据同步

监听：

```text
modifyend
```

当用户拖动节点以后：

1. 获取当前 LineString coordinates。
2. 使用当前 `currentCrs`。
3. 每个坐标执行 `toLonLat()`。
4. 转换为 `[lon, lat]`。
5. 重建 `RoutePoint[]`。
6. 更新 Pinia Store。
7. 更新经纬度表格。
8. 保存 localStorage。

形成：

```text
地图拖拽
   ↓
LineString geometry
   ↓
toLonLat()
   ↓
WGS84
   ↓
Route Store
   ↓
经纬度表
```

要求双向同步：

```text
坐标表修改 → 地图变化

地图拖拽 → 坐标表变化
```

------

# 十八、航路选择

支持：

```text
点击航路列表选择
```

最好同时允许：

```text
直接点击地图上的航路线选择
```

可以使用 OpenLayers：

```ts
Select
```

但 Select 必须只作用于：

```text
routeLayer
```

不能影响：

```text
S-57 WMS
AIS
测量层
其他矢量对象
```

选中后：

```text
activeRouteId = routeId
```

并刷新样式。

------

# 十九、节点显示

当航路处于：

```text
选中
或
编辑
```

状态时，应能够看到航路节点。

最简单方案：

依赖 OpenLayers Modify 默认编辑节点即可。

如果需要长期显示节点，可以增加独立：

```text
routeWaypointSource
routeWaypointLayer
```

但必须保证：

```text
普通航路不要生成大量无意义点 Feature
```

推荐：

```text
只有 activeRoute 显示航路点
```

节点可以显示：

```text
1
2
3
4
...
```

但不是强制。

------

# 二十、多航路管理 UI

建议新增组件：

```text
frontend/src/components/RoutePlannerPanel.vue
```

不要把大量模板继续直接写进 `MapWorkspaceView.vue`。

页面入口放在地图右侧工具栏。

增加：

```text
航路规划
```

按钮。

点击后打开：

```text
el-drawer
```

建议宽度：

```text
420 ~ 480px
```

面板顶部明确标注：

```text
航路规划模拟
```

以及：

```text
仅用于功能模拟，不作为实际导航依据
```

------

# 二十一、航路面板布局

建议：

```text
┌──────────────────────────┐
│ 航路规划模拟              │
│ 非实际导航数据             │
├──────────────────────────┤
│ [+ 新建航路] [全部显示]    │
│             [全部隐藏]     │
├──────────────────────────┤
│ ☑ 航路 A                  │
│    5 个航路点   [编辑][删] │
│                          │
│ ☑ 航路 B                  │
│    8 个航路点   [编辑][删] │
├──────────────────────────┤
│ 当前航路：航路 A           │
├──────────────────────────┤
│ #  经度        纬度        │
│ 1  120.123    72.234  ×   │
│ 2  122.232    73.323  ×   │
│ 3  125.322    74.112  ×   │
│ [+ 添加航路点]             │
├──────────────────────────┤
│ [地图绘制] [拖拽编辑]      │
│ [结束编辑] [定位航路]      │
├──────────────────────────┤
│ 批量坐标输入               │
│ 120.1,72.2                │
│ 122.2,73.3                │
│ ...                       │
│ [应用坐标]                 │
└──────────────────────────┘
```

不要求完全照搬 UI，但功能必须完整。

------

# 二十二、航路显隐

每条航路具有：

```text
visible
```

属性。

点击列表前复选框：

```text
Route A visible=false
```

地图应立即隐藏 Route A。

其他路线：

```text
Route B
Route C
```

保持显示。

不能通过：

```ts
routeLayer.setVisible(false)
```

实现单条航路隐藏，因为这会隐藏全部航路。

应针对：

```text
Feature
```

处理显隐。

可以：

```text
style function 返回 null
```

或者维护 source 中实际显示的 features。

优先选择实现简单、无状态冲突的方案。

------

# 二十三、定位到航路

每条航路增加：

```text
定位
```

按钮。

通过：

```ts
feature.getGeometry()?.getExtent()
```

然后：

```ts
map.getView().fit(...)
```

建议：

```text
padding
duration
maxZoom
```

避免只含短航线时放大过度。

------

# 二十四、投影切换适配——必须实现

当前系统支持：

```text
EPSG:3857
EPSG:3413
```

航路 Store 永远保存：

```text
EPSG:4326
```

所以当：

```ts
switchProjection(crs)
```

执行时：

现有逻辑已经会：

```text
清理 WMS
切换 View
重新加载业务图层
reloadAisGeometry()
```

在这里增加：

```ts
reloadRouteGeometry()
```

流程：

```text
Route Store WGS84 points
       ↓
fromLonLat([lon,lat], newCrs)
       ↓
重新构造 LineString
       ↓
更新 Feature geometry
```

不要：

```text
3857 → 3413 → 3857 → 3413
```

连续对已经投影过的 Geometry 做累积 transform。

否则会引入误差和状态复杂度。

永远使用：

```text
原始 WGS84 RoutePoint
```

重新生成。

这与当前 AIS 的 `reloadAisGeometry()` 思路保持一致。

------

# 二十五、绘制/编辑与已有地图交互必须互斥

当前地图已有：

```text
queryMode
weatherMode
measureInteraction
```

新增：

```text
routeInteractionMode
```

必须避免交互冲突。

当开始绘制航路：

```text
queryMode = false
weatherMode = false
结束 measureInteraction
```

当开始拖拽航路：

```text
queryMode = false
weatherMode = false
结束测量 Draw
```

当：

```text
routeInteractionMode !== 'idle'
```

时：

`singleclick` 不应该同时触发：

```text
要素识别
气象查询
```

建议所有交互切换通过一个统一函数管理，例如：

```ts
deactivateMapInteractionsExcept(...)
```

但不要为了这一点大规模重构现有地图逻辑。

------

# 二十六、不要影响现有海图卸载逻辑

当前：

```text
unloadAllChartLayers()
```

只负责业务海图。

航路是用户绘制覆盖层。

因此：

```text
卸载全部海图图层
```

不能把航路清除。

以下也不能影响航路：

```text
批量加载 S-57
批量卸载 S-57
切换 smart/standard
Render Bundle attach/detach
TileWMS 合并
GWC
瓦片缓存
TileRequestQueue
```

航路属于完全独立的：

```text
Vector overlay
```

------

# 二十七、MapWorkspaceView.vue 最小侵入修改

`MapWorkspaceView.vue` 只负责：

```text
挂载 routeLayer
打开 RoutePlannerPanel
处理地图级交互
处理 projection reload
清理 interaction
```

不要把以下内容全部写入该文件：

```text
坐标校验
文本解析
localStorage
Route CRUD
复杂数据转换
大量路线管理 UI
```

这些分别放入：

```text
types
store
utils
component
```

------

# 二十八、建议新增文件

推荐结构：

```text
frontend/src/
├── components/
│   └── RoutePlannerPanel.vue
│
├── stores/
│   ├── projects.ts
│   └── routes.ts                  # 新增
│
├── utils/
│   ├── mapRoute.ts                # 新增
│   └── mapRoute.test.ts           # 新增
│
└── views/
    └── MapWorkspaceView.vue       # 最小修改
```

如果 OpenLayers interaction 逻辑过多，可以进一步新增：

```text
frontend/src/composables/useRouteDrawing.ts
```

负责：

```text
routeSource
routeLayer
Draw
Modify
Select
interaction cleanup
feature sync
projection reload
```

如果这样能明显降低 `MapWorkspaceView.vue` 复杂度，则优先采用。

------

# 二十九、推荐 useRouteDrawing 职责

如果新增：

```text
useRouteDrawing.ts
```

它不要负责 UI。

仅负责地图交互：

```ts
createRouteLayer()

syncRoutesToMap()

syncRouteToMap()

removeRouteFeature()

selectRoute()

startRouteDraw()

stopRouteDraw()

startRouteModify()

stopRouteModify()

reloadRouteGeometry()

fitRoute()

dispose()
```

这样形成：

```text
RoutePlannerPanel
       ↓
Routes Store
       ↓
useRouteDrawing
       ↓
OpenLayers
```

------

# 三十、Undo / Cancel 最低要求

自由绘制至少提供：

```text
取消绘制
```

如果实现成本不高，可以提供：

```text
撤销最后一个点
```

OpenLayers Draw 支持：

```ts
removeLastPoint()
```

可以直接使用。

不要自己重新实现 Draw 状态机。

------

# 三十一、删除规则

删除航路前：

使用：

```text
ElMessageBox.confirm
```

确认。

如果删除的是 activeRoute：

```text
停止 Modify
清空 activeRouteId
移除对应 Feature
删除 Store Route
保存 localStorage
```

删除航路点后：

如果：

```text
points.length < 2
```

不要留下非法 LineString。

可以禁止继续删除，并提示：

```text
航路至少需要两个航路点
```

------

# 三十二、航路名称

默认新建名称：

```text
航路 1
航路 2
航路 3
...
```

允许修改名称。

Route ID 使用：

```ts
crypto.randomUUID()
```

如果当前目标浏览器兼容性不允许，则采用项目现有 UUID 方案。

不要用数组索引作为 routeId。

------

# 三十三、性能要求

当前路线数量预计：

```text
1 ~ 20 条
```

每条：

```text
2 ~ 数百点
```

这种规模必须直接使用：

```text
VectorLayer
```

不要：

```text
把用户航路发布到 GeoServer
把航路做成 WMS
建立瓦片
创建大量独立 Layer
每次 zoom 全量重新解析 localStorage
```

正常 zoom/pan：

```text
0 次 API 请求
0 次 GeoServer 请求
```

这是重要验收项。

------

# 三十四、未来大数据兼容

本阶段不需要针对数万点路线复杂优化。

但 `mapRoute.ts` 保持纯函数，使未来可以增加：

```text
simplify
Douglas-Peucker
轨迹抽稀
Web Worker
```

本次不要过度设计。

------

# 三十五、跨 180° 经线

Polar-GIS 属于极地项目，因此测试一条跨国际日期变更线的路线：

```text
179°E
→
179°W
```

至少确保：

```text
不会交换 lon/lat
不会产生 NaN
不会导致地图异常
不会导致投影切换崩溃
```

如果 EPSG:3857 下出现全球长连线，需要使用 OpenLayers 合适的 wrap/连续经度处理方式解决。

不能通过把业务坐标永久修改为错误值绕过问题。

EPSG:3413 下也要验证。

------

# 三十六、地图截图兼容

现有地图截图功能会组合 OpenLayers layer canvas。

新增航路 VectorLayer 后：

验证：

```text
截图中能够显示当前可见航路
```

不能因为航路使用 DOM Overlay 导致截图缺失。

这也是坚持使用 VectorLayer 的原因之一。

------

# 三十七、用户提示

航路面板明确显示：

```text
航路规划模拟
```

以及：

```text
当前航路仅用于功能模拟，不作为实际导航依据。
```

保持项目现有“非认证航海显示”的定位。

不要将功能描述成：

```text
真实安全航行路径
最优航线
导航推荐
```

当前只是：

```text
绘制与编辑模拟
```

------

# 三十八、单元测试

新增：

```text
frontend/src/utils/mapRoute.test.ts
```

至少测试：

### 1. 经纬度校验

```text
0,0       合法
180,90    合法
-180,-90  合法
181,0     非法
0,91      非法
NaN       非法
```

### 2. 坐标文本解析

输入：

```text
120,72
122,73
125,74
```

得到 3 个 RoutePoint。

### 3. LineString 构建

EPSG:3857：

```text
输入 N 点
输出 geometry N 点
```

EPSG:3413：

```text
输入 N 点
输出 geometry N 点
```

### 4. 顺序验证

输入：

```text
[lon,lat]
```

不得错误解释：

```text
[lat,lon]
```

### 5. 投影 round-trip

```text
4326
→ currentCrs
→ 4326
```

允许浮点误差，但经纬度应基本一致。

### 6. 多航路

创建：

```text
3 条路线
```

同步到 source 后：

```text
3 个 LineString Feature
```

### 7. 单路线隐藏

隐藏 Route B：

```text
A/C 保持显示
B 不显示
```

------

# 三十九、Store 测试

如果当前项目测试结构适合，增加：

```text
frontend/src/stores/routes.test.ts
```

验证：

```text
创建 Route
删除 Route
修改 RoutePoint
增加点
删除点
切换 visible
activeRoute
localStorage 恢复
不同 projectId 数据隔离
```

------

# 四十、手工验收场景

实现完成后必须人工验证以下场景。

## 场景 1：经纬度创建航路

输入：

```text
120.000000,72.000000
125.000000,73.000000
130.000000,74.000000
```

地图出现航线。

------

## 场景 2：自由绘制

点击：

```text
地图绘制
```

在地图连续点击 5 个点。

双击结束。

列表出现新航路。

坐标表自动生成对应经纬度。

------

## 场景 3：表格修改

修改第 2 点：

```text
125
→
127
```

地图线路立即移动。

------

## 场景 4：拖拽修改

进入：

```text
拖拽编辑
```

拖动第 3 个航路点。

松开后：

```text
经纬度表立即变化
```

刷新页面：

```text
修改仍存在
```

------

## 场景 5：多航路

创建：

```text
航路 A
航路 B
航路 C
```

三条同时显示。

关闭 B：

```text
A/C 保持显示
B 消失
```

------

## 场景 6：地图缩放

连续：

```text
放大 5 次
缩小 5 次
```

要求：

```text
航路跟随地图正确缩放
位置不漂移
无闪烁
无重复 Feature
无 API 请求
无 GeoServer 请求
```

------

## 场景 7：地图拖动

大范围拖动地图。

要求：

```text
航线与地图地理位置保持一致
```

不能出现：

```text
航路浮在屏幕固定位置
```

------

## 场景 8：投影切换

连续执行：

```text
EPSG:3857
→ EPSG:3413
→ EPSG:3857
→ EPSG:3413
```

至少 3 个循环。

所有航路：

```text
位置正确
数量不增加
没有残留旧投影 Feature
没有坐标累积误差
```

------

## 场景 9：与测量功能兼容

航路编辑结束后使用：

```text
距离测量
面积测量
```

应正常。

在航路绘制过程中切测量功能时：

必须正确结束或取消航路 Draw interaction。

不能两个 Draw interaction 同时工作。

------

## 场景 10：AIS

开启 AIS。

要求同时存在：

```text
S-57
航路
AIS
```

全部正常显示。

------

## 场景 11：海图批量加载

创建航路后执行：

```text
批量加载核心图层
批量加载推荐图层
批量卸载海图
```

航路不得被清除。

------

## 场景 12：智能/标准模式

切换：

```text
smart
standard
smart
```

航路不得发生变化。

Route Layer 不加入：

```text
Render Bundle
Tile Merge
GWC Scheduler
```

------

# 四十一、必须执行的自动验证

完成开发后运行：

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

要求：

```text
TypeScript 无错误
所有已有测试继续通过
新增测试通过
Vite build 成功
```

不要为了通过测试删除或修改现有测试的有效断言。

------

# 四十二、禁止事项

本任务禁止：

```text
删除现有功能
重写 MapWorkspaceView.vue
修改 GeoServer 服务逻辑
修改 GWC
修改 S-57 导入
修改 WMS Bundle
修改 Tile Request Queue
修改瓦片缓存
新增新的地图框架
引入 Leaflet
引入 Mapbox
把航路发布成 WMS
增加数据库表
修改 FastAPI 接口
使用屏幕绝对坐标绘制航路
使用 CSS transform 模拟地图缩放
把 3857/3413 坐标保存为真实航路坐标
把 lon/lat 顺序写反
```

除非实际代码表明某个小范围修改确实不可避免，否则不要触碰与航路无关的模块。

------

# 四十三、代码质量要求

遵循现有：

```text
Vue 3 Composition API
<script setup lang="ts">
Pinia Setup Store
Element Plus
OpenLayers
TypeScript strict 类型
```

避免：

```ts
any
```

除非 OpenLayers 类型确实无法避免，并且要控制在最小范围。

函数应尽量短小。

坐标转换必须放纯函数。

交互生命周期必须可清理。

避免全局事件泄漏。

------

# 四十四、生命周期清理

在：

```text
onBeforeUnmount
```

确保清理：

```text
route Draw interaction
route Modify interaction
route Select interaction
route Snap interaction（如果使用）
相关 map event listener
route feature source（必要时）
```

不要清除 localStorage 草稿。

切换页面回来后应该重新恢复。

------

# 四十五、文档更新

功能验证完成以后更新：

```text
docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
```

09 中增加：

```text
前端航路规划模拟模块
Route Store
VectorLayer
Draw/Modify
localStorage
投影处理
```

10 中记录：

```text
任务目标
修改文件
技术决策
测试结果
```

11 中总结：

```text
新增经纬度绘制
自由绘制
拖拽编辑
多航线
缩放适配
投影切换
```

12 用户手册增加：

```text
航路规划模拟
创建航路
输入坐标
自由绘制
编辑航路
隐藏/显示
删除
投影切换
注意事项
```

保留：

```text
非认证航海显示
不作为真实导航依据
```

------

# 四十六、预留未来 Route API

虽然这次不实现后端，但代码结构必须方便未来将：

```text
localStorage
```

替换为：

```text
GET    /api/v1/projects/{projectId}/routes
POST   /api/v1/projects/{projectId}/routes
PUT    /api/v1/routes/{routeId}
DELETE /api/v1/routes/{routeId}
```

因此：

不要让 OpenLayers Feature 成为业务数据唯一来源。

正确数据流必须是：

```text
Route Store
      ↓
OpenLayers Feature
```

而不是：

```text
OpenLayers Feature
      ↓
业务真值
```

地图只是渲染结果。

Route Store 的：

```text
RoutePoint[]
```

才是当前前端阶段的数据事实来源。

------

# 四十七、最终应达到的系统效果

最终地图工作台应形成：

```text
                    MapWorkspace
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
   S-57/WMS          用户航路            AIS
       │                 │                  │
TileWMS/GWC        VectorLayer         VectorLayer
                         │
              ┌──────────┴──────────┐
              │                     │
          LineString             Modify
              │                     │
      Route Store WGS84 ←── toLonLat()
              │
         localStorage
```

其中：

```text
S-57 海图加载链路完全不变
AIS 完全不变
测量功能完全不变
航路作为新增独立 Vector Overlay
```

------

# 四十八、完成后输出开发报告

不要只回复“已完成”。

完成代码后输出：

## 1. 修改文件

例如：

```text
新增：
frontend/src/components/RoutePlannerPanel.vue
frontend/src/stores/routes.ts
frontend/src/utils/mapRoute.ts
frontend/src/utils/mapRoute.test.ts

修改：
frontend/src/types/index.ts
frontend/src/views/MapWorkspaceView.vue
frontend/src/styles.css
...
```

## 2. 功能完成情况

逐项说明：

```text
经纬度绘制
自由绘制
拖拽编辑
坐标修改
多航路显示
单路线显隐
地图缩放
地图平移
投影切换
本地保存
```

## 3. 技术实现

重点说明：

```text
Route Store
LineString
VectorLayer
Draw
Modify
Select
fromLonLat
toLonLat
projection reload
```

## 4. 对原系统影响

明确说明：

```text
是否修改后端
是否修改 S-57
是否修改 WMS/GWC
是否修改数据库
是否修改现有 API
```

正常情况下本任务全部应为：

```text
否
```

## 5. 测试结果

给出真实执行结果：

```text
npm run typecheck
npm test
npm run build
```

不能编造测试结果。

如果某项失败，必须给出：

```text
失败命令
错误信息
涉及文件
原因
已完成修复 / 未解决原因
```

------

# 最终原则

本任务最重要的设计原则是：

**航路数据使用 WGS84 `[lon, lat]` 作为唯一业务坐标，OpenLayers VectorLayer 只负责展示；Draw/Modify 负责交互；任何地图投影均从 WGS84 重新构建几何。**

以及：

**新增航路功能必须与现有 S-57/WMS/GWC/Bundle/Tile Cache 渲染体系完全解耦。**

不要为了新增航路功能破坏现有已经稳定运行的海图加载与性能优化链路。