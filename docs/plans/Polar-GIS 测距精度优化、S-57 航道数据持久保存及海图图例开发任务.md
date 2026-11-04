# Polar-GIS 测距精度优化、S-57 航道数据持久保存及海图图例开发任务

## 一、任务背景与基本要求

项目仓库：

https://github.com/shifengdongma/polar-gis

请基于最新 `master` 分支实际代码，完成以下三项功能优化：

1. 分析并优化现有测距工具，提高极地、高纬度地区的距离计算精度。
2. 在现有 S-57 航道专题查询基础上，实现航道原始数据提取、服务器持久化保存及 GeoJSON 下载，供后续航线规划算法使用。
3. 为海图图层增加直观的图例与符号说明，使用户能理解不同图层的颜色、线型、图案代表什么海图要素。

**总体要求：最小侵入、复用现有模块、直接完成可用功能、只做必要验证。**

不要为了这三个任务大规模重构系统架构、增加复杂中间件或建立完整测试平台。

不影响当前的 S-57 海图导入、批量加载、智能渲染、海冰、环境叠加、测量交互、航路绘制和智能规划功能。

开发前先检查：

```
git status
git branch --show-current
git log -5 --oneline
```

查看实际文件，保留所有未提交修改。

# 二、任务一：测距函数分析与高精度测量改造

## 2.1 首先确认现有实现

重点检查：

```
frontend/src/utils/mapMeasure.ts
frontend/src/utils/mapRoute.ts
frontend/src/utils/mapMeasure.test.ts
frontend/src/views/MapWorkspaceView.vue
```

当前测距核心已知为：

```
import { getDistance } from 'ol/sphere'
```

逐段调用：

```
getDistance(pointA, pointB)
```

对折线各段求和。

当前业务坐标为：

```
WGS84
[longitude, latitude]
```

显示投影为：

```
EPSG:3857
EPSG:3413
```

必须保留 WGS84 作为测量数据的唯一真值，不允许直接使用 EPSG:3857 或 EPSG:3413 的投影平面长度作为最终测量距离。

## 2.2 分析现有算法误差

当前：

```
ol/sphere.getDistance()
```

使用球面大圆距离计算。

请先给出简短分析：

- 当前实际使用的计算函数；
- 采用的地球模型；
- 是否直接使用屏幕像素距离；
- 高纬度测距误差来源；
- 多航点折线测距的计算方式；
- 当前算法与 WGS84 椭球测地线的区别。

需要明确：

```
球面大圆距离不是完全错误的测距方法，
但它属于球体近似模型。
```

误差分析应基于实际坐标和参考结果，不要假设任何位置的误差都固定。

## 2.3 引入 WGS84 椭球测地线距离

推荐采用 GeographicLib 的 WGS84 椭球测地线反算算法（Karney 方法）。

具体实现优先选择可在现有前端直接运行、依赖稳定且维护成本较低的 JavaScript 库。

开发前核对该库的真实 npm 包名、版本、许可证与 TypeScript 支持情况，不要编造 import 路径。

如果前端依赖不便使用，也可以采用已有 Python `pyproj.Geod` 提供计算实现，但应避免让地图上的每次测量更新都产生不必要的网络请求。

建议新增一个纯计算函数，例如：

```
export function geodesicDistanceWGS84(
  pointA: [number, number],
  pointB: [number, number]
): number
```

输入：

```
[lon, lat]
```

输出：

```
meters
```

建议统一：

```
export function measurePolylineLength(
  points: [number, number][]
): number
```

对每对相邻航点：

```
椭球测地线反算
       ↓
每段距离
       ↓
总距离
```

不得把整个折线的起点到终点直线距离当成折线总长度。

## 2.4 兼容原有测距

保留现有：

```
Draw
MeasureDraft
measureGeometryToDraft
buildMeasureGeometry
formatMeasureResult
formatDistance
```

等逻辑与调用关系。

如果能够在不增加复杂度的前提下实现，建议提供：

```
type DistanceMethod =
  | 'ellipsoid'
  | 'sphere'
```

默认：

```
ellipsoid
```

原来的 `ol/sphere.getDistance()` 可保留用于对比与兼容。

但如果增加模式切换会显著增加 UI 工作量，可以只在工具层保留旧算法，不必增加额外按钮。

## 2.5 测量 UI

原有测距工具的操作不变：

```
启动测距
点击起点
点击多个航点
双击结束
显示总距离
```

结果显示：

```
距离：xxx.xx km（xxx.xx NM）
计算方法：WGS84 椭球测地线
```

可选择同时显示：

```
球面近似：xxx.xx km
差值：xxx m
```

但不是必须。

保留：

```
m
km
NM
```

现有单位与格式。

不要把计算结果的小数位数描述为仪器测量精度。

## 2.6 极地特殊情况

必须正确处理：

```
高纬度坐标
接近北极点
跨 180° 经线
东西半球转换
同一点距离为 0
```

还应注意两个不同概念：

```
椭球测地线最短距离
```

与：

```
船舶实际行驶轨迹距离
```

并不相同。

当用户仅设置两个点时，结果是两点间的椭球测地线最短距离。

当用户设置多个航点时，结果是各相邻航点间测地线距离之和。

不要错误宣称这就是避障后的真实航行距离。

## 2.7 面积功能不在本次改造范围

当前：

```
sphericalRingArea()
```

用于面积计算。

本任务主要修改测距，不要求同时引入复杂的椭球多边形面积算法。

保持原有测面积功能正常，不改变其现有说明。

## 2.8 基础验证

只需要少量必要测试：

1. 使用一个正常纬度坐标对，与可靠的 WGS84 椭球计算结果比较。
2. 使用一个北极高纬度坐标对比较。
3. 使用跨 180° 经线的坐标对比较。
4. 验证多段距离等于各段距离之和。
5. 验证切换 EPSG:3857 / 3413 后测距数值不变化。

建议基于现有 `mapMeasure.test.ts` 增加测试，而不是新建大型测量测试体系。

# 三、任务二：S-57 航道信息提取与持久化保存

## 3.1 充分复用现有航道专题功能

最新仓库已存在：

```
backend/app/services/s57_waterway_catalog.py
backend/app/services/s57_waterways.py
backend/app/api/s57_waterways.py

frontend/src/api/s57Waterways.ts
frontend/src/components/S57WaterwayPanel.vue
frontend/src/composables/useS57Waterways.ts
frontend/src/types/s57Waterways.ts
frontend/src/utils/mapS57Waterway.ts
```

当前已有：

```
GET /api/v1/projects/{projectId}/s57-waterways/catalog

POST /api/v1/projects/{projectId}/s57-waterways/search

GET /api/v1/projects/{projectId}/s57-waterways/{featureId}
```

实现了：

```
航道分类
真实数据查询
航道搜索
结果分页
属性详情
地图定位
地图独立高亮
```

**这些功能不要重复开发。**

本任务重点新增：

```
航道数据批量提取
航道数据独立保存
已保存成果管理
GeoJSON 下载
```

## 3.2 航道对象类别

复用：

```
s57_waterway_catalog.py
```

中的实际分类。

重点支持：

```
FAIRWY  航道
RECTRC  推荐航路
NAVLNE  航行线
TWRTPT  双向航路段
CANALS  运河

TSSLPT
TSSBND
TSEZNE
TSSRON
```

以及现有专题目录中已定义的相关管制与辅助对象。

必须把：

```
航道本体
推荐航路
交通分隔制
航行限制
辅助信息
```

明确区分。

例如：

```
DEPARE
DEPCNT
SOUNDG
```

可用于后续水深安全判断，但不能直接视为航道中心线。

## 3.3 原始 S-57 数据提取方式

优先复用当前已经导入的：

```
PostGIS geo.*
```

数据表。

不要重新开发一套：

```
S-57 .000 → GDAL
```

导入程序。

应在：

```
resolve_waterway_layers()
```

已解析的有效图层上增加批量提取。

流程：

```
项目
  ↓
有效 S-57 数据集版本
  ↓
可查询航道图层
  ↓
按选定对象类别提取
  ↓
读取真实属性与 Geometry
  ↓
转换为 EPSG:4326
  ↓
形成 FeatureCollection
  ↓
保存 GeoJSON + 元数据
```

提取不能只下载当前搜索结果第一页。

必须按服务器端分页或流式批次读取全部符合筛选条件的记录。

对较大数据量可以限制单次最大提取条数，并在 UI 提示。

## 3.4 保存格式

优先使用：

```
GeoJSON
```

每个要素包含：

```
{
  "type": "Feature",
  "id": "stable-feature-id",
  "geometry": {
    "type": "LineString",
    "coordinates": [
      [120.0, 75.0],
      [121.0, 75.5]
    ]
  },
  "properties": {
    "objectClass": "NAVLNE",
    "objectName": "示例航行线",
    "sourceLayerId": "source-layer-id",
    "sourceDatasetId": "source-dataset-id",
    "sourceVersionId": "source-version-id",
    "originalAttributes": {}
  }
}
```

上述仅为数据结构示例，不能用示例航行线冒充实际提取结果。

原始几何可能是：

```
Point
LineString
Polygon
MultiLineString
MultiPolygon
```

必须保留真实几何类型。

不能为了方便路径规划把所有面对象强制转换为 LineString。

所有坐标统一：

```
EPSG:4326
[longitude, latitude]
```

同时保存原始属性，不能只保留中文翻译后的显示字段。

## 3.5 服务器端持久化

建议采用最简方案：

```
data/navigation/waterways/
    projectId/
        snapshotId/
            waterways.geojson
            manifest.json
```

`manifest.json` 至少包含：

```
snapshotId
projectId
createdAt
crs
featureCount
objectClasses
sourceDatasets
sourceVersionIds
sourceContentHashes（如存在）
filters
schemaVersion
```

每次保存生成独立 snapshotId。

文件写入采用临时文件加原子替换，避免中途失败留下不完整成果。

下载后得到的 GeoJSON 应能被常见 GIS 工具及 Python 脚本读取。

该保存目录需要使用持久化 Docker volume 或已有持久数据目录，不得只写入容器临时文件系统。

暂不需要建立复杂数据库关系表。若现有存储服务能管理成果文件，则优先复用现有存储能力。

## 3.6 新增接口

建议：

```
POST /api/v1/projects/{projectId}/s57-waterways/snapshots
```

根据选定类别、筛选条件与当前有效数据集版本，生成持久化成果。

```
GET /api/v1/projects/{projectId}/s57-waterways/snapshots
```

列出已保存成果。

```
GET /api/v1/projects/{projectId}/s57-waterways/snapshots/{snapshotId}/download
```

下载 GeoJSON。

如需读取快照元信息：

```
GET /api/v1/projects/{projectId}/s57-waterways/snapshots/{snapshotId}
```

注意 FastAPI 路由顺序和路径设计，避免：

```
/{featureId}
```

吞掉：

```
/snapshots
```

等固定路径。

建议在统一 router 中把固定路径定义在动态 featureId 之前，必要时采用更清晰的 `/features/{featureId}` 规范，兼容旧接口。

## 3.7 数据版本一致性

保存时必须绑定：

```
Dataset
DatasetVersion
Layer
```

真实来源。

如果后续导入新的 S-57 更新文件：

```
原有快照不自动覆盖
```

而是：

```
旧快照仍可读取
新版本可重新提取
```

用户查看旧快照时可提示：

```
该成果基于旧版海图数据
```

这对于后续规划算法结果复现非常重要。

## 3.8 前端功能

在现有：

```
S57WaterwayPanel.vue
```

新增功能入口：

```
[保存提取结果]
[已保存航道数据]
```

保存提取结果时：

```
选择航道类别
设置筛选条件
点击保存
后端完成提取
显示保存结果
```

已保存列表显示：

```
成果名称 / ID
保存时间
来源数据集
S-57 版本
要素数量
下载按钮
```

用户可以通过：

```
下载 GeoJSON
```

取得可供后续分析的数据文件。

不必开发复杂的数据预览编辑器。

## 3.9 后续路径规划数据接口预留

保存的数据应满足 Python 规划程序使用需求。

例如可以通过：

```
import json

with open("waterways.geojson", encoding="utf-8") as f:
    data = json.load(f)

features = data["features"]
```

读取真实航道要素。

此阶段只要求保存和读取，不要求立即把航道数据接入 NSGA-III 或风险模型。

不要额外开发整套航道拓扑构建算法。

也不要自动把所有航道对象拼成可航行网络。

# 四、任务三：海图图层符号与图例展示

## 4.1 先检查已有图例能力

重点检查：

```
backend/app/api/layers.py
backend/app/services/s57_styles.py
backend/app/services/s57_style_refresh.py

frontend/src/views/MapWorkspaceView.vue
frontend/src/utils/s57ObjectNames.ts
frontend/src/styles.css
```

当前已经存在：

```
GET /api/v1/layers/{layerId}/legend
```

后端利用：

```
GeoServer WMS GetLegendGraphic
```

获取图例。

前端已有：

```
图例与元数据
```

入口。

因此本次要求：

**增强现有图例展示，不重复开发图例服务。**

## 4.2 新增图层内联图例

当前左侧图层列表显示：

```
图层名称
加载状态
操作按钮
```

建议增加：

```
[图例]
```

图标或展开按钮。

点击后展示：

```
图层中文名称
S-57 对象代码
实际图例符号
颜色/线型/图案含义
简短用途说明
```

例如：

```
水深区域 DEPARE
[实际图例]
描述：表示海图中的水深区域对象

等深线 DEPCNT
[实际图例]
描述：连接相同水深值位置的线要素

航道 FAIRWY
[实际图例]
描述：表示 S-57 航道区域对象
```

对于每个对象的描述，要依据其真实对象定义与当前 SLD 样式填写。

## 4.3 优先展示实际 GeoServer 图例

已有：

```
GetLegendGraphic
```

接口，优先使用。

前端可以：

```
const response = await api.get(
  `/layers/${layerId}/legend`
)
```

再显示返回的图例 URL。

不得仅使用 emoji 或随便绘制一个图标假装是海图符号。

但需要注意 GeoServer 可能无法为某些图层返回可用图例。

对此采用简单的回退机制：

```
有 GeoServer 图例
→ 显示真实图例

无 GeoServer 图例
→ 显示当前系统 SLD 样式对应的简化符号
```

回退符号必须依据：

```
s57_styles.py
```

现有颜色和几何类型绘制。

不能宣称这些自定义简化样式是完整 IHO S-52 标准符号。

## 4.4 统一中文说明

复用：

```
s57ObjectNames.ts
```

中的 S-57 中文名称映射。

建议增加简单说明映射：

```
export const s57ObjectDescriptions: Record<string, string> = {
  COALNE: '海岸线对象，用于表示陆地与水域的边界。',
  LNDARE: '陆地区域对象。',
  DEPARE: '水深区域对象。',
  DEPCNT: '等深线对象。',
  SOUNDG: '测深点对象。',
  FAIRWY: '航道对象。',
  RECTRC: '推荐航路对象。',
  NAVLNE: '航行线对象。',
}
```

具体描述应校核 S-57 对象定义，不能误解为实时航行状态或已经验证的安全通道。

不必一次编写全部对象字典。

优先覆盖当前项目常见、实际已加载的对象类别，其余按需补充。

对于未知类别，显示原始代码，不要猜测。

## 4.5 图例 UI 设计

建议在海图左侧图层面板：

```
S-57 海图图层

☑ 海岸线 COALNE
   [图例]
   ─────
   海岸线

☑ 水深区域 DEPARE
   [图例]
   ■■■
   水深区域

☑ 航道 FAIRWY
   [图例]
   实际样式预览
   S-57 航道对象
```

同时保留现有：

```
图例与元数据
```

详情功能。

不要创建全新的独立图例页面。

## 4.6 控制图例加载量

不允许在用户进入地图工作台时：

```
一次性向 GeoServer 请求全部图层的图例
```

推荐：

```
用户展开某个图例
→ 请求该图层图例
→ 缓存结果
```

每个图层首次加载后缓存图例 URL 或结果，关闭再打开无需重复请求。

样式发生变化时才失效对应缓存。

不要影响原有：

```
TileRequestQueue
Render Bundle
GWC
S-57 批量加载
```

图例请求与海图瓦片请求应保持独立。

## 4.7 图例与实际显示的一致性

必须注意：

```
S-57 Object Class
```

不等于：

```
唯一固定的可视化符号
```

同一类别可能根据实际样式、比例尺和属性产生不同显示。

所以：

- 能从当前有效 SLD 或 GeoServer 图例获取的，展示真实图例；
- 属于样式预设的，展示该预设的实际颜色和线型；
- 无法确认的，只展示类别名称与代码，不伪造图案；
- 不改变已有 S-57 制图规则以迎合图例。

# 五、推荐实施顺序

本次只划分三个开发阶段。

## 阶段一：高精度测距

完成：

```
当前测距分析
椭球测地线计算函数
测距调用替换
结果显示说明
少量基础测试
```

不修改测面积功能和地图交互。

## 阶段二：航道数据保存

完成：

```
现有航道专题服务复用
服务器批量提取
GeoJSON + manifest 保存
下载接口
前端保存与下载按钮
```

不重新开发 S-57 导入，也不立即开发航道规划拓扑。

## 阶段三：图例展示

完成：

```
GeoServer 图例复用
图层内联展示
中文类别说明
图例请求缓存
```

不引入完整 S-52 符号引擎。

# 六、精简验证要求

**测试只针对本次修改，不要为了测试而无限扩展工作量。**

后端：

```
cd backend
pytest -q
```

前端：

```
cd frontend
npm run typecheck
npm test
npm run build
```

如果全量测试较多，可先执行相关测试，最后运行已有全量测试作为基本回归，不需要新建大规模测试体系。

只需重点验证：

**测距：** 普通两点、高纬两点、跨 180° 经线、多点折线，以及投影切换后数值一致。

**航道保存：** 选择真实航道类别、生成保存成果、下载 GeoJSON、解析文件内容、查看来源版本信息。

**图例：** 展开图例、显示真实符号和说明、图例不可用时正确降级、关闭图例不影响海图。

**现有功能：** 简单检查海图正常加载、海冰正常显示、航线正常绘制，确认本次修改没有直接破坏核心地图操作。

不要求：

```
大规模压力测试
复杂性能基准平台
全量端到端自动化框架
数百个新测试用例
额外独立微服务
复杂数据库迁移
```

# 七、预计文件修改范围

主要修改：

```
frontend/src/utils/mapMeasure.ts
frontend/src/utils/mapRoute.ts
frontend/src/utils/mapMeasure.test.ts

frontend/src/components/S57WaterwayPanel.vue
frontend/src/composables/useS57Waterways.ts
frontend/src/api/s57Waterways.ts
frontend/src/types/s57Waterways.ts

frontend/src/views/MapWorkspaceView.vue
frontend/src/utils/s57ObjectNames.ts
frontend/src/styles.css

backend/app/services/s57_waterways.py
backend/app/api/s57_waterways.py

deploy/compose.yml
```

按实际需要新增少量文件，例如：

```
backend/app/services/s57_waterway_export.py
frontend/src/components/S57LayerLegend.vue
frontend/src/utils/geodesicDistance.ts
```

不要求为了形式而新增全部文件。

尽量复用现有服务函数，避免重复代码。

# 八、文档更新与最终交付

在完成代码后，简要更新：

```
docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
```

不需要大篇幅重写文档。

最终报告只需要说明：

1. 当前使用的测距函数和旧算法的主要误差来源。
2. 新测距算法及基本精度对比结果。
3. 航道数据如何提取、保存与下载。
4. 保存的 GeoJSON 与元数据结构。
5. 海图图层图例如何显示。
6. 实际修改文件。
7. 已执行的基础验证及结果。
8. 未解决的问题。

未运行的测试必须标记为未执行，不允许编造通过结果。

**最终标准：三个功能真正可用、现有系统不受影响，并且修改保持简洁易维护。不要为了追求架构复杂度和测试数量而偏离主要开发任务。**