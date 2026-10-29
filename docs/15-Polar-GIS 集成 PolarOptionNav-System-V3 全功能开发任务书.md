# Polar-GIS 集成 PolarOptionNav-System-V3 全功能开发任务书

## 0. 任务身份与总体要求

你是一名熟悉 Python/FastAPI、Vue 3/TypeScript、OpenLayers、PostGIS、海洋环境数据处理、船舶性能建模、多目标路径规划及软件测试的高级全栈工程师和系统架构师。

现在需要将 `PolarOptionNav-System-V3` 已有的极地船舶环境感知、风险评估与多目标路径规划功能移植到 `polar-gis` 项目中。

### 项目来源

基底项目：

https://github.com/shifengdongma/polar-gis

参考功能项目：

https://github.com/shifengdongma/PolarOptionNav-System-V3

默认分支：

- Polar-GIS：`master`
- PolarOptionNav-System-V3：`main`

最终交付必须发生在 `polar-gis` 项目中，不能以独立启动 V3 项目作为移植完成的证据。

### 核心目标

在保留 Polar-GIS 当前所有功能的前提下，新增完整业务链：

**环境数据加载 → 船舶性能参数 → 航行风险评估 → 多目标航线规划 → 候选航线显示 → 航线对比 → 人工审核与修改 → 规划结果管理。**

最终用户能够从 Polar-GIS 地图工作台打开智能规划模块，而不需要切换到另一个 WebGIS 平台。

本任务要求最大限度复用 V3 已实现、已经测试的业务能力，对尚未完成的原型能力进行真实补齐。必须区分：

1. 已有可运行代码；
2. 已有算法但未接入真实数据；
3. 已有 API 但 UI 未接入；
4. 仅有 UI 占位；
5. 仅有设计文档或未来规划；
6. 真正缺失、需要开发的功能。

禁止把这六类功能混为一谈。

## 1. 开发前必须执行仓库审计

首先读取 Polar-GIS 中以下文件：

```
CLAUDE.md
README.md

backend/app/main.py
backend/app/core/config.py
backend/app/models.py
backend/app/schemas.py
backend/app/api/projects.py
backend/app/api/ice.py
backend/app/services/ice.py
backend/app/services/map_render_plan.py
backend/pyproject.toml

frontend/src/views/MapWorkspaceView.vue
frontend/src/components/RoutePlannerPanel.vue
frontend/src/components/RouteInfoFlyout.vue
frontend/src/components/IceLayerPanel.vue
frontend/src/components/IceTimeline.vue
frontend/src/composables/useRouteDrawing.ts
frontend/src/composables/useIceOverlay.ts
frontend/src/stores/routes.ts
frontend/src/utils/mapRoute.ts
frontend/src/utils/mapRenderScheduler.ts
frontend/src/utils/mapRenderBundles.ts
frontend/src/utils/tileCache.ts
frontend/src/utils/tileRequestQueue.ts

deploy/compose.yml
deploy/nginx/default.conf

docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
```

随后阅读 V3 项目：

```
README.md

backend/app/main.py
backend/app/routes.py
backend/requirements.txt

core/models.py
core/contracts/
core/environment/
core/providers/
core/vessel/

services/environment_service/
services/vessel_service/
services/planner_service/

frontend/src/App.vue
frontend/src/components/
frontend/src/map/
frontend/src/services/
frontend/src/types/

docs/V5_REUSE_AND_MIGRATION_PLAN.md
docs/engineering/
docs/product/
```

特别检查：

```
docs/product/V5_FUNCTION_GAP_MATRIX.md
docs/product/V5_EXISTING_UI_FUNCTION_AUDIT.md
docs/product/V5_NAVIGATION_FUNCTIONAL_SPEC.md
```

这些文档中包含“当前实现”和“未来产品目标”，不能将未来设计直接当成已经完成的代码。

检查两个仓库当前 HEAD、Git 状态、依赖版本和测试命令。不要覆盖未提交修改。

建议创建独立开发分支：

```
git checkout -b feature/v3-navigation-integration
```

在形成审计结论前，不允许直接批量复制 V3 文件。

### 审计交付

先生成：

```
docs/plans/v3-integration-audit.md
```

必须包含：

- 两个项目的实际技术栈；
- 两边已实现功能；
- 重叠功能清单；
- V3 可直接复用文件；
- V3 必须重构文件；
- 不应移植的文件；
- 现有环境/地图/航路状态的潜在冲突；
- 数据文件缺失及外部 API 依赖；
- 已实现与待实现功能差距矩阵；
- 最小侵入移植计划。

对于代码与文档不一致的地方，以实际运行和测试证据为准，并记录不一致原因。

## 2. 总体架构必须保持 Polar-GIS 主导

禁止把 V3 的整套 `App.vue`、路由、独立地图实例、独立 FastAPI 应用直接复制进 Polar-GIS。

最终建议架构：

```
Polar-GIS Frontend
│
├── MapWorkspaceView.vue
│   ├── 原有底图及 S-57 图层
│   ├── 原有海冰图层
│   ├── 新增水深图层
│   ├── 新增风场图层
│   ├── 新增海流图层
│   ├── 新增海浪图层
│   ├── 新增风险栅格图层
│   ├── 原有手动航路图层
│   └── 新增算法规划航路图层
│
├── EnvironmentPanel
├── VesselPanel
├── NavigationTaskPanel
├── PlanningPanel
├── RiskAnalysisPanel
├── RouteComparisonPanel
└── PlanningResultPanel
          │
          ▼
Polar-GIS FastAPI
│
├── existing APIs
├── environment APIs
├── vessel APIs
├── risk APIs
├── planner APIs
└── planning task APIs
          │
          ▼
Business Services
│
├── EnvironmentService
├── VesselService
├── RiskEvaluationService
├── PlanningGridService
├── PlannerService
└── PlanningTaskService
          │
          ▼
PostgreSQL/PostGIS
GeoServer/GWC
NetCDF / Raster Files
Planning Results
```

不得替换现有：

```
S-57 图层管理
GeoServer/GWC
Render Bundle
海图批量加载
海冰密集度
海冰时间轴
航路绘制
航路拖拽编辑
航路信息浮窗
地图测量
要素识别
用户认证
权限管理
```

新增业务模块应尽可能独立，实现显式 attach、update、dispose 生命周期。

## 3. 建议新代码组织方式

在后端现有分层架构下引入专用导航业务目录，而不是把 V3 根级别的 `core` 与 `services` 原样铺到 Polar-GIS 根目录。

建议：

```
backend/app/navigation/
├── __init__.py
├── contracts/
│   ├── coordinates.py
│   ├── directions.py
│   ├── time.py
│   ├── units.py
│   ├── quality.py
│   └── evidence.py
│
├── environment/
│   ├── interfaces.py
│   ├── models.py
│   ├── query.py
│   ├── time_manager.py
│   └── providers/
│       ├── gebco.py
│       ├── nextsim.py
│       ├── carra2.py
│       ├── topaz5.py
│       └── wam.py
│
├── vessel/
│   ├── models.py
│   ├── physical.py
│   ├── propulsion.py
│   ├── performance.py
│   └── service.py
│
├── risk/
│   ├── models.py
│   ├── evaluator.py
│   ├── grid.py
│   └── service.py
│
└── planner/
    ├── dnsga3.py
    ├── environment_adapter.py
    ├── environment_model.py
    ├── energy_model.py
    ├── speed_model.py
    ├── historical_frequency.py
    ├── northern_grid.py
    ├── land_mask.py
    ├── static_grid.py
    └── service.py
```

这只是目标组织建议，必须先检查 V3 实际 import 图、依赖闭包及 Polar-GIS 现有代码，必要时调整目录。

目标是让 V3 业务核心逐步成为 Polar-GIS 内部的可复用业务库，而不是出现两个平行的 FastAPI 应用或两个配置系统。

# 第一阶段：环境感知与数据源融合

## 4. 多源环境数据 Provider

V3 已包含以下关键 Provider 相关代码：

```
core/providers/gebco/
core/providers/nextsim/
core/providers/carra2/
core/providers/topaz5/
core/providers/wam/

services/environment_service/copernicus_ice.py
services/environment_service/current.py
services/environment_service/wave.py
services/environment_service/wind.py
services/environment_service/polar_bathymetry.py
services/environment_service/environment_query.py
services/environment_service/time_manager.py
```

需要审查并迁移实际实现。

目标：

| 环境数据 | 参考来源     | 主要业务                          |
| -------- | ------------ | --------------------------------- |
| 水深     | GEBCO        | 水深显示、吃水安全、陆地/浅水障碍 |
| 海冰     | neXtSIM-F 等 | 海冰密集度、厚度、冰区风险        |
| 风       | CARRA2       | 风速、风向、风风险                |
| 海流     | TOPAZ5       | 流速、流向、对地航速修正          |
| 海浪     | Arctic WAM   | 有效波高、周期、浪向、风险        |

不得假设所有数据都存在或均能从公共 API 直接获取。

需要分别核对：

```
实际文件格式
变量名
时间坐标
坐标系
数据分辨率
有效空间范围
单位
NoData
维度顺序
权限与下载条件
```

Provider 不应将不可用数据自动填为零。

## 5. 复用 Polar-GIS 已有海冰功能

Polar-GIS 目前已存在：

```
backend/app/services/ice.py
backend/app/api/ice.py
frontend/src/composables/useIceOverlay.ts
frontend/src/components/IceLayerPanel.vue
frontend/src/components/IceTimeline.vue
```

这是已经完成移植与性能优化的正式功能。

必须复用，而不是覆盖。

V3 的新海冰 Provider 与现有 IceService 的关系建议设计为：

```
IceService
├── 现有海冰数据展示与时间轴
└── 可选 V3 IceProvider

EnvironmentService
└── IceProviderAdapter
    ├── 查询实际原始值
    ├── 提供空间时间元数据
    └── 供风险评估与路径规划使用
```

必须确保：

- 原有海冰图层继续正常工作；
- 数据源切换有清晰状态；
- 现有时间轴不丢失；
- 不覆盖现有 PNG 瓦片 URL；
- 不重新引入已修复的瓦片并发堆积问题；
- 保留缓存、限流、过期请求中止机制；
- 不把不同海冰产品强行视为同一分辨率、同一数据时间。

## 6. 统一环境时间语义

V3 存在：

```
EnvironmentTimeManager
EnvironmentTimeline.vue
```

Polar-GIS 已有：

```
IceTimeline.vue
```

需要设计统一的环境时间上下文，而不是简单删除旧时间轴。

至少区分：

```
requested_time
matched_time
valid_time
issue_time
observation_time
ingest_time
```

对于没有某类时间元数据的数据源，保持未知状态，不要伪造。

用户在地图上切换环境时间时：

```
海冰
风
浪
流
```

分别按可用时次匹配。

每个图层都应展示真实的匹配时间和数据质量。

规划服务应使用明确的环境快照时间，防止地图显示时间与后台规划使用时间不一致。

## 7. 新增环境图层

在 Polar-GIS 现有 OpenLayers Map 中新增：

```
BathymetryLayer
WindLayer
CurrentLayer
WaveLayer
```

参考 V3：

```
frontend/src/map/layers/
frontend/src/services/
```

要求：

水深：

- 支持分级水深栅格/色带；
- 支持图层显隐、透明度、图例；
- 与现有 S-57 水深图层并存；
- 不得把 GEBCO 栅格直接并入 S-57 TileWMS Bundle。

风场：

- 支持风向箭头；
- 支持风速数值和颜色；
- 支持随地图缩放调整采样密度；
- 控制最大矢量数量；
- 支持点击或悬停查询。

海流：

- 支持流向、流速；
- 明确方向为流向 TO 还是来向 FROM；
- 能在后续航速模型中使用。

海浪：

- 支持有效波高；
- 支持波浪方向；
- 支持周期显示；
- 支持按实际时次切换。

所有环境图层必须：

```
独立显隐
独立加载状态
独立错误状态
独立数据来源说明
可正确卸载
支持 EPSG:3413/3857
```

不能影响原有海图瓦片加载。

## 8. 环境数据查询服务

参考 V3：

```
EnvironmentQueryService
EnvironmentGrid
EnvironmentSnapshot
```

新增统一查询能力。

推荐 API：

```
GET /api/v1/navigation/environment/sources
POST /api/v1/navigation/environment/query
POST /api/v1/navigation/environment/batch-query
GET /api/v1/navigation/environment/times
```

实际设计可以根据业务调整。

查询输入包括：

```
{
  "longitude": 125.0,
  "latitude": 78.0,
  "time": "2025-02-15T12:00:00Z",
  "fields": [
    "ice",
    "wind",
    "wave",
    "current",
    "bathymetry"
  ]
}
```

返回必须包含：

```
value
unit
source
validTime
quality
available
reason
```

环境查询不能因为单个 Provider 失败就丢失所有已成功查询的数据。

# 第二阶段：船舶性能与航行安全

## 9. 迁移船舶资料模型

参考：

```
core/vessel/models.py
core/vessel/physical.py
core/vessel/propulsion.py
core/vessel/performance/

services/vessel_service/service.py

data/vessel/xuelong2.json
```

新增船舶资料模块。

优先使用 V3 当前已有的“雪龙2”资料作为样例船舶能力数据，但应明确这是静态船舶资料，不能伪装成实时船位或传感器数据。

功能：

```
船舶名称
船型
冰级
船长
船宽
设计吃水
设计排水量
主推进装置
推进功率
服务航速
最大航速
续航能力
破冰能力
```

原型参数应保留来源与单位。

不能任意修改船舶物理参数以使规划结果更好看。

## 10. 船舶管理 UI

建议新增：

```
VesselProfilePanel.vue
```

并允许在规划任务中选择船舶。

支持查看：

- 船舶基本信息；
- 吃水与安全富余水深；
- 最大推进功率；
- 航速约束；
- 冰区航行能力。

只有经过模型验证的参数才用于规划计算。

V3 中未接入的实时速度、位置、航向字段，应显示“未接入实时船舶状态”，不要显示模拟的实时值。

## 11. 水深安全

参考：

```
services/vessel_service/depth_safety.py
services/planner_service/land_mask.py
```

迁移安全水深校验。

至少实现：

```
可用水深
船舶吃水
富余水深 UKC
浅水判定
陆地判定
未知水深判定
```

当底层水深数据缺失时：

```
status = UNKNOWN
```

不能自动变成：

```
SAFE
```

对于规划网格中的浅水、陆地和不可通行区域，使用明确阻断规则。

# 第三阶段：风险评估模型

## 12. 移植 V3 环境风险模型

重点读取：

```
services/planner_service/environment_model.py
services/planner_service/environment_adapter.py
services/planner_service/historical_frequency.py
services/planner_service/land_mask.py
```

当前源码存在以下风险权重定义：

```
RISK_WEIGHTS = {
    "ice": 0.4,
    "depth": 0.2,
    "fog": 0.2,
    "wind": 0.1,
    "wave": 0.1,
}
```

这些是原型中的模型参数，不应被解释为经过权威验证的普适海事风险权重。

本次默认保持原模型行为以保证迁移可复现。

如果需要修改权重，必须：

1. 形成参数版本；
2. 说明原因；
3. 增加针对性测试；
4. 比较修改前后输出；
5. 保留原模型作为对照。

## 13. 风险评估必须输出分项解释

建立统一风险结果：

```
iceRisk
depthRisk
fogRisk
windRisk
waveRisk
combinedRisk
traversable
quality
sources
```

不允许仅返回一个无法解释的风险分数。

风险不确定时，必须明确：

```
missing
unknown
synthetic
```

并按照安全策略处理。

不得把：

```
data unavailable
```

等同于：

```
risk = 0
```

## 14. 规划环境栅格

参考：

```
services/planner_service/northern_grid.py
services/planner_service/static_grid.py
services/planner_service/environment_model.py
```

保留 V3 当前 25km 环境栅格及其坐标和约束设计作为初版规划基线。

需要明确：

```
规划网格不是海图瓦片
规划网格不是屏幕像素
规划网格不能直接使用 OpenLayers zoom 代替分辨率
```

网格中心业务坐标应统一为 WGS84。

地图可视化时再转换为：

```
EPSG:3413
EPSG:3857
```

对于 25km 栅格，真实测地距离、邻接关系、边权和障碍状态需要独立计算，不能直接用屏幕平面距离近似。

## 15. 新增风险可视化图层

建议：

```
PlanningRiskLayer
```

能够显示：

```
综合风险
海冰风险
水深风险
风风险
浪风险
雾风险
```

使用图层下拉选择。

不需要一次同时渲染六张完整风险栅格。

建议：

```
风险类型选择
       ↓
请求指定 planId 的风险层
       ↓
生成瓦片或裁剪后的矢量网格
       ↓
在当前 OpenLayers Map 上叠加
```

对于大型网格，应采用分层采样、瓦片或视口裁剪，避免一次渲染全部单元。

点击某个风险单元，显示：

```
位置
时间
综合风险
各风险分项
有效数据源
数据质量
通航状态
不可通航原因
```

风险网格的来源必须绑定对应规划快照，而不是地图当前时间随意变化后继续显示旧结果。

# 第四阶段：多目标路径规划算法

## 16. 迁移 D* Lite 与 NSGA-III 实现

重点审查：

```
services/planner_service/dnsga3.py
services/planner_service/service.py
services/planner_service/environment_model.py
services/planner_service/environment_adapter.py
services/planner_service/energy_model.py
services/planner_service/speed_model.py
services/planner_service/northern_grid.py
services/planner_service/static_grid.py
```

先确认 D* Lite 初始路径在真实执行链中对应的函数和调用位置，不要仅凭 README 声明认为其已经完整参与规划。

迁移后仍采用：

```
初始可行路径搜索
        ↓
环境边代价评价
        ↓
NSGA-III 多目标优化
        ↓
非支配候选解
        ↓
候选航线提取与排序
```

保留 V3 目前三目标：

```
Risk
Energy
Time
```

其中：

```
Distance
```

仅作为统计与对比指标，不参与 NSGA-III 的优化目标。

不要擅自把距离重新加入第四目标。

## 17. 保留统一 EdgeTransitResult 计算口径

必须检查 V3 的：

```
energy_model.py
environment_model.py
```

以及相关边评价模型。

要求每条规划边使用统一评价结果，供：

```
初始路径评估
多目标优化
风险分析
能耗统计
航时统计
结果解释
```

复用。

禁止在不同模块中重复实现不同的距离、风险、能耗公式，造成同一航线在多个页面中数值不一致。

## 18. 航速和功率约束

保留 V3 当前模型的关键区分：

```
0.5 kn：数值搜索下界
1 kn：有效运行航速下界
18 kn：物理最大航速
12 kn：敞水功率曲线参考速度
15 MW：当前样例推进功率上限
```

注意这些值来自当前原型模型和船舶设定，实际应由船舶资料及配置决定，不能固定为所有船舶通用数值。

风、浪、海冰、静水功率分量和海流沿航向速度修正必须分别计算。

能耗单位：

```
MWh
```

航时单位：

```
hours
```

速度单位：

```
kn
```

必须保留单位契约，不允许出现 km/h、m/s、kn 混算。

## 19. 缺测数据策略

V3 的 PlannerEnvironmentAdapter 有确定性 gap-fill。

不能直接删除该能力，因为它可能是当前 V3 规划算法覆盖部分区域的必要条件。

但必须为规划任务增加明确的数据策略：

```
real_only
allow_synthetic_research
```

其中：

`real_only`：

- 数据缺失时不构造伪观测；
- 阻断依赖缺失数据的安全结论；
- 无法完成可靠规划时返回 UNKNOWN 或不可规划状态。

`allow_synthetic_research`：

- 仅用于研究、仿真和算法测试；
- 缺口可由 V3 已实现的确定性 gap-fill 补足；
- 返回每个单元的数据来源和质量；
- UI 必须明确提示“含合成环境数据，不可作为真实航行决策依据”。

禁止将合成数据悄悄混入真实环境层。

## 20. 新增规划接口

采用 Polar-GIS 统一 `/api/v1` 命名空间。

建议：

```
POST /api/v1/navigation/plans

GET /api/v1/navigation/plans/{planId}

GET /api/v1/navigation/plans/{planId}/routes

GET /api/v1/navigation/plans/{planId}/risk-grid

GET /api/v1/navigation/plans/{planId}/risk-grid/{cellId}

POST /api/v1/navigation/plans/{planId}/cancel
```

实际 API 名称可根据现有项目规范调整。

请求至少包含：

```
{
  "projectId": "existing-project-id",
  "start": {
    "longitude": 120.0,
    "latitude": 75.0
  },
  "goal": {
    "longitude": 130.0,
    "latitude": 78.0
  },
  "departureTime": "2025-02-15T12:00:00Z",
  "vesselId": "xuelong2",
  "dataPolicy": "real_only",
  "algorithm": "dnsga3",
  "objectives": [
    "risk",
    "energy",
    "time"
  ]
}
```

不一定需要完全照此 JSON 实施，但必须保持：

```
经纬度语义明确
UTC 明确
单位明确
环境数据策略明确
算法参数可追踪
```

## 21. 不得在 HTTP 同步请求中无限运行规划

V3 当前原型规划接口为：

```
POST /api/planner
```

移植时必须评估计算耗时、CPU、内存和并发。

对于耗时规划任务，优先采用现有 Polar-GIS Worker/任务体系的可扩展模式，或新增边界清晰的规划任务执行器。

支持：

```
queued
running
completed
failed
cancelled
```

规划请求不得长时间占用地图常规 API 的处理能力。

如果初版保留同步规划，必须有明确耗时上限、输入网格上限和并发控制，并说明后续异步升级条件。

# 第五阶段：与 Polar-GIS 原有航路系统融合

## 22. 不能重写现有 useRouteDrawing

Polar-GIS 当前已有：

```
useRouteDrawing.ts
routesStore
RoutePlannerPanel.vue
RouteInfoFlyout.vue
mapRoute.ts
```

已经提供：

```
手动航线绘制
经纬度坐标输入
航点拖拽修改
多航路显示
航线选中
航线长度统计
航点信息浮窗
航路投影重建
```

这些功能全部必须保留。

V3 规划结果应新增独立数据契约和渲染层，而不是直接写入手动航路 Store。

## 23. 区分三类航路

建议新增：

```
type RouteOrigin =
  | 'manual'
  | 'algorithm'
  | 'adopted'
```

同时建立：

```
ManualRoute
RecommendedRoute
CaptainDraftRoute
```

并预留：

```
ActiveRoute
```

的生命周期契约。

第一阶段：

```
算法规划生成 RecommendedRoute
```

用户可以：

```
查看
选择
比较
采纳为草稿
```

当用户采纳后，将规划结果通过显式适配器复制成可编辑航路草稿。

不允许直接修改原始 RecommendedRoute 的结果快照。

不要把 UI 中的“采纳”误写成自动驾驶意义上的“执行”。

## 24. 航路数据坐标

所有航路业务数据统一使用：

```
WGS84 EPSG:4326
```

坐标顺序：

```
[longitude, latitude]
```

地图渲染时根据当前 CRS 转换。

不要因投影切换直接修改数据库中保存的业务坐标。

应兼容：

```
跨 180° 经线
北极高纬度
EPSG:3413
EPSG:3857
```

需要测试线路跨反经线时的显示和距离。

## 25. 候选航线显示

参考 V3 PlannerResponse 中的路线结构，新增：

```
PlanningRouteLayer
```

与原有手绘 RouteLayer 分离。

建议：

```
推荐路线：强调色
候选路线：不同线型或可区分颜色
未选中路线：较低透明度
当前选中路线：加粗高亮
```

每条航线应具有：

```
routeId
planId
coordinates
riskScore
energyMWh
timeHours
distanceKm
sourceQuality
algorithmVersion
```

其中字段要根据实际算法返回的数据决定，不得补造数值。

## 26. 航线对比

新增：

```
RouteComparisonPanel.vue
```

显示：

```
候选路线
风险
能耗
航时
距离
数据质量
```

推荐使用表格和已有 ECharts 组件。

可以增加 Pareto 解集散点展示：

```
X：能耗
Y：风险
颜色或 tooltip：航时
```

但只展示真实优化结果，不生成假的 Pareto 候选路线。

支持点击比较项：

```
高亮地图上的对应路线
缩放到路线范围
打开路线详情
```

## 27. 用户修改规划航线

当用户采纳某条候选路线：

```
RecommendedRoute
      ↓
Copy / Adapt
      ↓
CaptainDraftRoute
      ↓
Existing Route Drawing
```

用户可以继续：

```
拖拽航点
添加航点
删除航点
修改坐标
调整航路
```

修改后要重新计算：

```
航线长度
风险
能耗
航时
```

如果重新评估失败，显示：

```
当前航线已修改，风险和能耗结果需要重新计算
```

不得继续展示未修改前的旧指标作为有效结果。

# 第六阶段：前端完整功能融合

## 28. 新增工作台入口，而不是独立页面

Polar-GIS 当前已有全屏地图工作台。

建议在现有地图工具栏新增：

```
智能航行规划
```

或者在右侧原有航路规划面板增加：

```
规划方式：
手动绘制
智能规划
```

推荐采用后一种方式，避免重复创建两套航路管理 UI。

同时在环境叠加菜单中扩展：

```
海冰
水深
风场
海流
海浪
风险评估
```

保持地图作为所有功能的共同工作区。

## 29. UI 模块建议

根据 V3 现有组件重新实现适合 Polar-GIS 的模块：

```
NavigationTaskPanel.vue
VesselProfilePanel.vue
EnvironmentLayerPanel.vue
EnvironmentTimeControl.vue
RiskAnalysisPanel.vue
IntelligentPlanningPanel.vue
RouteComparisonPanel.vue
PlanningResultPanel.vue
```

不要原样复制 V3 的：

```
TopStatusBar.vue
MainNavigation.vue
App.vue
styles.css
```

以免覆盖 Polar-GIS 现有全局 UI。

复用当前：

```
Element Plus
ECharts
OpenLayers
Pinia
```

原则上不新增另一套 UI 框架。

## 30. 智能规划面板

规划界面至少包含：

```
起点
终点
出发时间
船舶选择
目标偏好
数据策略
算法参数
开始规划
任务状态
规划结果
```

起点和终点支持：

```
经纬度输入
地图点击选择
从现有手绘航路读取
```

如果选择已有航路，只允许提取真实航路端点或有效约束，不得直接删除或重写原有航路。

## 31. 规划运行状态

用户点击开始规划后：

```
校验参数
      ↓
提交规划请求
      ↓
显示状态
      ↓
获取规划结果
      ↓
加载候选航线
      ↓
显示比较面板
```

API 错误必须能够区分：

```
输入参数不合法
环境数据缺失
没有可行路线
规划超时
算法失败
服务不可用
```

不能统一显示“规划成功”或空白页面。

## 32. 时间轴与结果一致性

用户修改环境时间时：

```
海图不变
环境图层刷新
规划任务结果不自动被覆盖
```

如果环境时间改变，已有规划结果应标注：

```
规划快照时间与当前地图环境时间不同
```

如果用户希望基于新时间重新规划，需要创建新的规划任务或新版本结果。

## 33. 风险栅格与候选路线联动

用户切换候选路线时：

- 对应路线高亮；
- 风险图层仍然来自对应 `planId`；
- 右侧显示风险、能耗、航时；
- 点击风险单元展示该栅格真实数据；
- 风险详情不允许使用其他规划任务的快照。

## 34. 地图交互互斥

必须处理以下已存在的交互：

```
测量
航路 Draw
航路 Modify
要素识别
海冰 hover
普通坐标 hover
航路点选
```

新增：

```
规划起点选择
规划终点选择
风险栅格识别
算法航线点选
```

必须通过统一的模式协调，防止多个交互同时响应同一次点击。

优先考虑扩展现有交互模式，而不是在各组件中独立注册无法追踪的 `map.on('singleclick')`。

## 35. 图层顺序

保留现有：

```
S-57
Ice
Route
Measure
AIS
```

的现有层级。

新增风、浪、流、水深、风险和规划路线时，先审查实际 zIndex。

推荐按语义建立层级：

```
底图
S-57
水深环境层
海冰/风/浪/流
风险栅格
规划候选航线
用户手绘航线
航点/测量
AIS/交互高亮
```

新图层不得盖住现有关键航线交互层。

# 第七阶段：规划业务持久化

## 36. 规划任务与结果

建议新增数据库模型：

```
navigation_tasks
planning_runs
planning_routes
planning_route_points
planning_result_metadata
```

具体表是否都必要，应先审查原有 `projects` 和航路存储实现。

每次规划需要关联：

```
projectId
taskId
vesselId
departureTime
planningAlgorithm
environmentSnapshot
parameters
status
result
```

规划结果可选择：

```
数据库存结构化元数据
对象/文件存储保存较大风险栅格
```

避免把超大二维数组直接塞进数据库普通 JSON 字段。

所有数据库变更必须通过 Alembic migration。

## 37. 兼容现有手动航路草稿

如果当前 Polar-GIS 手绘航路通过 localStorage 保存：

- 不得直接改变旧 payload 格式；
- 不得导致旧航路丢失；
- 不得把规划任务 ID 误作原航路 ID；
- 对采用规划结果创建的新航路，可新增来源字段或版本迁移。

原有手绘功能必须无感升级。

# 第八阶段：性能、资源控制与部署

## 38. 环境数据不能占满地图瓦片通道

Polar-GIS 已经针对海冰加载完成优化。

新增环境图层时必须审查：

```
TileRequestQueue
LRUTileCache
IceOverlay loading
S-57 rendering
```

对于图片瓦片，采用统一或协调的请求预算。

对于风、浪、流的矢量场：

```
视口裁剪
缩放级别采样
最大要素数量
请求取消
数据缓存
```

不允许每次地图平移都请求全北极范围的大型环境矩阵。

## 39. 规划性能

建议在后端控制：

```
最大规划区域
最大栅格单元数
最大候选路线数
最大迭代数
最大执行时间
最大并发任务数
```

这些应配置化，并附带测试。

避免在请求中无条件加载整个 GEBCO 或多个海洋大栅格文件。

对于风险网格和大环境文件：

```
按需读取
空间裁剪
数据缓存
可复用网格
```

## 40. Docker

继续使用 Polar-GIS 当前：

```
postgres
geoserver
backend
worker
web
```

服务架构。

在没有真实需求前，不新增第二个独立 FastAPI 容器。

环境数据建议通过配置目录挂载：

```
/data/navigation/
├── ice/
├── wind/
├── wave/
├── current/
├── bathymetry/
└── planning/
```

实际目录应与现有 `data/ice` 和部署路径协调，避免同一份数据在多个目录中复制。

配置项包括：

```
NAVIGATION_ENABLED
NAVIGATION_DATA_ROOT
PLANNER_MAX_CELLS
PLANNER_MAX_CONCURRENT_JOBS
PLANNER_TIMEOUT_SECONDS
ENVIRONMENT_CACHE_SIZE
```

名称与默认值需要根据实际性能测试确定。

禁止硬编码 Windows 本地绝对路径。

## 41. Nginx 和鉴权

新增 API 使用：

```
/api/v1/navigation/
```

确保 Nginx 转发正确。

如果新增 `.png` 栅格瓦片接口，保留当前 `/api/` 优先匹配的配置，避免静态 PNG 正则拦截。

规划任务和结果查询必须沿用 Polar-GIS 认证体系，并校验项目权限。

普通用户可以在授权项目中执行规划；管理员保留数据源、系统配置和管理权限。

不要重新复制 V3 的独立认证系统。

# 第九阶段：完整测试与验收

## 42. 后端测试

移植并适配 V3 现有测试：

```
tests/providers/
tests/environment/
tests/vessel/

backend/tests/test_planner_dnsga3.py
backend/tests/test_planner_environment_adapter.py
backend/tests/test_environment_grid.py
backend/tests/test_depth_safety.py
backend/tests/test_vessel_profile.py
```

新增 Polar-GIS 集成测试：

```
test_navigation_environment_api.py
test_navigation_vessel_api.py
test_navigation_risk.py
test_navigation_planner.py
test_navigation_planning_tasks.py
```

至少覆盖：

- Provider 数据缺失；
- 多源数据查询；
- 单位转换；
- CRS 转换；
- UTC 时间匹配；
- `quality=synthetic` 标注；
- 零风险与缺测风险区别；
- 陆地不可通行；
- 浅水安全限制；
- 船舶速度和功率约束；
- D* Lite 初始路线；
- NSGA-III 候选解；
- 风险、能耗、航时一致性；
- Pareto 结果结构；
- 规划任务取消；
- 无路线返回；
- 授权和未授权访问；
- 原有海冰与 S-57 API 回归。

## 43. 前端测试

新增：

```
EnvironmentLayerPanel.test.ts
NavigationTaskPanel.test.ts
VesselProfilePanel.test.ts
RiskAnalysisPanel.test.ts
IntelligentPlanningPanel.test.ts
RouteComparisonPanel.test.ts
PlanningRouteLayer.test.ts
```

必须测试：

```
新增图层不创建第二个 Map
规划图层能正确销毁
双投影切换
路线跨 180° 经线
环境时间与规划时间区分
旧请求取消
风险单元选择
候选路线高亮
采纳结果后可编辑
原有手绘航线不丢失
规划服务失败时地图可继续使用
```

## 44. 现有功能回归

必须验证：

```
登录与退出
用户管理
项目管理
S-57 导入
S-57 批量加载
standard/smart/overview
Render Bundle
GWC
底图切换
EPSG:3413/3857
海冰密集度
海冰厚度缺失状态
IceTimeline
海冰 hover
AIS
气象演示
要素识别
测量
手动航路绘制
航路拖拽修改
航路选中
截图
打印
左右面板折叠
```

不得因新功能导致当前 Polar-GIS 核心功能退化。

## 45. 使用真实数据进行端到端验证

至少完成一条真实调用链：

```
打开 Polar-GIS
→ 登录
→ 进入项目地图
→ 打开环境图层
→ 加载可用环境数据
→ 选择船舶
→ 设置起点、终点和出发时间
→ 提交规划任务
→ 查询环境栅格
→ 计算风险
→ 执行规划算法
→ 返回 Pareto 候选航线
→ 地图显示航线
→ 对比风险、能耗、航时
→ 选择路线
→ 采纳为可编辑草稿
→ 修改航点
→ 重新评估或明确标记旧结果失效
```

如果现实数据不足以完成某个场景，应明确列出缺失的数据集、时间、区域和限制，不允许伪造测试成功。

可以用标注清楚的合成测试数据测试算法，但不能将此结果写成“真实环境规划已验证”。

# 第十阶段：推荐执行顺序

整个任务按五个实施批次推进。

### 批次 A：架构审计与接口契约

完成：

```
功能矩阵
依赖闭包审计
版本与依赖冲突核查
环境/船舶/风险/规划数据契约
测试基线
```

输出审计报告和接口设计。

### 批次 B：环境感知与船舶模型

完成：

```
Provider
环境查询
风浪流水深图层
环境时间
船舶资料
安全水深
```

形成可独立运行的环境与船舶服务。

### 批次 C：风险模型与规划算法

完成：

```
风险评估
风险网格
环境 Adapter
速度/功率/能耗模型
D* Lite
NSGA-III
规划 API
```

先通过后端真实计算与测试，再集成 UI。

### 批次 D：地图、航路和规划工作台

完成：

```
规划任务
候选航线
路线对比
风险图层
路线采纳
手动修改
结果保存
```

所有内容嵌入现有 MapWorkspaceView，禁止创建新地图应用。

### 批次 E：性能、回归和交付

完成：

```
前后端全量测试
Docker 构建
端到端联调
性能压测
数据质量核查
现有功能回归
用户手册
架构文档
开发工作日志
```

每个批次结束后输出实际修改文件、运行结果、未通过项及下一批次依赖。

# 第十一阶段：最终交付标准

移植完成后，至少实现以下用户可见能力：

**环境感知：**

用户能够在 Polar-GIS 地图上选择并显示可用的风、浪、流、水深和海冰环境图层，查看时间、图例、原始环境值及数据质量。

**船舶能力：**

用户能够选择船舶资料，查看推进功率、航速、吃水与冰区性能参数，并让规划模型使用对应船舶约束。

**风险评估：**

用户能够对已选区域或规划结果查看环境综合风险、分项风险、风险栅格及不可通航区域。

**智能规划：**

用户能够提交起终点、船舶、时间和目标约束，真实调用 V3 移植的规划模型，获取算法产生的候选航线。

**多路线比较：**

用户能够对风险、能耗、航时和距离进行比较，在地图中高亮候选路线。

**航线编辑：**

用户能够将候选路线采纳为可编辑草稿，继续使用 Polar-GIS 原有航点修改功能，修改后让风险和规划指标重新评估或明确失效。

**系统稳定性：**

新增模块不可用时，S-57、海冰、已有航线、测量、登录、项目管理必须仍然正常工作。

# 第十二阶段：必须保留的安全与科研边界

本平台属于船舶导航辅助决策与科研验证系统。

不能将其描述成经过认证的 ECDIS 或自动驾驶系统。

不得实现自动操舵、自动推进控制或未经审核的航线自动执行。

`RecommendedRoute` 仅供人工审核，不能直接成为自动控制指令。

对于：

```
real
synthetic
missing
unknown
```

必须保留清晰区分。

不确定数据不能直接被描述为安全。

高级功能如 RG-MPAO*、CF-JRS、RCOS、Truth/Forecast/Observation/Belief 完整体系，只有在实际源码和测试存在可复用实现时才纳入本轮迁移；如果仅有 V5 设计文档，应作为后续研究扩展，不得宣称完成。

# 第十三阶段：最终交付报告

完成开发后输出：

```
1. 实际基线 Commit
2. 两个仓库功能对照矩阵
3. 已迁移源码清单
4. 重构后的业务架构
5. 数据源和 Provider 清单
6. 已完成环境感知功能
7. 已完成船舶性能功能
8. 已完成风险评估功能
9. 已完成多目标规划功能
10. 前端交互完成情况
11. 新增 API 文档
12. 新增数据库迁移
13. Docker 部署变化
14. 后端测试结果
15. 前端测试结果
16. 真实数据端到端验证
17. 现有 Polar-GIS 功能回归结果
18. 性能与资源占用
19. 已知限制和未实现功能
20. git diff --stat
21. 推荐 Commit Message
```

同步更新：

```
docs/09-system-architecture.md
docs/10-work-log.md
docs/11-work-summary.md
docs/12-user-manual.md
```

不允许删除历史开发记录。

不允许没有运行测试就宣称测试通过。

没有明确授权时不自动 commit、push 或覆盖生产数据。

**最终验收原则：必须是 Polar-GIS 系统内真正可调用、可展示、可验证的功能，而不是 V3 项目重新启动成功、前端增加几个按钮或者 API 返回模拟 JSON。**