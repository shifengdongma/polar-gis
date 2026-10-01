# Polar-GIS 海冰冰情图层完整嵌入开发任务

你现在需要在现有 `polar-gis` 项目中新增“冰情信息展示”功能。

主项目：

```
shifengdongma/polar-gis
```

参考实现项目：

```
shifengdongma/polar-gis-ice-viewer
```

请首先完整阅读两个仓库的现有代码，不要根据本 Prompt 猜测当前文件内容。

当前 `polar-gis` 开发分支为：

```
master
```

开始开发前必须执行：

```
git status
git branch --show-current
git log -5 --oneline
```

确认工作区状态、当前 HEAD 和现有未提交修改。

当前 GitHub master 最新开发中已经包含航路绘制、航路点选、坐标悬停、测量、S-57 大批量图层加载、smart/standard/overview 模式、Render Bundle、TileWMS 合并、GeoWebCache、Tile Cache、TileRequestQueue 等功能。

本任务必须遵循：

```
新增冰情能力
≠
重新设计地图工作台
≠
重新设计 S-57 图层系统
≠
把 polar-gis-ice-viewer 整个应用复制进主系统
```

最终目标是：

```
现有 Polar-GIS 地图
    │
    ├── 现有底图 XYZ / WMTS
    ├── 现有 S-57 TileWMS / GWC
    ├── 新增 海冰浓度 TileLayer
    ├── 新增 海冰厚度 TileLayer
    ├── 现有航路 VectorLayer
    ├── 现有测量 VectorLayer
    └── 现有 AIS VectorLayer

冰情数据：
NetCDF
   ↓
FastAPI Ice Service
   ↓
XYZ PNG Tiles
   ↓
OpenLayers TileLayer
   ↓
EPSG:3413 / EPSG:3857
```

# 一、首先进行源码审计，不要直接开始修改

重点阅读 Polar-GIS：

```
frontend/src/views/MapWorkspaceView.vue
frontend/src/styles.css
frontend/src/api/client.ts
frontend/src/api/projects.ts
frontend/src/types/index.ts

frontend/src/utils/mapLayerBatch.ts
frontend/src/utils/mapRenderScheduler.ts
frontend/src/utils/mapRenderBundles.ts
frontend/src/utils/mapTileMerger.ts
frontend/src/utils/tileCache.ts
frontend/src/utils/tileRequestQueue.ts

backend/app/main.py
backend/app/core/config.py
backend/app/api/
backend/app/services/
backend/pyproject.toml
backend/Dockerfile

deploy/compose.yml
deploy/nginx/default.conf

docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
```

重点阅读参考仓库：

```
polar-gis-ice-viewer/
├── backend/
│   ├── app/
│   │   ├── ice_service.py
│   │   ├── main.py
│   │   └── basemap.py
│   └── requirements.txt
│
└── frontend/
    ├── src/App.vue
    ├── src/styles.css
    └── package.json
```

必须先回答并记录：

```
1. Polar-GIS 当前 Map 在哪里创建？
2. 当前 EPSG:3413 如何注册？
3. switchProjection() 当前执行哪些生命周期操作？
4. S-57 RuntimeLayer / Bundle / GWC 生命周期在哪里？
5. measureLayer / routeLayer / aisLayer 的 zIndex 分别是多少？
6. 当前 pointermove 有哪些消费者？
7. 当前截图、打印如何获取 OpenLayers canvas？
8. 当前左侧图层面板的环境叠加入口在哪里？
9. polar-gis-ice-viewer 如何读取 NetCDF？
10. 如何生成 concentration/thickness PNG tile？
11. 如何处理 EPSG:3411 → 3413 / 3857？
12. 时间轴数据来自哪里？
13. hover 查询为什么直接查原始 NetCDF，而不是读取瓦片颜色？
```

先完成审计，再实施。

# 二、总体集成原则

必须采用“独立环境叠加模块”的方式接入。

冰情图层绝对不能进入以下现有 S-57 状态：

```
runtimeLayers
runtimeDatasets
selectedLayerIds
attachedLayerIds
activeLayerIds
warmingLayerIds
suspendedLayerIds
manuallyForcedLayerIds
loadedLayerIds
failedLayerIds
```

也不能进入：

```
Render Bundle
mapRenderScheduler
mapTileMerger
TileWMS Merger
GeoWebCache S-57 Bundle
S57 resolve API
S57 Layer Catalog
S57 Importer
S57 Batch Import
```

原因：

冰情是时间序列栅格环境数据，不是 S-57 逻辑海图对象。

正确结构：

```
S-57
→ 原有 TileWMS / GWC / Bundle

Ice
→ 独立 XYZ TileLayer

Route / Measure / AIS
→ 原有 VectorLayer
```

不要为了冰情功能修改现有 S-57 性能体系。

# 三、不要移植参考项目中的临时底图

`polar-gis-ice-viewer` 使用：

```
base_map.gpkg
```

海岸线作为独立验证项目的临时底图。

Polar-GIS 已经存在：

```
XYZ
WMTS
S-57
GeoServer
GWC
```

因此：

```
backend/app/basemap.py
/api/basemap/coastline
临时 GeoPackage 海岸线
独立 baseLayer
```

全部不要迁移。

冰情图层必须直接叠加到当前 `MapWorkspaceView.vue` 所使用的那个 OpenLayers Map。

严禁：

```
new Map(...)
```

创建第二套地图。

也严禁为了冰情重新创建 Polar-GIS 整个地图实例。

# 四、后端 Ice Service

建议新增：

```
backend/app/services/ice.py
```

以参考项目：

```
polar-gis-ice-viewer/backend/app/ice_service.py
```

为基础迁移。

保留以下核心能力：

```
IceService

dates

_inspect()

info()

tile()

value_at()

alignment_geojson()

_render()

_png()
```

但必须重构为符合 Polar-GIS 当前代码规范的正式 Service。

# 五、冰情数据目录禁止硬编码 Windows 路径

参考项目当前类似：

```
F:\workspace\sample-data
```

这种写法不能进入 Polar-GIS。

在：

```
backend/app/core/config.py
```

增加配置，例如：

```
ice_enabled: bool = True
ice_data_root: Path = Path("/data/ice")
ice_tile_cache_entries: int = 256
ice_tile_max_zoom: int = 10
```

名称可根据现有 Settings 风格调整。

必须支持 `.env`：

```
ICE_ENABLED=true
ICE_DATA_ROOT=/data/ice
ICE_TILE_CACHE_ENTRIES=256
ICE_TILE_MAX_ZOOM=10
```

开发环境可以自行覆盖：

```
ICE_DATA_ROOT=F:\workspace\sample-data
```

但是代码中不能出现本机绝对路径。

# 六、NetCDF 文件识别

沿用参考项目日期识别方式。

支持：

```
xxx_20220101.nc
xxx_20220102.nc
xxx_20220105.nc
```

通过文件名末尾：

```
(\d{8})\.nc$
```

获取实际存在日期。

时间轴必须：

```
只展示实际存在的 NetCDF 文件日期
```

禁止自动补：

```
20220103
20220104
```

如果服务器目录：

```
20220101.nc
20220103.nc
20220108.nc
```

时间轴只能有三个位置。

# 七、支持冰情字段

保留参考项目字段别名：

```
FIELD_ALIASES = {
    "concentration": (
        "sic_merged",
        "sea_ice_area_fraction",
        "ice_concentration",
        "sic",
    ),
    "thickness": (
        "sea_ice_thickness",
        "ice_thickness",
        "sit",
        "thickness",
    ),
}
```

不要假设每个 NetCDF 都同时包含两个变量。

`/info` 必须扫描所有日期并生成：

```
concentration.availableDates
thickness.availableDates
```

当前参考样例实际上只有浓度数据，没有厚度变量。

因此：

```
有浓度、无厚度
```

必须是完全正常的系统状态。

界面应该显示：

```
海冰厚度
当前日期无厚度变量
```

并禁用开关。

禁止为了演示效果生成假的厚度数据。

# 八、浓度数据规则

参考项目的 `sic_merged` 使用：

```
0 ~ 100
```

表示百分比。

必须保留以下语义：

```
0        = 有效值，0% 海冰
1~100    = 有效浓度
127      = NoData
NaN      = NoData
<0       = NoData
>100     = NoData
```

注意：

0% 是有效原始值。

渲染时允许 0% 完全透明，因为没有海冰覆盖；

但是 hover 查询到 0 时仍应该返回：

```
海冰浓度：0%
```

不能把 0 当成 NoData。

# 九、海冰厚度单位

统一转为：

```
m
```

如果 NetCDF 单位为：

```
cm
```

除以 100。

如果单位为：

```
mm
```

除以 1000。

不要对未知单位自行猜测。

# 十、坐标与投影是本任务重点

参考冰情数据源使用：

```
EPSG:3411
```

Polar-GIS 地图支持：

```
EPSG:3413
EPSG:3857
```

必须保持正确转换链：

```
NetCDF Grid EPSG:3411
        ↓
      WGS84
        ↓
EPSG:3413 / EPSG:3857
```

禁止：

```
直接把 EPSG:3411 米坐标当成 EPSG:3413
```

因为二者并非同一个 CRS。

瓦片渲染应沿用参考实现思想：

```
目标瓦片像素
    ↓
当前地图 CRS
    ↓
经纬度 WGS84
    ↓
NetCDF EPSG:3411
    ↓
查找对应网格
    ↓
得到原始 concentration / thickness
    ↓
颜色映射
```

EPSG:3857 必须限制：

```
±85.05112878°
```

以上区域透明，不要错误拉伸北极点。

# 十一、颜色样式

迁移参考项目 `PALETTES`。

## 海冰浓度

范围：

```
0%
10%
20%
30%
40%
50%
60%
70%
80%
90%
100%
```

使用参考项目现有青蓝 → 深蓝 → 黄 → 橙 → 红渐变。

要求：

```
控制点每 10%
区间内部连续插值
不是 10 个生硬色块
```

0% alpha 为 0。

NoData alpha 为 0。

## 海冰厚度

继续使用参考项目暖色方案：

```
0
0.5
1.5
3
5+
```

如果没有 thickness：

```
图例可显示
但必须明确“当前数据不可用”
开关 disabled
```

# 十二、后端 API

新增：

```
backend/app/api/ice.py
```

使用：

```
APIRouter(prefix="/ice", tags=["ice"])
```

然后在：

```
backend/app/main.py
```

注册：

```
app.include_router(ice.router, prefix=api)
```

最终 API 必须位于：

```
/api/v1/ice
```

而不是参考项目原来的：

```
/api/ice
```

建议接口：

```
GET /api/v1/ice/info

GET /api/v1/ice/value
    ?date=YYYYMMDD
    &x=...
    &y=...
    &projection=EPSG:3413

GET /api/v1/ice/alignment
    ?date=YYYYMMDD
    &projection=EPSG:3413

GET /api/v1/ice/{field}/{projection}/tile/{z}/{x}/{y}.png
    ?date=YYYYMMDD
```

如果经过 Nginx 审计认为 `.png` API 路径存在 location 冲突，也可以采用：

```
/api/v1/ice/{field}/{projection}/tile/{z}/{x}/{y}
```

Response 仍：

```
Content-Type: image/png
```

两种方案任选一种，但必须验证开发和 Docker/Nginx 生产路径均能访问。

# 十三、Nginx 必须专项检查

当前 Polar-GIS Nginx 同时存在：

```
location /api/
```

以及：

```
location ~* \.(png|jpg|jpeg|gif|ico|webp)$
```

如果冰情 API URL 以：

```
.png
```

结束，必须验证正则 location 不会把 API tile 当作前端静态 PNG。

推荐将 API 改为：

```
location ^~ /api/ {
    ...
}
```

从而确保：

```
/api/v1/ice/...png
```

始终进入 backend。

修改后必须回归：

```
登录
refresh token
项目 API
S-57 API
demo API
ice API
```

全部正常。

不要新增第二个 Nginx 服务。

# 十四、Python 依赖

根据 `ice_service.py` 实际使用情况，在：

```
backend/pyproject.toml
```

增加必要依赖：

```
netCDF4
numpy
Pillow
pyproj
```

版本范围参考 `polar-gis-ice-viewer/backend/requirements.txt`。

不要机械加入没有实际使用的库。

如果不迁移临时 GeoPackage basemap，则不要仅因为参考项目存在而加入：

```
shapely
```

除非新实现确实使用。

修改后必须验证 Docker `python:3.12-slim` 可以成功构建这些依赖。

# 十五、Docker 数据挂载

建议主仓库增加：

```
data/ice/
```

只保留：

```
.gitkeep
README.md
```

不要把大型 NetCDF 样例直接提交 Git。

`deploy/compose.yml` 的 backend 增加只读挂载：

```
- ../data/ice:/data/ice:ro
```

backend environment：

```
ICE_DATA_ROOT: /data/ice
```

Worker 当前不处理冰情，因此原则上不需要访问冰情数据。

不要因为冰情增加新的：

```
database
worker
Redis
GeoServer
```

服务。

# 十六、前端不要增加第二套 Vue 应用

不要把：

```
polar-gis-ice-viewer/frontend/src/App.vue
```

整个复制进入主项目。

应该拆成正式模块。

建议新增：

```
frontend/src/
├── api/
│   └── ice.ts
│
├── components/
│   ├── IceLayerPanel.vue
│   ├── IceTimeline.vue
│   └── IceValueTooltip.vue
│
├── composables/
│   └── useIceOverlay.ts
│
├── types/
│   └── ice.ts
│
└── utils/
    └── mapIce.ts
```

如果当前项目的 types 统一放：

```
frontend/src/types/index.ts
```

则遵循现有规范，不强制新建目录。

核心原则：

```
MapWorkspaceView
负责集成

useIceOverlay
负责状态和 OpenLayers 生命周期

mapIce
负责纯地图/投影工具

IceLayerPanel
负责图层控制 UI

IceTimeline
负责时间选择

IceValueTooltip
负责鼠标查询展示
```

不要继续把全部冰情业务逻辑直接堆进已经很大的：

```
MapWorkspaceView.vue
```

# 十七、前端不应增加新第三方依赖

Polar-GIS 和参考项目目前都已经使用：

```
Vue 3
TypeScript
OpenLayers 10.6
proj4
```

因此正常情况下：

```
frontend/package.json
```

不需要新增冰情相关 npm 包。

不要引入：

```
Leaflet
Mapbox
Cesium
另一个状态管理库
```

# 十八、Ice Type 定义

建立类似：

```
export type IceFieldId = 'concentration' | 'thickness'

export interface IceFieldInfo {
  id: IceFieldId
  label: string
  name: string
  units: string
  availableDates: string[]
}

export interface IceInfo {
  dates: string[]
  fields: IceFieldInfo[]
  defaultDate: string | null
  sourceCrs: string
  extent: [number, number, number, number] | null
}

export interface IceValue {
  date: string
  field: IceFieldId
  value: number
  units: string
  longitude: number
  latitude: number
  sourceX?: number
  sourceY?: number
}
```

字段命名必须最终服从当前 Polar-GIS API 序列化规范。

不要同时维护两套 snake_case/camelCase 真值。

# 十九、mapIce.ts

至少抽出以下纯函数：

```
createIceTileGrid(crs)

buildIceTileUrl(
    field,
    crs,
    date
)

iceFieldAvailable(
    info,
    field,
    date
)

formatIceDate()

projectIceExtent()

isIceValueValid()

iceTimelineIndex()
```

对于 EPSG:3413：

```
extent:
[-4194304, -4194304, 4194304, 4194304]

tileSize:
256

maxZoom:
10
```

EPSG:3857 使用标准 Web Mercator extent。

不要使用 CSS 或屏幕像素模拟地图投影。

# 二十、useIceOverlay.ts

这是前端核心模块。

需要管理：

```
info
loading
error

selectedDate

concentrationVisible
concentrationOpacity

thicknessVisible
thicknessOpacity

hover

debugAlignment

concentrationLayer
thicknessLayer
alignmentLayer
```

建议接口：

```
const ice = useIceOverlay({
  getMap: () => map,
  getCrs: () => currentCrs.value,
  canQueryValue: () => ...
})
```

暴露：

```
loadInfo()

attach()

dispose()

setDate()

stepDate()

toggleConcentration()

toggleThickness()

setConcentrationOpacity()

setThicknessOpacity()

refreshLayers()

reloadForProjection()

fitIceExtent()

clearHover()

handlePointerMove()

loadAlignment()
```

要求：

```
attach() 多次调用不得重复创建图层
dispose() 必须彻底卸载监听和图层
```

# 二十一、Ice Layer 应使用独立 TileLayer

类似：

```
const concentrationLayer = new TileLayer({
    source: new XYZ(...),
    opacity: concentrationOpacity,
    visible: concentrationVisible,
})
```

以及：

```
const thicknessLayer = new TileLayer(...)
```

不要：

```
TileWMS
GeoServer
VectorLayer
Canvas 手绘
DOM overlay 绘制冰区
```

冰情是服务端生成的 PNG 栅格 XYZ。

# 二十二、图层 zIndex

先读取当前：

```
S-57
routeLayer
measureLayer
aisLayer
```

的实际 zIndex。

然后设置：

```
S-57 海图
   ↓
Ice concentration
Ice thickness
   ↓
Route
Measure
AIS
```

也就是说冰情应该盖在海图上方，但是：

```
航路
测量结果
AIS
```

必须继续清晰可见。

不要为了冰情修改已有航路/测量/AIS zIndex。

# 二十三、投影切换

当前 Polar-GIS 已经存在：

```
switchProjection(crs)
```

并包含：

```
清理旧 WMS
清 Bundle
清 Tile Cache
切 currentCrs
setView
加载底图
reloadAisGeometry
reloadRouteGeometry
syncMeasureForProjection
重新挂 S-57
reconcileRenderPlan
```

不要复制参考项目：

```
map.setTarget(undefined)
map = null
setupMap(...)
```

这种“重建整个地图”的方案。

正确做法：

在现有：

```
switchProjection(crs)
```

生命周期中增加一个独立步骤，例如：

```
iceOverlay.reloadForProjection(crs)
```

功能：

```
保留 selectedDate
保留浓度 visible
保留厚度 visible
保留 opacity

只替换：
XYZ Source
TileGrid
projection

重新加载：
alignment debug layer
hover coordinate state
```

不能影响：

```
S-57
Route
Measure
AIS
```

# 二十四、日期切换

用户改变日期：

```
20220101
→
20220105
```

不要删除并重新创建 TileLayer。

只应替换：

```
XYZ Source
```

即：

```
concentrationLayer
  └── setSource(new XYZ(...date=20220105))

thicknessLayer
  └── setSource(...)
```

旧 Source 需要允许 GC / dispose，避免长时间拖动时间轴后内存累积。

URL 中必须包含日期，因此浏览器不会错误复用其他日期瓦片。

# 二十五、左侧图层面板集成

当前 Polar-GIS 左侧面板已有：

```
底图
数据集
海图图层
环境叠加
```

现有环境叠加中已有：

```
AIS 船位
```

在这个体系中增加：

```
冰情信息
```

不要创建新的一级应用页面。

建议 UI：

```
环境叠加

AIS 船位

冰情信息
  ├── 海冰浓度   [开关]
  │      透明度  [slider]
  │
  ├── 海冰厚度   [开关]
  │      透明度  [slider]
  │
  ├── 当前日期
  │      2022-01-01
  │
  └── 图例
```

可以增加：

```
[冰情]
```

按钮打开/折叠 `IceLayerPanel`。

要求与当前 Polar-GIS 视觉语言一致：

```
Element Plus
现有 glass panel
现有间距
现有字体
现有开关样式
```

不要原样复制参考仓库整套页面 CSS。

所有新增 class 建议统一：

```
ice-
```

前缀，避免污染现有样式。

# 二十六、图例

IceLayerPanel 中显示：

```
海冰浓度（%）

0 10 20 30 40 50 60 70 80 90 100
```

颜色必须与 backend `PALETTES` 保持一致。

不要前后端分别写两套不一致的配色。

可以：

```
backend palette = 真正渲染规则
frontend CSS gradient = 对同一色值的视觉表达
```

测试至少检查关键色值没有漂移。

厚度：

```
0
0.5
1.5
3
5+
```

如果当前日期不存在 thickness：

```
当前日期无厚度变量
```

并禁用。

# 二十七、时间轴

当：

```
浓度显示
或
厚度显示
```

并且：

```
info.dates.length > 0
```

时，在地图底部显示：

```
IceTimeline
```

参考实现：

```
ICE DATA TIMELINE

2022-01-01

[‹] ─────●──────── [›]

1 / 20 个可用日期

当前文件：xxx_20220101.nc
```

但主系统 API 如果没有暴露真实文件名，就只显示：

```
20220101
```

不要构造不存在的文件名。

时间轴必须使用：

```
info.dates
```

数组索引。

禁止按：

```
date + 1 day
```

计算。

# 二十八、时间轴布局不能破坏完整地图大屏

当前系统：

```
左侧图层面板可折叠
右侧航路面板可折叠
```

IceTimeline 要根据两侧状态让位。

例如：

```
left:
图层面板打开 → 约 400px
图层面板折叠 → 16~40px

right:
航路面板打开 → 约 540px
航路面板折叠 → 16~40px
```

不要固定：

```
left: 400px;
right: 540px;
```

应由 MapWorkspaceView 传递布局状态或者 CSS variable。

窗口折叠后时间轴应该自动占用更大的地图宽度。

# 二十九、鼠标悬停冰情原始值

参考项目这一点必须保留。

禁止：

```
从 PNG 像素颜色反推浓度
```

正确：

```
pointermove
    ↓
当前地图 coordinate
    ↓
/api/v1/ice/value
    ↓
当前 CRS → WGS84 → EPSG:3411
    ↓
最近 NetCDF cell
    ↓
返回 raw value
```

显示：

```
海冰浓度：65%
2022-01-01
经度 120.1234°
纬度 78.5678°
```

# 三十、hover 性能控制

禁止每个 pointermove 都立即发 HTTP。

至少实现：

```
100ms debounce
```

建议：

```
AbortController
```

取消旧请求。

并维护 request generation / request id，防止：

```
旧响应覆盖新位置
```

以下情况立即停止查询：

```
鼠标拖图
浓度图层关闭
没有 selectedDate
当前日期没有 concentration
鼠标离开地图
进入其他地图交互
组件销毁
```

如果可以根据冰情投影 extent 判断鼠标在数据范围之外，也应直接跳过 API 请求。

# 三十一、冰情 hover 与现有地图 hover 的关系

当前 Polar-GIS 已经存在：

```
坐标悬停提示
航路信息浮窗
测量
要素识别
气象
航路绘制/编辑
```

必须明确优先级。

推荐：

```
航路浮窗 / 当前地图工具
        ↓
冰情 hover
        ↓
普通经纬度 hover
```

进入：

```
测量
要素识别
气象
航路 Draw
航路 Modify
```

时暂停冰情 value 查询。

避免一个 pointermove 同时出现：

```
坐标框
冰情框
航路框
```

三个浮窗。

不要破坏当前地图交互互斥逻辑。

# 三十二、Alignment 调试功能

参考项目：

```
/api/ice/alignment
```

可以保留。

但这是：

```
开发/空间对齐验证功能
```

不是普通用户主要功能。

建议：

```
默认关闭
```

可以放在：

```
冰情面板 → 高级 / 调试
```

或者：

```
仅 development 模式显示
```

它应该用 VectorLayer 显示少量黄色控制点。

不要默认长期显示。

# 三十三、截图兼容

当前 Polar-GIS 截图会合成 OpenLayers layer canvas。

因为冰情使用真正：

```
TileLayer
```

所以截图中应该自然包含冰情栅格。

必须验证：

```
S-57 + 冰情 + 航路
```

组合截图。

不要使用 DOM Canvas 自己画冰情，否则截图体系会失效。

IceTimeline 和 IceValueTooltip 属于 UI，不要求进入地图截图。

# 三十四、打印兼容

打印时：

```
冰情地图图层保留
```

但是：

```
IceValueTooltip
IceTimeline
IceLayerPanel
alignment debug controls
```

可以通过：

```
@media print
```

隐藏。

不要影响原有打印功能。

# 三十五、空数据与错误处理

以下都不能导致整个地图打不开：

```
ICE_DATA_ROOT 不存在
ICE_DATA_ROOT 为空
NetCDF 文件损坏
某个日期无 concentration
某个日期无 thickness
未知变量名
非法日期
非法 field
非法 projection
非法 tile z/x/y
```

`GET /ice/info` 在空目录时应该正常返回类似：

```
{
  "dates": [],
  "fields": [],
  "defaultDate": null
}
```

前端：

```
无可用冰情数据
```

S-57 地图仍然正常工作。

这是非常重要的降级原则：

```
Ice failure
≠
Map failure
```

# 三十六、缓存与性能

参考项目已有：

```
tile cache
value grid cache
```

需要保留有限缓存。

不要无限缓存所有：

```
日期 × zoom × x × y
```

建议：

```
Tile cache 约 256 entries
value grid 只保留最近 1~2 个日期
```

切日期时不用主动清整个后端 tile cache，因为 key 本身包含日期。

瓦片：

```
256 × 256 PNG RGBA
```

OpenLayers：

```
transition: 0
```

减少时间轴切换时淡入残影。

# 三十七、不要让冰情影响当前 S-57 TileRequestQueue

Polar-GIS 当前自己的：

```
TileRequestQueue
LRUTileCache
warming
bundle
smart scheduler
```

是为了管理大量 S-57 TileWMS。

冰情最多：

```
2 个 TileLayer
```

不要强行把它接入这个复杂调度器。

否则会引入：

```
日期状态
Ice XYZ
S57 WMS
Bundle
```

之间不必要的耦合。

OpenLayers 自己管理冰情 XYZ 请求即可。

# 三十八、API 鉴权

先分析现有公开地图 API 和用户地图访问边界。

冰情属于：

```
只读地图环境数据
```

不要配置成：

```
system_admin only
```

否则普通用户无法浏览冰情。

同时注意：

OpenLayers XYZ 的原生图片请求不会自动携带 Axios 中设置的：

```
Authorization: Bearer ...
```

所以绝对不能：

```
给 tile endpoint 强制 Bearer
+
仍使用普通 XYZ url
```

然后假设它能工作。

可以选择：

A：

```
与现有地图瓦片相同的只读访问边界
```

或 B：

实现自定义：

```
tileLoadFunction + fetch + Authorization
```

但不要为了简单的只读冰情功能引入不必要复杂度。

必须在浏览器真实验证。

# 三十九、当前项目已有 disclaimer 必须保留

Polar-GIS：

```
不是认证 ECDIS
```

冰情同样不能被描述为：

```
权威冰情
实时航海冰情
官方导航依据
安全航行依据
```

建议 UI：

```
冰情数据用于环境信息展示与功能验证，
数据有效性以实际导入数据来源为准，
不可替代正式航海冰情资料。
```

# 四十、后端测试

建议新增：

```
backend/tests/test_ice_service.py
backend/tests/test_ice_api.py
```

测试时不要提交大 NetCDF fixture。

在 pytest：

```
tmp_path
```

中动态生成极小 NetCDF。

至少测试：

```
1. 空目录
2. 日期识别
3. 日期排序
4. concentration alias
5. thickness alias
6. 多日期 field union
7. 0% 是有效值
8. 127 是 NoData
9. >100 是 NoData
10. NaN 是 NoData
11. thickness cm → m
12. thickness mm → m
13. EPSG:3413 tile
14. EPSG:3857 tile
15. 返回 PNG signature
16. 非法 field
17. 非法 projection
18. 非法 zoom
19. 不存在日期
20. value_at 原始值
21. alignment GeoJSON
22. cache 不导致结果改变
```

# 四十一、前端测试

建议新增：

```
frontend/src/utils/mapIce.test.ts
frontend/src/composables/useIceOverlay.test.ts
frontend/src/components/IceTimeline.test.ts
frontend/src/components/IceLayerPanel.test.ts
```

以及更新：

```
MapWorkspaceView.test.ts
```

至少验证：

```
info 加载

没有冰情数据不会破坏 Map

浓度图层创建

厚度图层创建

厚度缺失时禁用

opacity 修改

visible 修改

时间轴只使用实际日期

上一天/下一天边界

日期变化替换 XYZ source

3413 tileGrid

3857 tileGrid

投影切换保留：
selectedDate
visible
opacity

dispose 删除 layer

dispose 删除 pointermove listener

hover debounce

旧 hover 请求不会覆盖新请求

Ice 不进入 selectedLayerIds

Ice 不进入 runtimeLayers

Ice 不进入 Render Bundle

Ice 不进入 TileRequestQueue
```

# 四十二、必须专项回归现有功能

冰情功能完成后必须手工验证：

```
登录/退出

项目门户

进入地图工作台

底图切换

EPSG:3857
EPSG:3413

S-57 单图层加载

S-57 批量加载

smart 模式

standard 模式

overview 模式

Bundle

GWC

图层显隐

图层透明度

属性查询

要素识别

气象演示

AIS

距离测量

面积测量

航路显示

航路点选

航路绘制

航路拖拽修改

左右窗口折叠

地图截图

地图打印
```

重点验证组合场景：

```
S-57 + 海冰浓度

S-57 + 海冰厚度

S-57 + Ice + Route

Ice + AIS

Ice + Measure

Ice + 投影切换

Ice + 时间轴连续切换

Ice + 左面板折叠

Ice + 右航路面板展开
```

# 四十三、推荐实施顺序

严格按照下面阶段进行，不要一次性改所有文件。

## Phase 1：Ice Service

完成：

```
pyproject dependencies
config ICE_DATA_ROOT
services/ice.py
api/ice.py
main.py router
```

先用 API 验证：

```
/info
/value
/tile
/alignment
```

再继续。

## Phase 2：部署

完成：

```
data/ice
compose mount
.env
Nginx /api PNG 路由检查
```

确保 Docker 环境真实访问 tile。

## Phase 3：前端底层

完成：

```
types
api/ice.ts
mapIce.ts
useIceOverlay.ts
```

只测试：

```
NetCDF
→ API
→ XYZ
→ 当前 Map
```

先不要做复杂 UI。

## Phase 4：图层 UI

增加：

```
IceLayerPanel
浓度开关
厚度开关
透明度
图例
```

## Phase 5：时间轴

增加：

```
IceTimeline
上一日期
下一日期
range
当前日期
```

## Phase 6：Hover

实现：

```
pointermove
debounce
AbortController
raw value
tooltip
```

## Phase 7：投影与生命周期

完善：

```
3413
3857
projection reload
dispose
alignment
截图
打印
窗口折叠
```

## Phase 8：测试与文档

完成所有测试和文档。

# 四十四、必须运行真实测试

后端：

```
cd backend
pytest
```

如果项目已有标准命令，以项目实际命令为准。

前端：

```
cd frontend

npm run typecheck
npm test
npm run build
```

Docker：

```
cd deploy
docker compose build backend web
docker compose up -d
docker compose ps
```

验证：

```
backend healthy
web healthy
postgres healthy
geoserver running
```

然后真实请求：

```
GET /api/v1/ice/info
GET ice tile
```

不得编造：

```
测试通过
```

没有运行的测试必须明确：

```
未执行
```

# 四十五、性能验收

打开浏览器 DevTools。

记录：

```
Ice tile 请求数量
tile HTTP 状态
tile 平均耗时
连续切换日期时内存变化
hover 请求频率
投影切换前后图层数量
```

必须保证：

```
切 20 次日期
```

以后地图中仍然只有：

```
1 个 concentration TileLayer
1 个 thickness TileLayer
```

而不是累计：

```
20 / 40 个 TileLayer
```

连续切日期不应该出现明显永久内存增长。

# 四十六、最终建议文件变更范围

预期新增：

```
backend/app/api/ice.py
backend/app/services/ice.py
backend/tests/test_ice_service.py
backend/tests/test_ice_api.py

frontend/src/api/ice.ts
frontend/src/components/IceLayerPanel.vue
frontend/src/components/IceTimeline.vue
frontend/src/components/IceValueTooltip.vue
frontend/src/composables/useIceOverlay.ts
frontend/src/utils/mapIce.ts

frontend/src/utils/mapIce.test.ts
frontend/src/composables/useIceOverlay.test.ts
frontend/src/components/IceTimeline.test.ts
frontend/src/components/IceLayerPanel.test.ts

data/ice/README.md
data/ice/.gitkeep
```

预期修改：

```
backend/app/main.py
backend/app/core/config.py
backend/pyproject.toml

frontend/src/views/MapWorkspaceView.vue
frontend/src/styles.css
frontend/src/types/index.ts（如实际需要）

deploy/compose.yml
deploy/nginx/default.conf
.env.example（如仓库实际存在）

docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
```

不要无理由修改其他文件。

# 四十七、明确禁止事项

禁止：

```
把参考 App.vue 整个复制进去

创建第二个 OpenLayers Map

创建第二套投影切换 UI

迁移 base_map.gpkg 临时底图

让 Ice 进入 S-57 runtimeLayers

让 Ice 进入 Render Bundle

让 Ice 进入 smart scheduler

把 Ice 交给 GeoServer 才能显示

为了 Ice 改写 S-57 importer

修改现有 Route 数据结构

修改现有 Route localStorage

修改现有测量算法

生成假的 thickness 数据

生成假的缺失日期

将 EPSG:3411 当作 EPSG:3413

从 PNG 颜色反推海冰值

硬编码 F:\workspace\sample-data

未测试就宣称完成
```

# 四十八、最终目标 UI

用户进入：

```
项目 → 地图工作台
```

左侧看到：

```
图层目录

底图
海图数据集
S-57 图层

环境叠加
├── AIS 船位
└── 冰情信息
```

开启冰情后：

```
冰情信息

☑ 海冰浓度
透明度 80%

☐ 海冰厚度
当前日期无厚度变量

海冰浓度图例
0 ───── 50 ───── 100%
```

地图底部：

```
2022-01-01

[‹] ─────────●───────── [›]

3 / 24 个可用日期
```

用户拖动时间轴：

```
2022-01-01
      ↓
2022-01-05
      ↓
2022-01-08
```

地图只替换 Ice XYZ Source：

```
S-57 不重新加载
底图不重新加载
航路不重新加载
AIS 不重新加载
```

鼠标悬停冰区：

```
海冰浓度 76%
2022-01-05
经度 xxx
纬度 xxx
```

切换：

```
EPSG:3857 ↔ EPSG:3413
```

冰情自动与现有地图一起重新投影显示。

# 四十九、文档更新

完成后更新：

```
docs/09-system-architecture.md
```

新增：

```
Ice Overlay Architecture

NetCDF
→ IceService
→ PNG XYZ
→ OpenLayers Ice TileLayer
```

明确：

```
Ice Overlay
与
S57 Render Pipeline
彻底解耦
```

更新：

```
docs/10-work-log.md
```

记录：

```
修改文件
实现内容
问题
决策
测试结果
```

更新：

```
docs/11-work-summary.md
```

概述：

```
海冰浓度
海冰厚度
样式
时间轴
hover
双投影
```

更新：

```
docs/12-user-manual.md
```

增加：

```
冰情信息图层使用说明
```

并保留：

```
非认证 ECDIS
冰情不作为正式导航依据
```

# 五十、最终交付报告格式

开发完成后不要只回复“已完成”。

请按下面结构输出：

```
1. 基线
   branch
   HEAD
   git status

2. 参考项目分析
   哪些功能被迁移
   哪些功能没有迁移
   为什么

3. 后端修改
   文件
   API
   数据处理
   投影
   缓存

4. 前端修改
   Ice Layer
   Panel
   Timeline
   Hover
   Projection

5. 部署修改
   Docker
   volume
   Nginx

6. 与现有系统隔离情况
   S57
   Bundle
   GWC
   Route
   Measure
   AIS

7. 测试结果
   backend pytest
   frontend typecheck
   frontend tests
   frontend build
   docker

8. 手工验收结果

9. 未验证内容

10. 已知限制

11. git diff --stat

12. 建议提交信息
```

最后再次检查：

```
git diff
git diff --stat
git status
```

如果用户没有明确要求：

```
不要自动 commit
不要自动 push
```

本次任务的核心原则只有一句：

**把 polar-gis-ice-viewer 的“冰情数据能力”移植进 Polar-GIS，而不是把两个 WebGIS 应用强行拼在一起。**