# PolarOptionNav-System-V3 → Polar-GIS 集成最终交付报告

> 日期：2026-10-30。本报告只描述实际运行/测试结果；真实环境规划未验证，E2E 使用明确标记的
> 合成研究数据。详细审计见 `docs/plans/v3-integration-audit.md`。

## 1. 实际基线 Commit

| 项目 | 分支 | HEAD |
|---|---|---|
| Polar-GIS | `master` | `728020b2bccbfed148bdeefe50fae43fcd564f08`（集成前） |
| PolarOptionNav-System-V3 | `main` | `237767b122ba52ff612411d15984b23a2d2a6495` |

集成批次提交（`git log 728020b..HEAD`）：

- `2ca5249` 批次 A：审计、契约、测试基线
- `693eaa4` 批次 B：环境 Provider/查询/船舶/环境图层
- `3cf70cc` 批次 C：风险、D*/NSGA-III、异步任务、持久化
- `0173f4b` 批次 D：前端规划工作台、候选航线、风险格、采纳编辑
- 批次 E：部署、E2E、回归、文档（本报告所在提交）

## 2. 两个仓库功能对照矩阵

| 能力 | Polar-GIS 集成前 | V3 | 集成后 Polar-GIS |
|---|---|---|---|
| S-57/GeoServer/GWC | 完整 | 无（自有 chart） | 原样保留 |
| 海冰图层/时间轴/hover | 完整 | 独立实现 | 原样保留；规划通过 IceService 适配 |
| 五类环境 Provider | 无 | 真实读取但本机缺数据 | 已迁移，严格质量/时间/manifest |
| 环境图层（风/流/浪/水深） | 无 | 独立 Map 图层 | 唯一 Map 上独立图层 |
| 船舶资料/水深安全 | 无 | 静态资料 | 雪龙2 静态资料 + UKC/UNKNOWN |
| 风险分项 | 无 | 原型公式 | legacy_v1 + real_v1，分项/质量/来源 |
| D* Lite/NSGA-III | 无 | 自研、同步 | 迁移 + 超时/取消/异步 worker |
| 规划持久化 | 无 | 内存 | planning_runs/routes + gzip 风险格 |
| 规划 UI/航路融合 | 手绘航路 | 独立 UI | 嵌入 RoutePlannerPanel，独立图层 |
| 采纳/编辑/重评 | 手绘可编辑 | 前端草稿 | 显式 adapter + stale + evaluate-route |
| 认证/权限 | JWT/角色/published 项目 | 无 | 沿用 Polar-GIS |

## 3. 已迁移源码清单

- 契约：`backend/app/navigation/contracts/*`（坐标/方向/时间/单位/质量/证据/可行性；扩展
  `TimeMatchInfo`、`DataQuality`、`combine_quality`、`within_max_lag`）。
- 环境：`backend/app/navigation/environment/{models,manifest,time_manager,service}.py`，
  `environment/providers/{base,gebco,ice,carra2,topaz5,wam}.py`；`navigation/netcdf.py`。
- 船舶：`backend/app/navigation/vessel/{models,service,depth_safety}.py`；
  `resources/vessels/xuelong2.json`。
- 风险：`backend/app/navigation/risk/evaluator.py`；`resources/risk/weights_v1.json`。
- 规划：`backend/app/navigation/planner/{static_grid,grid,energy_model,dstar,dnsga3,
  environment_adapter,service,errors}.py`；`resources/grids/northeast_passage_25km_static.npz`。
- 任务：`backend/app/navigation/tasks/{service,processor,errors}.py`；
  `backend/app/models.py` 的 `PlanningRun/PlanningRoute`；迁移 `0005_navigation_planning.py`、
  `0006_navigation_run_title.py`。
- API：`backend/app/api/navigation_{environment,vessels,plans,risk}.py`。
- 前端：`stores/navigation.ts`、`api/navigation.ts`、`types/navigation.ts`、
  `composables/use{EnvironmentOverlays,PlanningRouteLayer,RiskGridLayer}.ts`、
  `components/{EnvironmentLayerPanel,EnvironmentTimeControl,EnvironmentValueTooltip,
  VesselProfilePanel,IntelligentPlanningPanel,NavigationTaskPanel,RouteComparisonPanel,
  RiskAnalysisPanel,PlanningResultPanel}.vue`、`utils/{mapEnvironment,routePlanning}.ts`。
- 测试：后端 66 个导航新增测试；前端 32 个新增测试/不变量；合成 fixture 生成器与 E2E 脚本。

## 4. 重构后的业务架构

```
Frontend（唯一 MapWorkspaceView）
  ├─ S-57 / 海冰 / 手绘航路（原样）
  ├─ 环境图层：水深 50 / 风 64 / 流 66 / 浪 68
  ├─ 风险格 70；候选航线 90
  └─ RoutePlannerPanel：手动绘制 | 智能规划（任务/船舶/对比/风险/结果）

Backend
  ├─ /api/v1/navigation/{environment,vessels,plans,risk}
  ├─ navigation.environment（Provider + 时间/质量 + 快照）
  ├─ navigation.vessel / risk
  ├─ navigation.planner（静态网格/EdgeTransitResult/D*/NSGA-III）
  ├─ navigation.tasks + models.planning_runs/routes
  └─ worker.PlanningRunProcessor（异步、取消、超时、心跳、租约）
        │
PostgreSQL/PostGIS · /data/navigation (ro) · /data/storage/navigation/plans (rw)
```

- 规划网格是 EPSG:3413 25 km 静态业务网格，不是海图瓦片/屏幕像素/OL zoom；距离、邻接、边权独立计算。
- 业务坐标 WGS84 `[lon,lat]`；渲染转 3413/3857；跨 180° 使用既有 unwrap/world-copy。
- 规划工作台不创建第二个地图实例、不新增第二 singleclick/pointermove。

## 5. 数据源和 Provider 清单

| 字段 | 目录/文件 | 变量/单位 | 状态 |
|---|---|---|---|
| 水深 | `bathymetry/GEBCO_*.nc` | elevation m（正上）→ depth m（正下） | 实现；本机无真实文件 |
| 海冰 | 现有 `ICE_DATA_ROOT` 或 `ice/*_YYYYMMDD.nc` | `sic_merged` % / `siconc` 0–1；`sithick` m | 实现；缺厚度只标该分量 missing |
| 风 | `wind/10m_wind_speed_YYYYMM.nc` + direction | `si10`/`wdir10`（兼容 u10/v10），FROM | 实现；本机无真实文件 |
| 海流 | `current/Copernicus_current_YYYYMMDD.nc` | `vxo/vyo` 原生 x/y → 地理 EN，m/s | 实现；TOPAZ 旋转修正 |
| 海浪 | `wave/Copernicus_wave_YYYYMMDD.nc` | `VHM0/VTPK/VMDR`，FROM | 实现；环形方向插值 |
| 静态网格 | 包内 NPZ | 110×240，25 km，version 3 | 随代码提交 488 KB |
| 船舶 | `xuelong2.json` | 7.85 m draft、UKC 2.0、15 MW、18 kn、PC3 | 随代码提交 |

`synthetic` 必须由数据根 `navigation_manifest.json` 标记；`real_only` 拒绝 synthetic 文件。无 manifest
时文件按 real 处理，issue/observation time 保持 unknown。

## 6. 已完成环境感知功能

- `GET /navigation/environment/sources|times`、`POST query|batch-query|field`、公开 bathy PNG 瓦片。
- 五字段故障隔离；单 Provider 失败不丢其他字段；缺测 `available=false + reason`，绝不填 0。
- 时间：requested/matched/valid/issue/observation；默认 latest-not-after、issue≤requested、按源
  max-lag（风 6h、冰/流/浪 24h）；研究模式才 nearest。
- 前端：水深色带、风/流/浪箭头（地理方位角构造，非投影平面 u/v）、逐层显隐/透明度/图例/
  source/matchedTime/quality、hover 原始值、EPSG:3413/3857、卸载/投影重建。
- 环境显示允许带标签的合成研究数据；规划默认 `real_only`。

## 7. 已完成船舶性能功能

- 雪龙2 静态资料：船长 122.5 m、船宽 22.32 m、设计吃水 7.85 m、排水量 13,996 t、2×7.5 MW
  （15 MW）、服务 12–15 kn、最大 18 kn、续航 20,000 nmi、PC3、连续破冰 1.5 m、来源链接。
- `required_depth = safety_draft + UKC = 7.85 + 2.0 = 9.85 m`；`SAFE/UNSAFE/UNKNOWN`，
  未知水深不返回 SAFE。
- UI 明确“未接入实时船位/航向/传感器数据”，不伪造实时值。
- 规划边评价注入船舶 max speed/power/reference speed；两船测试产生不同 speed/energy。

## 8. 已完成风险评估功能

- 分项：ice/depth/fog/wind/wave + combined + traversable + quality + sources + blockedReason。
- `legacy_v1`：精确复现 V3 权重 0.4/0.2/0.2/0.1/0.1 与公式（冰 load/1.35 阻断、depth+UKC、
  wind 11.7/5.0、wave 5.0/1.2、fog 确定性先验）。
- `real_v1`：禁止合成；fog=null；冰/深度缺失→combined/traversable=null；风/浪缺失按可用权重
  归一并标 prior missing；real_only 规划要求五字段齐全。
- 25 km 风险格绑定 planId 快照；API 支持字段/bbox/stride、单格完整环境值与质量/来源；
  前端风险格独立灰色 null 样式，点击格查看详情；区域 `risk_only` 任务无需先规划。

## 9. 已完成多目标规划功能

- D* Lite 三种子（risk/energy/time）→ 自研 NSGA-III；三目标 Risk/Energy/Time；Distance 仅统计。
- 统一 `EdgeTransitResult`：距离/航向/STW/SOG/静水/冰/风/浪功率/能耗/航时/可行性；
  功率上限、0.5 kn 搜索下界/1 kn 运行下界/18 kn 最大/12 kn 参考来自船舶配置。
- 异步 planning_runs worker；queued/running/completed/failed/cancelled；取消/超时/环境缺失/
  无路线/算法失败细分错误码；风险栅格即使无路线也保留。
- 持久化：`planning_runs`/`planning_routes` + Alembic 0005/0006（任务标题）；风险栅格 gzip 原子文件。
- `evaluate-route` 读取 run 风险快照，≤5 km 加密、逐格校验；候选/重评风险/能耗/航时一致
  （E2E 断言相等）。

## 10. 前端交互完成情况

- RoutePlannerPanel 手动/智能切换；原有手绘功能、信息浮窗、拖拽编辑、批量坐标不变。
- 智能工作台：任务/船舶/候选对比/风险/结果五页；地图选起终点；手绘航路端点；UTC；固定三目标；
  real_only/合成研究；种群/代数/seed。
- 候选航线独立图层：推荐/候选/选中样式，点击选中/fit。
- ECharts Pareto（x 能耗、y 风险、tooltip 航时），仅真实候选；表格对比/地图高亮/采纳。
- 采纳为可编辑草稿：`origin=adopted`、来源 plan/route、planningSnapshot；修改后 stale 提示，
  旧指标不作为当前值；“按当前航线重新评估”成功后更新，失败保留错误。
- 风险格地图点选、单格详情、区域评估；快照时间与当前环境时间不一致提示；合成横幅。
- 唯一 singleclick 优先级扩展；pickMode/riskInspect 与测量/手绘/识别/气象互斥；环境时间与冰情
  时间轴分离；原有 localStorage key v1 不变、payload v2 兼容。

## 11. 新增 API 文档

环境：
- `GET /api/v1/navigation/environment/sources`
- `GET /api/v1/navigation/environment/times?field=`
- `POST /api/v1/navigation/environment/query`
- `POST /api/v1/navigation/environment/batch-query`
- `POST /api/v1/navigation/environment/field`
- `GET /api/v1/navigation/environment/tiles/bathymetry/{crs}/{z}/{x}/{y}.png`
船舶：
- `GET /api/v1/navigation/vessels`、`GET /api/v1/navigation/vessels/{id}`
- `GET /api/v1/navigation/vessels/{id}/depth-safety?depth_m=`
规划：
- `POST /api/v1/navigation/plans`（202）
- `GET /api/v1/navigation/plans?project_id=&status=&page=&page_size=`
- `GET /api/v1/navigation/plans/{planId}`
- `GET /api/v1/navigation/plans/{planId}/routes`、`.../routes/{routeId}`
- `GET /api/v1/navigation/plans/{planId}/risk-grid?field=&bbox=&stride=`
- `GET /api/v1/navigation/plans/{planId}/risk-grid/{cellId}`
- `POST /api/v1/navigation/plans/{planId}/cancel`
- `POST /api/v1/navigation/plans/{planId}/evaluate-route`
- `POST /api/v1/navigation/risk/evaluate`

所有 JSON 接口沿用 JWT/项目可见性；bathy 瓦片与既有海冰瓦片同样公开只读。

## 12. 新增数据库迁移

`backend/migrations/versions/0005_navigation_planning.py`
- `planning_runs`（id/project_id/requested_by/title/vessel_id/mode/status/stage/progress/request_json/
  environment_snapshot_json/algorithm_version/data_policy/risk_model_version/error_code/
  error_message/result_summary_json/risk_grid_path/worker_id/cancel_requested/时间戳）
- `planning_routes`（run_id CASCADE、route_index、route_id、coordinates_json、风险分项、
  energy_mwh/time_hours/distance_km/quality/algorithm_version；唯一 run+index）
- 风险栅格不入 DB JSON，写 `PLANNER_RESULT_ROOT/{planId}.json.gz`（临时文件+原子 rename）。
- 迁移在 fresh SQLite 与“0004 后无 planning 表”场景升级通过；0004 增加幂等保护以支持 fresh DB。
- `0006_navigation_run_title.py` 为 `planning_runs` 增加可编辑 `title`；已在“0005 后无 title 列”的
  SQLite 数据库升级通过。

## 13. Docker 部署变化

- 五服务不变（postgres/geoserver/backend/worker/web），不新增 FastAPI 容器。
- backend/worker 增加 `${NAVIGATION_DATA_HOST_PATH:-../data/navigation}:/data/navigation:ro`；
- worker 增加 `${ICE_DATA_HOST_PATH:-../data/ice}:/data/ice:ro`（与 backend 对齐，规划可读海冰）；
- `NAVIGATION_ENABLED/DATA_ROOT/ICE_DATA_ROOT/ICE_BACKEND/DEFAULT_DATA_POLICY`、`PLANNER_*`
  环境变量；`PLANNER_RESULT_ROOT=/data/storage/navigation/plans`（共享存储）。
- `deploy/.env.example`、`backend/.env.example`、`data/navigation/*/README.md` 已更新；
  `.gitignore` 允许 README、忽略 NetCDF/JSON/NPZ 数据。
- `docker compose --env-file .env.example config` 通过；Nginx `^~ /api/` 已优先，无需改动。
- 镜像构建已尝试但受本机 Docker/网络与时间限制未完成（Dockerfile 未改变构建上下文）；需在有网络环境
  重跑 `docker compose build backend frontend`。不能宣称镜像构建已通过。

## 14. 后端测试结果

- `cd backend && pytest tests/ -q` → **280 passed, 0 failed**（基线 214 + 导航 66）。
- 覆盖：契约/单位/时间/方向/质量、Provider 缺文件/NoData/单位/时间/TOPAZ 旋转/WAM FROM/
  CARRA2 变量/合成 manifest、real_only 拒绝 synthetic、故障隔离、船舶/UKC/UNKNOWN、风险公式/
  缺测≠0/陆地/浅水/冰负载、静态网格、D*/NSGA/能耗/两船差异/电流/功率约束、规划 API/权限/取消/
  风险格/重评、Worker claim/异常隔离/心跳超时、迁移。
- `ruff check` 新增导航代码通过；既有 29 个历史 lint 未修改。

## 15. 前端测试结果

- `npm test` → **28 files / 386 tests passed**（基线 20/353 + 新增 8 files/33 tests）。
- `npm run typecheck` → 零错误；`npm run build` → 成功（仅有既有 chunk 大小提示）。
- 覆盖：双投影箭头/bbox、环境/船舶面板、路由 hash/stale、navigation store 采纳/选点/互斥、
  规划图层生命周期、面板契约、MapWorkspace 单 Map/单 handler/attach/dispose/projection、
  routes v1 payload 从旧 key 加载、v1→v2。
- Playwright（临时安装，未写入依赖）：登录→项目地图→智能规划→完成→候选→采纳→编辑→
  stale→重新评估→风险格；通过，截图在 `output/navigation-e2e-{result,stale,risk}.png`。

## 16. 真实数据端到端验证

- **未完成真实环境验证**：本机没有 GEBCO/neXtSIM/CARRA2/TOPAZ5/WAM 真实文件或 Copernicus/CDS
  凭证，`sample-data/` 只有冰情样例且无厚度。
- 已完成 **合成研究数据** E2E（`scripts/navigation/e2e_synthetic.py`）：
  - 环境 query（五字段）→ 船舶 → 创建 allow_synthetic_research 计划 → worker 真实 D*/NSGA-III
    → 3 条 Pareto 候选 → 风险格 15,731 单元 → evaluate-route；
  - 推荐航线与重评结果 **risk/energy/time 完全一致**；
  - `real_only` 负例：synthetic manifest 被拒绝，任务 failed `ENVIRONMENT_DATA_MISSING`；
  - `risk_only` 区域评估完成；
  - 全链 17.0 s，规划 worker 10.7 s（种群 8、代数 2、全 15,731 格）。
- 浏览器 UI E2E 同链通过（见 §15），但同样使用合成数据。

## 17. 现有 Polar-GIS 功能回归结果

- 后端 280 passed、前端 386 passed，typecheck/build 通过；既有测试全部保留。
- 自动化覆盖：认证/用户/项目、S-57 API/导入单元、Render Plan 纯函数、海冰 API/Service、
  AIS/气象 demo、要素查询测试（既有覆盖范围内）。
- 未在本环境运行真实 GeoServer/GWC/S-57 批量导入与浏览器手工 44 项清单（无 GeoServer 数据/服务）；
  **不能宣称这些真实服务回归已通过**。代码上未修改 S-57/GeoServer/GWC/海冰/手绘航路实现；
  唯一相关改动是 `0004` 迁移幂等保护（fresh DB）。
- Nginx `^~ /api/` 已保证新 PNG 瓦片不被静态正则拦截。

## 18. 性能与资源占用

- 合成全网格规划（15,731 单元、5 Provider、D* 三种子、NSGA 8×2）：worker **10.7 s**。
- API+worker+risk+evaluate 全链 **17.0 s**；风险格文件按 gzip 存盘，API 按 bbox/stride 裁剪，
  服务端自动 stride 限制在 `PLANNER_RISK_GRID_MAX_CELLS`。
- 环境矢量采样上限 600 点/视口，moveend 300ms 防抖，旧请求 abort；bathy 瓦片共享
  `TileRequestQueue`/`LRUTileCache` 并 generation abort。
- 规划 worker 串行（`PLANNER_MAX_CONCURRENT_JOBS=1`），超时 300 s；会延迟导入任务，已文档化。

## 19. 已知限制和未实现功能

- 无真实环境数据；真实环境规划、真实 Provider 下载/鉴权未验证；无 Copernicus/CDS 凭证。
- 雾无真实 Provider；real_v1 中雾风险为 null；历史频率未迁移（仅 legacy 合成先验）。
- 无项目成员 ACL；沿用 published project + 认证。
- 无实时船位/AIS 融合、自动操舵/推进、路线自动执行、ECDIS/雷达/XTE/ETA。
- Truth/Forecast/Observation/Belief、SparseGraph、EdgeEvaluator、RG-MPAO*、CF-JRS、RCOS
  仍为后续研究，未实现。
- Worker 串行；未来可拆独立 planner worker。
- 规划 UI 在 520px 抽屉内较紧凑；未改现有面板宽度常量。
- 真实 S-57/GeoServer/GWC/海冰数据服务回归未执行，仅代码/单元测试与合成链路。

## 20. `git diff --stat`

集成前 `728020b` 到最终批次（含本报告/文档/部署/脚本）：

```
122 files changed, 17846 insertions(+), 71 deletions(-)
```

（该统计包含批次 A-E 与最终报告本身；提交后可用 `git diff --stat 728020b` 复核。）

## 21. 推荐 Commit Message

```
feat(navigation): 集成 PolarOptionNav V3 环境感知/风险/多目标规划

- 环境 Provider/质量/时间/manifest + 环境图层
- 船舶/UKC/水深安全
- legacy_v1/real_v1 风险分项与风险栅格
- D* Lite + NSGA-III + 统一 EdgeTransitResult
- 异步 planning_runs worker + 持久化 + API
- 前端规划工作台/候选对比/风险格/采纳编辑/stale/重评
- 合成研究 E2E、回归、Docker 挂载与文档

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

## 22. 后续用户反馈修复（2026-10-30）

1. **合成信息不可见/不可修改**：新增 `syntheticOverrides` 契约（10 个字段、范围校验、仅
   `allow_synthetic_research`）；任务面板展示算法所需字段、“从起点读取当前环境值”与逐项编辑；
   覆盖应用到全规划区并标 `synthetic`/`research-override`；结果面板显示每字段 quality/source
   和本次覆盖值。
2. **进度卡在 10% / 历史任务不能编辑删除**：Provider 采样改为 1000 点分块，块间更新进度和检查
   取消；阶段推进为环境采样→多目标优化→结果保存（实测 0→2→12…65→95→100）。新增
   `planning_runs.title` 与 Alembic `0006`；`PATCH` 重命名、`DELETE` 删除终态任务（级联航线/
   风险文件）；历史列表提供重命名/删除按钮。
3. **选中任务蓝底浅字**：智能规划抽屉改为亮色主题（深色文字/浅色卡片/浅青选中行+左边框）；
   环境图层左侧暗色面板保持不变。
4. **合成值显示/随机值超时/历史时间/风险格可见性**：合成研究模式下环境查询对缺失字段执行与
   规划器一致的确定性 gap-fill，任务面板自动填入实际值（不再只显示“自动”）；D* 增加
   `PLANNER_MAX_SEARCH_EXPANSIONS=200000`，超限返回“没有可行航线”并保留风险栅格，避免随机/
   极端值导致规划超时；SQLite datetime 补 UTC，历史任务按浏览器本地时区显示；S-57
   `optional_other` zIndex 100→45，风险页打开已完成任务时自动加载 combined 风险格并显式可见。
5. 验证：后端 280 passed（新增 3 个）、前端 386 passed、typecheck/build/ruff 通过、迁移 0006
   通过；API E2E 与 Playwright UI smoke 复跑通过，截图更新。
