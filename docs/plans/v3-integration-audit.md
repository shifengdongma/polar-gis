# PolarOptionNav-System-V3 → Polar-GIS 集成审计

> 批次 A 交付。审计日期：2026-10-29。审计方式：只读代码审查 + git 状态检查 + 基线测试（结果见 §12）。
> 结论以实际代码/测试为准；文档声明与代码不一致处已单列（§11）。

## 0. 基线与仓库状态

| 项目 | 路径 | 分支 | HEAD | 工作区 |
|---|---|---|---|---|
| Polar-GIS | `F:\polar-gis` | `master` | `728020b2bccbfed148bdeefe50fae43fcd564f08` | 仅 V3 目录与任务书未跟踪；V3 已加入 `.gitignore` |
| PolarOptionNav-System-V3 | `F:\polar-gis\PolarOptionNav-System-V3` | `main` | `237767b122ba52ff612411d15984b23a2d2a6495` | clean（嵌套 git 仓库） |

- Polar-GIS 默认分支 `master`；V3 默认分支 `main`。
- V3 无根 `pyproject.toml`/`Dockerfile`/CI；`pytest.ini` 依赖 `pythonpath = .`，使用顶层 `core.*`/`services.*` import 与 `Path(__file__).parents[2]` 数据路径。
- V3 的 `.venv` 指向不存在的 `D:\conda` 解释器；本机全局 Python 3.12.7 缺 netCDF4/pyproj/xarray/shapely/rasterio，因此 V3 测试未能在其自身环境运行（其真实数据用例本身也会 skip）。
- Polar-GIS `.venv` 可用（Python 3.12.7，FastAPI 0.139.2、SQLAlchemy 2.0.51、numpy 2.5.3、netCDF4/pyproj 可用）；前端 `node_modules` 已存在。

## 1. 实际技术栈

### Polar-GIS
- 后端：Python 3.12+，FastAPI（`/api/v1`），SQLAlchemy 2，Pydantic v2，PostgreSQL/PostGIS，Alembic，netCDF4/numpy/Pillow/pyproj；GDAL 仅 CLI（ogrinfo/ogr2ogr/gdalinfo）；GeoServer + GWC；pytest（18 个测试模块、202 个 `def test_`，文档记录 214 passed）。
- 前端：Vue 3.5、Vite 7、TypeScript 5.9（strict）、OpenLayers 10.6.1、Element Plus 2.11（zh-CN）、ECharts 6、Pinia 3、Axios 1.12、Vitest 3.2 + jsdom。
- 部署：`deploy/compose.yml` 五服务（postgres/geoserver/backend/worker/web）；nginx `location ^~ /api/` 优先于 PNG 正则。

### PolarOptionNav-System-V3
- 后端：FastAPI（`/api`）、Pydantic v2、numpy/netCDF4/pyproj/Pillow；xarray 仅用于 `copernicus_ice.py`；rasterio 仅用于 `polar_bathymetry.py` 与 `static_grid.py` 的网格重建；shapely 仅 chart service；无 scipy/pymoo。
- 规划：自研 D* Lite + 自研 NSGA-III（heapq，非 pymoo）；NumPy-only。
- 前端：Vue 3.5、Vite 6、OpenLayers 10.3、proj4、Vitest 2.1；自带 `App.vue`/独立 `ol/Map`。
- 无认证、无异步任务、无数据库、无 Docker/CI。

## 2. Polar-GIS 已实现功能（保留基线）

| 能力 | 状态 | 证据 |
|---|---|---|
| JWT access + HttpOnly refresh、角色/审计 | 已实现 | `backend/app/core/security.py`, `api/auth.py`, `api/deps.py` |
| 项目管理/发布/图层配置 | 已实现 | `backend/app/api/projects.py` |
| S-57 导入、PostGIS、GeoServer 发布、GWC | 已实现 | `services/importer.py`, `services/geoserver.py` |
| 批量导入 worker（batch → import job） | 已实现 | `worker/main.py`, `services/s57_batch.py` |
| S-57 Render Bundle / 调度 / LRU / 请求队列 | 已实现 | `services/map_render_plan.py`, 前端 `mapRenderScheduler.ts`, `tileCache.ts`, `tileRequestQueue.ts` |
| 海冰浓度/厚度 NetCDF → PNG 瓦片/时间轴/hover | 已实现（数据目录默认可为空） | `services/ice.py`, `api/ice.py`, `useIceOverlay.ts` |
| 手绘航路（绘制/拖拽/多航路/浮窗/长度/方位） | 已实现（localStorage） | `stores/routes.ts`, `useRouteDrawing.ts`, `mapRoute.ts` |
| 测量/识别/气象演示/AIS 演示/截图/打印/面板折叠 | 已实现 | `MapWorkspaceView.vue` |
| 环境 Provider（风/浪/流/水深）、船舶、风险、规划、后端航路持久化 | **缺失** | 后端/前端搜索无运行时实现 |
| 项目成员 ACL | **缺失** | `projects.py:78-89` 仅校验 published |

前端关键事实：
- 单一 `new OlMap`（`MapWorkspaceView.vue:790`）；EPSG:3857/3413；`switchProjection`（:1350-1390）替换整个 View。
- 唯一 `pointermove`（:808-828）与唯一 `singleclick`（:829-842）；模式通过手工 flag 互斥。
- zIndex：S-57 10-40、冰 60/62、手绘航路 95、测量 100、AIS 110、冰对齐调试 120。
- 右侧 `RoutePlannerPanel` 为 520px 非模态 drawer；左栏含 `IceLayerPanel` 与“环境叠加”下拉；底部 `IceTimeline`。
- `types/routePlanning.ts` 已有只读契约（null≠0、结果≠草稿、status/adapter），但无运行时消费者。

## 3. V3 六类功能分类

> 分类口径：1 已有可运行代码；2 已有算法但未接真实数据；3 已有 API 但 UI 未接；4 仅 UI 占位；5 仅设计文档；6 真正缺失。

| 能力 | 类别 | 证据/说明 |
|---|---:|---|
| 五类 Provider 文件读取（GEBCO/neXtSIM/CARRA2/TOPAZ5/WAM） | 1* | `core/providers/*`, `services/environment_service/*`；本机无数据，数据门控 |
| `EnvironmentQueryService` 多源查询/故障隔离/批量 | 1* | `environment_query.py:56-201`；无聚合 quality/issue time |
| `EnvironmentTimeManager` 模拟时钟 | 1 | `time_manager.py:17-141`；非真实数据时间解析 |
| 船舶资料 + 水深安全 | 1 | `data/vessel/xuelong2.json`, `depth_safety.py`；吃水存在冲突 |
| D* Lite | 1 | `dnsga3.py:95-193`；一次性，作为 NSGA 种子 |
| 自研 NSGA-III | 1 | `dnsga3.py:196-347`；三目标 Risk/Energy/Time，Distance 仅统计 |
| 能耗/功率模型 | 1 | `energy_model.py:89-185`；常量固定 |
| 25km NEP 静态网格/land mask | 1 | `static_grid.py`；NPZ 110×240 |
| 风险模型 | 2 | `environment_model.py:26-90`；主路径输入合成 |
| 规划主路径 `/api/planner` | 2 | `service.py:44-159`；`northern_grid.py:46-58` 合成冰/风/流/浪 |
| 风险栅格 API | 3 | `routes.py` 返回 `risk_layers`；前端 `getPlannerGrid` 未调用、`riskLayersData` 未赋值 |
| 环境/风险/航线图层 | 1* | 前端 `map/layers/*`；数据门控 |
| PlanningPanel 路线列表/指标 | 1/2 | `PlanningPanel.vue`；后端环境合成 |
| Captain Draft 前端编辑 | 1（仅前端） | `App.vue:645-684`；无后端校验/持久化 |
| 验证/接受/激活、监控、事件 | 4 | 禁用控件/空面板 |
| 实时船位/AIS/雷达/XTE/ETA | 6 | 无 |
| Truth/Forecast/Observation/Belief、SparseGraph、EdgeEvaluator、RG-MPAO*、CF-JRS、RCOS | 5 | 仅 docs/product、engineering |
| 后端任务持久化/取消/超时/鉴权/并发 | 6 | 同步 `/api/planner`，内存快照上限 8 |
| 规划 E2E 测试 | 6 | 无测试执行 `PlannerService.plan` 或带请求体的 `/api/planner` |

`*` 表示源码可运行但本机缺真实数据/依赖。

## 4. 重叠功能清单

| 领域 | Polar-GIS | V3 | 集成策略 |
|---|---|---|---|
| 地图 | 单一 Map、S-57/冰/航路/测量 | 独立 Map、chart/bathy/ice/wind/current/wave | 保留 Polar-GIS Map；只移植图层算法 |
| 海冰 | IceService + PNG + Timeline + hover | neXtSIM Provider + 冰瓦片 | 复用 IceService 作冰后端，不覆盖既有瓦片 |
| 航路 | 手绘 localStorage + 编辑 | 前端 Captain Draft + 单路线渲染 | 手绘保持；规划结果独立 Store/图层 |
| 规划 | 无 | 同步 D*+NSGA-III、内存快照 | 移植算法，改异步任务 + 持久化 |
| 环境 | 无（仅海冰） | 五类 Provider/查询/时间轴 | 移植并补 quality/time/manifest |
| 船舶 | 无（AIS 演示） | 静态 profile + depth safety | 迁移，统一吃水/UKC |
| 风险 | 无 | 权重/公式/风险栅格 | 迁移，分 legacy_v1/real_v1 |
| 认证/权限 | JWT/角色/published 项目 | 无 | 沿用 Polar-GIS；不复制 V3 认证 |
| 部署 | 五服务 Docker | 本地 uvicorn/vite | 只扩展 Polar-GIS compose |

## 5. V3 可直接复用文件

**后端**
- `core/contracts/*.py`：coordinates/directions/time/units/quality/evidence/status（语义完整、有测试）。
- `core/netcdf.py`：netCDF 打开辅助（需去掉 Windows CWD 变更）。
- `core/providers/{base,common/*,gebco,nextsim,carra2,topaz5,wam}`：netCDF4 readers/adapters，含 issue time/quality 字段。
- `core/environment/{fields,grid,metadata,sample,snapshot,query/*}.py`：环境字段/查询模型（按需）。
- `core/vessel/{models,physical,propulsion}.py`：静态船舶模型（精简）。
- `services/environment_service/{wind,current,wave,copernicus_ice,providers}.py`：变量别名、插值、TOPAZ 旋转、WAM 方向处理（需修正语义）。
- `services/environment_service/{environment_query,time_manager,grid}.py`：故障隔离/缓存/时间/格点模式。
- `services/planner_service/{dnsga3,energy_model,environment_model,environment_adapter,northern_grid,static_grid,land_mask}.py`：算法与公式基线。
- `services/vessel_service/depth_safety.py`：draft+UKC 判定（需改 UNKNOWN）。
- `data/vessel/xuelong2.json`（1,996B）、`data/planning/northeast_passage_25km_static.npz`（488KB）。
- `backend/tests/*` 与 `tests/*` 中的 Provider/contracts/D*/NSGA/风险 adapter/船舶/网格测试（需适配 import）。

**前端（只移植算法/布局思想）**
- `map/{managed-layer,polar-view}.ts`、`map/layers/{bathymetry,ice,wind,current,wave}-layer.ts`。
- `services/{wind-field,current-field,wave-field,environment-display-cache,environment-feature-pool}.ts`。
- `components/{PlanningPanel,VesselPanel,EnvironmentPanel,EnvironmentTimeline,TaskPanel}.vue` 的布局/交互思想（不复制全局样式）。

## 6. V3 必须重构文件

| 文件/模块 | 问题 | 重构要求 |
|---|---|---|
| 全部顶层 `core.*`/`services.*` import | 目标仓库无这些包 | 迁入 `backend/app/navigation/` 并改 import |
| `config/environment.yaml`, `core/config/environment_config.py` | Windows 绝对路径 `G:\...`、`parents[2]` | 改用 Polar-GIS `Settings`，数据根配置化 |
| `core/netcdf.py` | 进程 CWD 变更，非并发安全 | 安全 open helper，禁止 CWD 变更 |
| `services/environment_service/copernicus_ice.py` | xarray 读取 | 改 netCDF4 或由 IceService 适配 |
| `services/planner_service/static_grid.py` | 模块级 import rasterio；builder 依赖 GeoTIFF | 拆 NPZ loader（无 rasterio）与离线 builder |
| `services/environment_service/{wind,current,wave}.py` | TOPAZ 旋转、WAM FROM、CARRA2 变量差异 | 统一契约并修正；tests 覆盖 |
| `services/planner_service/speed_model.py` + `energy_model.py` | 两套速度模型，UI 显示值与目标值不一致 | 删除 speed_model 作为目标来源；统一 EdgeTransitResult |
| `services/planner_service/environment_adapter.py` | 默认合成 gap-fill，缺测→伪观测 | dataPolicy 驱动；real_only 禁止合成 |
| `services/planner_service/northern_grid.py` | `_dynamic_cell` 合成冰/风/流/浪 | 删除；只用真实 Provider/快照 |
| `services/vessel_service/service.py` | draft=10 vs profile 7.85 | 统一 profile draft + UKC=2.0 |
| `backend/app/routes.py` | 同步、无鉴权/超时/持久化 | 重写为 Polar-GIS 异步规划任务 API |
| `frontend/src/App.vue` 等 | 独立 Map/全局 UI | 不复制；嵌入 MapWorkspaceView |
| 风险栅格前端路径 | `riskLayersData` 未赋值 | 重新实现独立 RiskGridLayer |

## 7. 不应移植的文件

- `PolarOptionNav-System-V3/frontend/src/App.vue`、`TopStatusBar.vue`、`MainNavigation.vue`、`styles.css`（会覆盖 Polar-GIS 全局 UI/地图）。
- `services/chart_service/*` 与 `data/charts/base_map.gpkg`（Polar-GIS 用 S-57）。
- `SyntheticEnvironmentProvider`、`MockIceProvider`、`MockVesselProvider` 作为运行时数据。
- `northern_grid._dynamic_cell` 的合成环境。
- `PlannerEnvironmentAdapter` 合成值作为默认/生产策略（仅保留为 `allow_synthetic_research` 的确定性 gap-fill）。
- `historical_frequency.py`（Open-Meteo 网络依赖，主规划路径未用）。
- 仅设计文档功能：Truth/Forecast/Observation/Belief、SparseGraph、EdgeEvaluator、RG-MPAO*、CF-JRS、RCOS。
- V3 的独立 FastAPI 应用/路由/进程级 service 单例、Windows 数据路径、损坏的 `.venv`。

## 8. 现有环境/地图/航路状态冲突

1. **单一 Map 约束**：新增图层不得 `new OlMap`；必须由 `MapWorkspaceView` attach/dispose。
2. **单一事件入口**：只有 `map.on('singleclick')`/`pointermove` 各一个；新增选点/风险识别必须扩展优先级链，禁止第二个监听器。
3. **模式互斥**：`queryMode/weatherMode/measureMode/routesStore.interactionMode/routeFlyout/ice hover` 靠手工 flag；新增 `pickMode/riskInspect` 必须在所有 toggle、`deactivateOtherMapInteractions`、`iceOverlay.canQueryValue`、关闭面板处清理。
4. **zIndex 冲突**：S-57 bundle zIndex 由服务端给出（通常 10-40）；冰 60/62、航路 95、测量 100、AIS 110。新层用 50/64/66/68/70/90/91，需实测 bundle zIndex。
5. **投影切换**：`map.setView` 替换 View；新图层必须从 WGS84 重建并 `reloadForProjection()`；反经线需 unwrap/world-copy。
6. **瓦片通道**：冰与 S-57 共享 `tileCache`(50MB/2048) + `tileRequestQueue`(16 并发/512 队列)；新增环境瓦片必须共享并 generation abort，不得添加无界预取。
7. **航路真值**：手绘 `RouteDraft` 是 localStorage v1（key `polar-gis:route-drafts:{projectId}:v1`）；规划结果必须独立 Store/图层；采纳是复制，不是改写推荐快照。
8. **面板几何**：520px drawer 与 540/550/420 预留宽度硬编码在 `MapWorkspaceView.vue:317,383,610-611` 与 `useRouteDrawing.ts:56`；加宽需同步全部。
9. **时间语义**：`IceTimeline` 是冰情专用索引式时间轴；新环境时间控制不能替换它，需明确两套时间边界。
10. **测试不变量**：`MapWorkspaceView.test.ts` 禁止 `new Select(`、`getLength(`/`getArea(`、singleclick 内 `routePanelVisible`、`setActiveRoute(null)`；实现必须绕开这些写法。

## 9. 数据文件缺失与外部依赖

| 数据 | V3 期望 | 本机状态 | Polar-GIS 现状 |
|---|---|---|---|
| GEBCO 水深 | `GEBCO_2026_sub_ice.nc`（elevation/lat/lon） | 缺失 | 无 |
| neXtSIM 海冰 | `arctic_ice_YYYYMMDD.nc`（siconc/sithick/…） | 缺失 | `data/ice` 空；`sample-data/` 有 149 个 2022 年冰浓度文件（945MB，gitignored），无厚度 |
| CARRA2 风 | 月度 `10m_wind_speed/direction_YYYYMM.nc`（si10/wdir10） | 缺失 | 仅 demo 气象
| TOPAZ5 流 | `Copernicus_current_YYYYMMDD.nc`（vxo/vyo，原生 x/y） | 缺失 | 无 |
| WAM 浪 | `Copernicus_wave_YYYYMMDD.nc`（VHM0/VTPK/VMDR） | 缺失 | 无 |
| 静态规划网格 | `northeast_passage_25km_static.npz` | 存在（488KB） | 无 |
| 雪龙2 资料 | `xuelong2.json` | 存在（1,996B） | 无 |
| V3 chart GPKG | `base_map.gpkg` 7.7MB | 存在 | 不需要（S-57） |
| Copernicus/CDS 凭证 | tools 需 copernicusmarine/cdsapi | 无 | 无 |

外部依赖：`copernicusmarine`、`cdsapi` 仅在 V3 `tools/data_tools/requirements.txt`，不是运行时依赖；本任务不自动下载数据。合成测试数据必须通过 `navigation_manifest.json` 标记 `quality=synthetic`，`real_only` 拒绝。

## 10. 已实现 vs 待实现差距矩阵

| 能力 | Polar-GIS 现状 | V3 现状 | 本任务目标 |
|---|---|---|---|
| 环境 Provider/查询 | 仅海冰 | 五类读取，缺数据/quality | 迁移 + manifest quality + 时间解析 + 批量采样 |
| 环境图层 | 仅海冰 | 五类图层（数据门控） | 水深栅格 + 风/流/浪矢量 + 独立状态/图例 |
| 环境时间 | IceTimeline | 模拟时钟 | 明确 requested/matched/valid/issue；规划快照 |
| 船舶 | 无 | 静态 profile + depth safety | 迁移，统一 draft 7.85 + UKC 2.0 |
| 水深安全 | 无 | SAFE/不安全 | SAFE/UNSAFE/UNKNOWN；陆地/浅水阻断 |
| 风险 | 无 | 权重/公式/风险栅格 | 分项 + combined + quality + real_v1/legacy_v1 |
| 规划网格 | 无 | 25km NEP 静态 NPZ | 复用；不当作瓦片/像素 |
| D* Lite | 无 | 一次性种子 | 迁移 + deadline/cancel |
| NSGA-III | 无 | 自研三目标 | 迁移 + 超时/取消/持久化 |
| 能耗/航时 | 无 | 边评价模型 | 统一 EdgeTransitResult + 船舶参数注入 |
| 规划任务 | 无 | 同步/内存 | 异步 worker + 状态机 + 取消 + 超时 |
| 规划结果 | 无 | 内存 8 条 | DB 元数据 + gzip 风险栅格文件 |
| 候选航线 UI | 无 | 单路线/列表 | 独立规划图层 + 对比 + 风险联动 |
| 采纳/编辑/重评 | 手绘可编辑 | 前端草稿 | 显式 adapter + stale + evaluate-route |
| 回归 | 完整 | 无 | 保持 S-57/冰/航路/测量/认证 |

## 11. 文档与代码不一致

1. V3 README/docs 暗示真实 Provider 驱动规划；主路径 `northern_grid.py:46-58` 使用合成冰/风/流/浪，只有静态水深来自真实 Provider。
2. V3 product docs 称 planner 为 mock、UI 不调用；实际 `routes.py:500-520` 有请求路径，`App.vue:589-625` 调用，`PlanningPanel.vue` 渲染路线。
3. V3 UI audit 称 route line/Captain Draft 未实现；实际 `App.vue:535-550,645-684` 已实现前端路线与草稿编辑。
4. V3 测试通过数在不同文档中为 66/95/103；无测试执行 `PlannerService.plan` 或带请求体的 `/api/planner`。
5. V3 `VesselService` 使用 draft=10m，资料/规划器使用 7.85m；同一船不同页面要求水深不同。
6. V3 `speed_model.effective_speed_knots` 与 `energy_model.calculate_edge_transit` 是两套速度/功率模型，UI 显示值与目标值不一致。
7. V3 V5 adapters 语义缺陷：TOPAZ 未旋转矢量、WAM 将 FROM 标为 TO、CARRA2 期望 u10/v10 而运行时文件是 si10/wdir10。
8. V3 前端风险层死路：`getPlannerGrid` 未调用、`riskLayersData` 未赋值；后端返回的 `risk_layers` 未显示。
9. V3 `config/environment.yaml` 含 Windows 绝对路径；`.venv` 损坏。
10. Polar-GIS README 写 168 测试，work log 记录 214 passed；`docs/09` 写 GeoServer 2.26.2，compose 固定 2.25.3；`docs/09` 文件清单仍列 11 个测试文件（实际 18）。
11. Polar-GIS `types/routePlanning.ts` 明确声明“后端无规划/船舶/风险服务”，与 V3 已有代码不矛盾（该文件指 Polar-GIS 自身）；集成时不得把它误当作已有运行时。

## 12. 测试基线（实际执行）

| 命令 | 结果 | 备注 |
|---|---|---|
| `cd backend && pytest tests/ -q` | **214 passed, 0 failed**（72+72+70 dots；exit 0） | 仅有 Starlette/httpx 与 NumPy 2.5 deprecation warnings；无失败 |
| `cd frontend && npm test` | **20 files / 353 tests passed**（exit 0，38.6s） | Vitest 3.2.7，jsdom |
| `ruff check app tests` | **29 errors（24 fixable），既有基线** | 均在既有 `app`/`tests` 文件（未排序 import、未使用 import 等）；本任务新增代码必须单独通过 `ruff check app/navigation`，不顺手修无关历史问题 |

> 基线结果由批次 A 实际运行填入；不修改无关失败，只记录。后续批次以此为零回归基线。

## 13. 最小侵入迁移计划

- **Batch A**：提交隔离、审计、契约、配置、资源、测试基线。
- **Batch B**：五类 Provider + manifest + 时间解析 + 批量采样 + 水深瓦片 + 船舶/UKC + 前端环境图层。
- **Batch C**：风险分项/风险栅格 + D* Lite/NSGA-III + EdgeTransitResult + dataPolicy + 异步 planning_runs/worker + API/迁移。
- **Batch D**：规划工作台 UI、候选航线/对比/风险联动、采纳/编辑/stale/重评、交互互斥、localStorage v2。
- **Batch E**：Docker/Nginx/合成 fixture/E2E/性能/回归矩阵/文档/最终报告。

**不新增服务、不复制 V3 应用、不覆盖现有海冰/手绘航路/S-57。** 所有新代码在 `backend/app/navigation/`、`frontend/src/{components,composables,utils,stores,api}` 内，按 attach/update/dispose 生命周期接入唯一 Map。

## 14. 已知限制（审计阶段）

- 本机无真实环境数据，无法在本轮验证真实环境规划；E2E 只使用明确标注的合成数据。
- Polar-GIS 无项目成员 ACL；规划沿用 published project + 认证，取消限 requester/admin。
- V3 的 V5 目标架构（Truth/Belief/稀疏图/RG-MPAO* 等）仅有文档，不纳入本轮。
- V3 的图表面板/独立地图/全局样式不迁移。
- 依赖不新增 xarray/rasterio/shapely/scipy/pymoo；若实现受阻，单独评审并记录。
