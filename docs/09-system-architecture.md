# 09 — 系统架构文档 (System Architecture)

> 极地海洋环境信息平台 (Polar-GIS) 系统架构说明
> 最后更新: 2026-11-16
>
> 本次按 `2026-10-10` 之后（会话 #27–#34）的实际代码与部署配置重新核对：
> 主架构章节（技术栈、目录结构、API、数据模型、前端结构、文件清单）已与当前
> `master` 同步；历史会话细节见第 8 章。会话 #34 新增 S-57 水深/危险物专题提取、
> 航道完整性诊断与东北航道覆盖对照。

---

## 1. 项目概述

Polar-GIS 是一个面向极地/高纬度海洋环境数据的 WebGIS 平台，支持 S-57 电子海图数据的导入、管理、发布与空间查询。

### 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python 3.12+ / FastAPI |
| ORM | SQLAlchemy 2.0 + Alembic |
| 数据库 | PostgreSQL 16 + PostGIS 3.4 |
| 空间数据引擎 | GDAL (ogrinfo, ogr2ogr, gdalinfo) |
| 地图服务器 | GeoServer 2.25.3 + GeoWebCache |
| 前端框架 | Vue 3 + Vite + TypeScript |
| UI 组件库 | Element Plus (中文) |
| 地图渲染 | OpenLayers 10.6.1 |
| 图表 | ECharts 6.0 |
| 状态管理 | Pinia 3.0 |
| 冰情/环境数据 | netCDF4 + numpy + Pillow + pyproj |
| 测地线计算 | GeographicLib (`geographiclib-geodesic` 2.2, WGS84/Karney) |
| 导航规划 | 内置 D* Lite + DNSGA-III（numpy 实现，无外部求解器） |
| 容器化 | Docker Compose (5 服务) |
| 反向代理 | Nginx |

---

## 2. 后端架构 (backend/)

### 2.1 目录结构与职责

```
backend/
├── app/
│   ├── main.py                 # FastAPI 应用入口 + lifespan（冰情预热、GWC 回填）
│   ├── models.py               # SQLAlchemy ORM 模型定义 (18 张表)
│   ├── schemas.py              # Pydantic 请求/响应模型（含航道快照/预览/专题/诊断）
│   ├── cli.py                  # 命令行工具 (创建管理员、S-57 源文件只读清单)
│   │
│   ├── api/                    # API 路由层（19 个模块）
│   │   ├── auth.py             # 认证: 登录/刷新/登出/当前用户
│   │   ├── users.py            # 管理员用户管理 CRUD
│   │   ├── projects.py         # 项目 CRUD + 发布 + 地图配置 + 渲染计划
│   │   ├── datasets.py         # 数据集管理 + S-57批次导入 + 上传
│   │   ├── layers.py           # 图层元数据 + 图例 + 空间查询 + 导出
│   │   ├── base_maps.py        # 底图 CRUD
│   │   ├── styles.py           # SLD 样式管理
│   │   ├── s57_basemaps.py     # 全球海图底图导入（管理员）
│   │   ├── s57_waterways.py    # S-57 航道专题：目录/搜索/预览/快照/诊断
│   │   ├── s57_thematics.py    # S-57 水深/危险物专题：目录/提取/成果/下载/样例
│   │   ├── ice.py              # 冰情 info/value/alignment/XYZ 瓦片
│   │   ├── navigation_environment.py # 导航环境源/查询/矢量场/水深瓦片
│   │   ├── navigation_vessels.py     # 船舶静态资料 + 吃水安全
│   │   ├── navigation_plans.py       # 智能规划任务/候选/风险格/重评
│   │   ├── navigation_risk.py        # 区域风险任务（risk_only）
│   │   ├── demo.py             # 演示数据 (AIS/天气)
│   │   ├── system.py           # 健康检查 + 审计日志 + GWC/样式刷新
│   │   └── deps.py             # 依赖注入 (认证/鉴权/项目边界)
│   │
│   ├── core/                   # 核心基础设施
│   │   ├── config.py           # Pydantic Settings (读取 .env)
│   │   ├── database.py         # SQLAlchemy 引擎 + 会话工厂
│   │   ├── security.py         # JWT 令牌 + Argon2 密码哈希
│   │   ├── errors.py           # AppError 异常 + 全局处理器
│   │   └── middleware.py       # 请求上下文中间件 (Request ID)
│   │
│   ├── services/               # 业务逻辑层（20 个模块）
│   │   ├── storage.py          # 本地文件存储 + 上传校验
│   │   ├── geoserver.py        # GeoServer REST API 客户端
│   │   ├── importer.py         # GDAL 导入处理器 (矢量/栅格/S-57)
│   │   ├── s57.py              # S-57 文件识别 + GDAL 检测
│   │   ├── s57_batch.py        # S-57 批次导入处理器
│   │   ├── s57_basemap.py      # 全球海图底图收集/发布
│   │   ├── s57_styles.py       # S-57 SLD 样式预设 (10种) + 比例尺规则
│   │   ├── s57_layer_catalog.py # S-57 图层分类事实来源（纯函数）
│   │   ├── s57_style_refresh.py # SLD 样式幂等刷新 (sldHash 对比 + 缓存截断)
│   │   ├── s57_waterway_catalog.py # 航道专题独立分类（不改动主目录）
│   │   ├── s57_waterways.py    # 项目当前版本跨图层航道查询/详情/分页 SQL
│   │   ├── s57_waterway_export.py # 航道成果键集导出 + GeoJSON/manifest + 公平预览
│   │   ├── s57_waterway_diagnostics.py # 航道 Cell/对象类/覆盖/东北航道区域诊断
│   │   ├── s57_project_layers.py # 通用项目 S-57 当前版本图层解析（不按类过滤）
│   │   ├── s57_thematic_catalog.py # 水深/危险物专题分类 + 实际导入类 + SOUNDG Z 诊断
│   │   ├── s57_thematic_export.py # 专题流式分卷导出 + manifest + ZIP + 样例
│   │   ├── ice.py              # NetCDF 冰情服务（info/value/PNG XYZ）
│   │   ├── map_render_plan.py  # 组合图层渲染计划纯函数 (build_bundles)
│   │   ├── gwc_backfill.py     # GWC EPSG:3413 瓦片缓存回填 (GridSet + 图层)
│   │   └── audit.py            # 审计日志写入
│   │
│   ├── navigation/             # PolarOptionNav V3 业务域（43 个 .py）
│   │   ├── contracts/          # 坐标/方向/时间/单位/质量/证据/状态
│   │   ├── environment/        # 环境源服务、时间匹配、manifest、合成数据
│   │   │   └── providers/      # GEBCO / CARRA2 / TOPAZ5 / WAM / ICE
│   │   ├── vessel/             # 雪龙2静态资料 + 吃水安全
│   │   ├── risk/               # legacy_v1 / real_v1 风险模型
│   │   ├── planner/            # 25km 网格、D* Lite、DNSGA-III、能耗模型
│   │   ├── tasks/              # 规划任务状态机 + worker 处理器
│   │   ├── resources/          # 网格 NPZ、权重 JSON、船舶 JSON
│   │   ├── schemas.py          # 导航请求/响应 Pydantic 模型
│   │   └── netcdf.py           # NetCDF 通用读取辅助
│   │
│   └── worker/                 # 后台工作进程
│       └── main.py             # 轮询：批次导入 → 单数据集导入 → 规划任务
│
├── migrations/                 # Alembic 数据库迁移
│   └── versions/               # 0001–0006（含 navigation_planning/run_title）
│
├── tests/                      # pytest 测试套件（32 个 test_*.py）
│
├── pyproject.toml              # 项目配置 + 依赖
├── alembic.ini                 # 迁移配置
└── Dockerfile                  # 容器构建
```

### 2.2 分层架构

```
请求 → API路由 (api/) → 业务逻辑 (services/) → 数据库 (models.py)
                                  ↕
                         外部服务 (GeoServer, GDAL)
```

- **API 层**: 处理 HTTP 请求/响应, 参数校验, 权限检查
- **Service 层**: 核心业务逻辑, 外部服务调用, 文件处理
- **Core 层**: 配置, 数据库连接, 安全, 日志
- **Worker 层**: 独立轮询进程，串行处理批次导入、单数据集导入与智能规划任务

### 2.3 API 路由总览

所有 API 端点均挂载在 `/api/v1` 前缀下。按 2026-11-16 代码清点为 **122 个路由装饰器**，主要模块如下：

| 模块 | 路由前缀 | 功能 |
|------|----------|------|
| 认证 | `/api/v1/auth` | 登录/刷新/登出/当前用户 |
| 用户管理 | `/api/v1/admin/users` | 用户 CRUD |
| 项目(公开) | `/api/v1/projects` | 已发布项目浏览、地图配置、批量解析、渲染计划 |
| 项目(管理) | `/api/v1/admin/projects` | 项目 CRUD + 发布/取消发布 |
| 数据集 | `/api/v1/admin/datasets` | 数据集 CRUD + 版本管理 + 清理 |
| 上传 | `/api/v1/admin/uploads` | 文件上传 |
| S-57批导入 | `/api/v1/admin/s57-import-batches` | 批量 S-57 导入/暂停/恢复/取消 |
| 导入任务 | `/api/v1/admin/import-jobs` | 导入任务监控 |
| S-57 底图 | `/api/v1/admin/s57-basemaps` | 全球海图底图 profiles/preflight/import/runs |
| 图层(公开) | `/api/v1/layers` | 元数据、图例、识别、搜索、导出 |
| 图层(管理) | `/api/v1/admin/layers` | 图层管理 |
| S-57 航道专题 | `/api/v1/projects/{projectId}/s57-waterways` | 目录/搜索/分页预览/快照保存下载/完整性诊断 |
| S-57 水深危险物专题 | `/api/v1/projects/{projectId}/s57-thematics` | 实际类目录/流式提取/成果 manifest/GeoJSON-ZIP/样例预览 |
| 冰情 | `/api/v1/ice` | info/value/alignment/XYZ 瓦片 |
| 导航环境 | `/api/v1/navigation/environment` | sources/times/query/batch-query/field/水深瓦片 |
| 导航船舶 | `/api/v1/navigation/vessels` | 雪龙2资料 + 吃水安全 |
| 智能规划 | `/api/v1/navigation/plans` | 创建/列表/详情/候选/风险格/取消/重评/重命名/删除 |
| 区域风险 | `/api/v1/navigation/risk` | `risk_only` 风险任务 |
| 底图(公开) | `/api/v1/base-maps` | 启用的底图列表 |
| 底图(管理) | `/api/v1/admin/base-maps` | 底图 CRUD |
| 样式 | `/api/v1/admin/styles` | SLD 样式管理 + S-57 样式刷新 |
| GWC 缓存 | `/api/v1/admin/gwc` | EPSG:3413 GridSet/缓存回填 |
| 演示 | `/api/v1/demo` | AIS 船舶 + 天气预报数据 |
| 系统 | `/api/v1/health`、`/api/v1/admin/audit-logs` | 存活/就绪检查 + 审计日志 |

### 2.4 数据导入架构 (S-57 Batch Import)

**优化后流程** (2026-07-23):

```
前端上传 → API保存文件 → Worker轮询领取 →
  └─ 扫描分组 (串行, 快)
  └─ 并行Cell处理 (ThreadPoolExecutor, 默认8 workers):
      └─ 每个Cell:
          1. 单次ogr2ogr (临时schema, LAUNDER=YES)  ← 优化: 从N次子进程→1次; 统一小写列名
          2. ALTER TABLE SET SCHEMA + RENAME
          3. GeoServer批量发布 (预设BBox) ← 优化: 跳过全表扫描
```

**关键优化**:
- **单次ogr2ogr**: 使用临时 PostgreSQL schema (`_imp_{id}`) 作为中间层，一次 ogr2ogr 导入全部图层，再逐个 ALTER TABLE 移至 geo schema
- **并行Cell**: `concurrent.futures.ThreadPoolExecutor`，每个Cell独立DB session + 独立ogr2ogr子进程 + 独立GeoServer发布
- **GeoServer BBox**: 发布时预设 `nativeBoundingBox` 避免GeoServer全表扫描计算
- **暂停/取消**: Worker在处理每个Cell前检查batch状态，支持优雅暂停（完成当前Cell后停止）和立即取消
- **LAUNDER=YES** (2026-07-23): ogr2ogr导入时强制小写列名，`allowed_fields`同步小写化，配合 `column_reference()` 保留原始大小写实现新旧数据兼容

### 2.4.1 图层属性查询架构

图层属性查询不通过GeoServer WFS，而是直接查询本地PostgreSQL数据库：

```
前端 → POST /api/v1/layers/{id}/features/search → 直接SQL查询 geo schema → 返回分页结果
```

- **字段白名单**: 查询字段必须是 `allowed_fields` 中的字段名（导入时由ogrinfo检测并存储）
- **SQL注入防护**: `field_pattern` 正则校验 (`^[A-Za-z_][A-Za-z0-9_]*$`) + 白名单检查 + 双引号引用
- **大小写处理** (2026-07-23): `column_reference()` 保留字段名原始大小写，与PostgreSQL实际列名一致；新导入统一使用LAUNDER=YES小写列名

### 2.4.2 S-57 图层分类目录

`app/services/s57_layer_catalog.py` 是后端唯一的 S-57 图层分类事实来源，提供不可变的 `S57LayerRule` 和纯函数分类接口，不依赖数据库、FastAPI、GDAL 或 GeoServer。

- **固定加载档案**: `core_chart`、`navigation_recommended`、`optional_thematic`、`metadata_quality`、`non_spatial`、`optional_other`
- **单向派生**: 核心海图完整展示规则表是成员与展示元数据的单一规范来源，公开 `CORE_CHART` 不可变集合从规则表键派生，避免双处维护
- **稳定展示分类**: 水深、岸线、危险物、助航、航路、限制/港区、专题、质量元数据和非空间对象分别使用固定分类值与优先级
- **保守几何判断**: 仅空值及明确的无几何标记视为无效；`GeometryCollection` 等合法 GDAL 几何类型保持可渲染
- **推荐语义**: 仅核心海图/航行推荐对象且已有样式映射时标记 `recommended=True`
- **懒加载兼容**: 所有规则均保持 `default_visible=False`，分类元数据不改变现有默认加载行为

### 2.4.3 S-57 图层批量解析 API

`POST /api/v1/projects/{projectId}/map-layers/resolve` 是项目级 S-57 图层批量解析端点，用于地图工作台的批量加载功能。

- **输入**：datasetIds（1-100 项）、profile（core_chart / navigation_recommended / all_spatial）、includeMetadata 标志。
- **输出**：按数据集分组的图层列表，每层包含分类信息、加载能力和跳过原因；汇总统计。
- **复用**：`classify_s57_layer()` 分类函数、`preset_for_object_class()` 样式映射、`s57_object_class()` 和 `style_mapped_for_layer()` 兼容旧数据无 s57 元数据的情况。
- **权限**：仅在当前已发布项目中校验，使用现有 project_or_404 访问边界。
- **不修改**：不改变 `GET /projects/{projectId}/map-datasets/{datasetId}/layers` 的懒加载语义。

### 2.4.4 S-57 导入分类元数据

导入流程通过 `merge_s57_layer_metadata()` 将 `classify_s57_layer()` 结果并入 `layers.metadata_json["s57"]`。旧数据无此元数据时，resolve API 动态回退分类，不强制数据库迁移。

### 2.4.5 S-57 更新链校验增强

`validate_s57_chain()` 现区分基础文件缺失（`S57_BASE_MISSING`）与更新间断（`S57_UPDATE_GAP`），并通过 `S57ChainValidationError` 传递 `missingUpdates` 列表。`s57_error_details()` 从错误消息提取结构化的 `missingUpdates`，供批次详情 API 的 `details` 字段使用。

### 2.5 认证与鉴权

- **JWT**: HS256 签名, `access_token` (30分钟) + `refresh_token` (7天, HTTP-only Cookie)
- **密码哈希**: Argon2 (argon2-cffi)
- **角色**: `system_admin` (全权限) / `user` (受限)
- **账户锁定**: 5次失败 → 15分钟锁定
- **审计**: 所有操作记录至 `audit_logs` 表

### 2.6 数据模型 (18 张表)

| 表名 | 用途 |
|------|------|
| `users` | 用户账户 |
| `refresh_tokens` | JWT 刷新令牌 |
| `projects` | 地图项目 |
| `project_layers` | 项目-图层关联 |
| `uploads` | 文件上传记录 |
| `datasets` | 数据集 |
| `dataset_versions` | 数据集版本链 |
| `file_assets` | 文件资产 |
| `import_jobs` | 异步导入任务 |
| `s57_import_batches` | S-57 批次导入 |
| `s57_import_batch_files` | 批次文件 |
| `s57_import_batch_items` | 批次单元格 |
| `styles` | 地图样式 |
| `layers` | 发布图层 |
| `base_maps` | 底图配置 |
| `audit_logs` | 审计日志 |
| `planning_runs` | 智能规划任务（状态/进度/船舶/数据策略/合成覆盖/标题） |
| `planning_routes` | 候选航线（坐标 JSON/指标/风险快照引用） |

> 迁移脚本：`0001_initial`、`0002_s57_import_batches`、`0003_project_code_active_unique`、
> `0004_s57_batch_purpose`、`0005_navigation_planning`、`0006_navigation_run_title`。
> 风险栅格 gzip 与航道快照 GeoJSON 不存表，写入共享存储卷
> （`<STORAGE_ROOT>/navigation/plans|waterways`）。

### 2.7 核心业务流程

1. **数据上传 → 导入 → 发布**:
   上传文件 → GDAL 分析 → ogr2ogr 导入 PostgreSQL (`geo` schema) → GeoServer 发布图层
2. **S-57 更新链**:
   `.000` (基座) → `.001`, `.002`, ... (顺序更新) → 版本链管理 → 支持回滚
3. **项目发布**:
   创建项目 → 关联图层+样式 → 配置可见性/透明度/缩放范围 → 发布

---

## 3. 前端架构 (frontend/)

### 3.1 目录结构与职责

```
frontend/
├── index.html                  # HTML 入口
├── package.json                # 依赖 + 脚本
├── vite.config.ts              # Vite 构建配置 + 代理
├── tsconfig.json               # TypeScript 配置
├── Dockerfile                  # 多阶段构建 (node → nginx)
│
└── src/
    ├── main.ts                 # 应用入口 (Vue + Pinia + Router + Element Plus)
    ├── App.vue                 # 根组件 (<RouterView />)
    ├── styles.css              # 全局样式（map-/ice-/env-/waterway-/planning- 前缀）
    │
    ├── api/ (5)                # client / projects / ice / navigation / s57Waterways
    │
    ├── components/ (17 .vue)
    │   ├── 地图与航路            # RoutePlannerPanel / RouteInfoFlyout
    │   ├── 航道与图例            # S57WaterwayPanel / S57LayerLegend
    │   ├── 冰情                  # IceLayerPanel / IceTimeline / IceValueTooltip
    │   ├── 环境叠加              # EnvironmentLayerPanel / EnvironmentTimeControl / EnvironmentValueTooltip
    │   ├── 智能规划              # IntelligentPlanningPanel / NavigationTaskPanel /
    │   │                         # PlanningResultPanel / RouteComparisonPanel /
    │   │                         # RiskAnalysisPanel / VesselProfilePanel
    │   └── WeatherChart          # 演示气象图表
    │
    ├── composables/ (6)
    │   ├── useRouteDrawing.ts    # 手绘航路 Draw/Modify/重建/定位
    │   ├── useIceOverlay.ts      # 冰情 TileLayer 生命周期 + hover
    │   ├── useEnvironmentOverlays.ts # 水深/风/流/浪叠加与矢量场
    │   ├── useS57Waterways.ts    # 航道目录/搜索/预览/快照
    │   ├── usePlanningRouteLayer.ts # 规划候选航线矢量层
    │   └── useRiskGridLayer.ts   # 风险格矢量层 + 点选
    │
    ├── layouts/
    │   └── AppLayout.vue         # 应用外壳 (侧边栏 + 顶栏 + 内容区)
    │
    ├── router/
    │   └── index.ts              # 路由配置 + 导航守卫
    │
    ├── stores/ (4)
    │   ├── auth.ts               # 认证状态 (登录/引导/登出)
    │   ├── projects.ts           # 项目列表状态
    │   ├── routes.ts             # 航路草稿 (WGS84 真值 + localStorage)
    │   └── navigation.ts         # 规划任务/候选/风险格/采纳
    │
    ├── types/ (4)                # index / navigation / routePlanning / s57Waterways
    │
    ├── utils/ (21)               # 纯函数与基础设施
    │   ├── mapExtent / mapRoute / mapMeasure / mapIce / mapEnvironment
    │   ├── mapLayerBatch / mapRenderScheduler / mapRenderBundles / mapTileMerger
    │   ├── mapS57Waterway / routePlanning / geodesicDistance / s57LayerLegend
    │   ├── s57ObjectNames / basemaps / basemapLayers / basemapHealth
    │   └── tileLoader / tileCache / tileRequestQueue / tileDiagnostics
    │
    └── views/ (11)
        ├── LoginView.vue         # 登录页
        ├── MapWorkspaceView.vue  # 全屏地图工作区
        ├── ProjectsView.vue      # 项目门户
        │
        └── admin/ (8)            # 仪表盘/用户/项目/数据目录/批量导入/
                                  # 数据清理/导入任务/图层与系统
```

### 3.2 技术架构

```
Vue 3 (Composition API + <script setup>)
├── Pinia (状态管理)
│   ├── useAuthStore     → 登录/引导/登出 + 令牌管理
│   ├── useProjectsStore → 项目列表分页加载
│   ├── useRoutesStore   → 航路草稿 (WGS84 真值 + localStorage 持久化)
│   └── useNavigationStore → 规划任务/候选/风险格/采纳与重评
├── Vue Router (路由 + 导航守卫)
│   ├── beforeEach: 认证检查 + 角色检查
│   └── Lazy loading: 所有路由组件动态 import
├── Axios (API 客户端)
│   ├── 自动 camelCase ↔ snake_case 转换
│   ├── 自动 Bearer Token 附加
│   └── 401 自动刷新 (去重并发刷新)
├── Element Plus (UI 组件库, 中文语言包)
├── OpenLayers (地图)
│   ├── EPSG:3857 (Web Mercator)
│   ├── EPSG:3413 (北极投影)
│   └── TileWMS / WMTS / XYZ 图层
└── ECharts (图表)
```

### 3.3 路由表

| 路径 | 页面 | 权限 |
|------|------|------|
| `/login` | 登录 | 公开 |
| `/map/:id` | 地图工作区 | 认证用户 |
| `/projects` | 项目门户 (默认页) | 认证用户 |
| `/admin` | 管理仪表盘 | 管理员 |
| `/admin/users` | 用户管理 | 管理员 |
| `/admin/projects` | 项目管理 | 管理员 |
| `/admin/data` | 数据目录 | 管理员 |
| `/admin/batch-imports` | S-57 批量导入 | 管理员 |
| `/admin/data-cleanup` | 数据清理 | 管理员 |
| `/admin/jobs` | 导入任务 | 管理员 |
| `/admin/system` | 系统配置 | 管理员 |

---

## 4. 部署架构

### 4.1 Docker Compose 服务

```
                    ┌──────────────┐
                    │   Nginx      │  ← web (frontend + reverse proxy)
                    │   :${PUBLIC_PORT} │
                    └──────┬───────┘
                           │ /api → backend
                           │ /geoserver → geoserver
              ┌────────────┼────────────┐
              ▼            ▼            ▼
    ┌─────────────┐ ┌──────────┐ ┌───────────┐
    │  backend    │ │geoserver │ │  postgres │
    │  :8000      │ │ :8080    │ │  :5432    │
    │  (internal) │ │(internal)│ │ (internal)│
    └──────┬──────┘ └──────────┘ └───────────┘
           │
    ┌──────┴──────┐
    │   worker    │  ← 后台导入处理
    │  (internal) │
    └─────────────┘
```

- **postgres**: postgis/postgis:16-3.4；`shm_size: 1gb`（航道大几何并发查询避免 `/dev/shm` 64MB 报 DiskFull）
- **geoserver**: docker.osgeo.org/geoserver:2.25.3；JVM 2–4GB + G1GC
- **backend**: FastAPI + Uvicorn（`backend/Dockerfile`），启动时 `alembic upgrade head`
- **worker**: 同 backend 镜像，运行 `app.worker.main`；串行处理批次导入、单数据集导入、智能规划任务
- **web**: Nginx 提供前端静态文件 + 反向代理（`^~ /api/` 优先于静态图片正则）

### 4.2 网络
- `public`: web 对外暴露（postgres/geoserver 端口也映射到宿主机便于调试）
- `internal`: 内部服务间通信（backend/worker 不对外）

### 4.3 卷与数据挂载
- `postgres-data`: 数据库持久化
- `geoserver-data`: GeoServer 数据
- `shared-storage`: 共享文件存储，backend/worker 读写；挂载到 `/data/storage`
  - `<STORAGE_ROOT>/navigation/plans`: 规划风险栅格 gzip
  - `<STORAGE_ROOT>/navigation/waterways`: 航道快照 `waterways.geojson` + `manifest.json`
- `${ICE_DATA_HOST_PATH:-../data/ice}:/data/ice:ro`: 冰情 NetCDF（backend/worker）
- `${NAVIGATION_DATA_HOST_PATH:-../data/navigation}:/data/navigation:ro`: GEBCO/CARRA2/TOPAZ5/WAM/冰情研究数据（backend/worker）
- `../data/s57-basemaps:/data/s57-basemaps:ro`: 全球海图底图源文件

### 4.4 关键运行参数

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ICE_ENABLED` | `true` | 冰情 API/瓦片总开关（404 `ICE_DISABLED`） |
| `ICE_DATA_ROOT` | `/data/ice` | 冰情 NetCDF 目录 |
| `ICE_MAX_CONCURRENT_GRID_LOADS` | `2` | 不同日期冷网格并发装载上限 |
| `NAVIGATION_ENABLED` | `true` | 导航环境/规划总开关 |
| `NAVIGATION_DATA_ROOT` | `/data/navigation` | 环境数据根目录 + `navigation_manifest.json` |
| `NAVIGATION_DEFAULT_DATA_POLICY` | `real_only` | 默认数据策略（`real_only` / 合成研究） |
| `PLANNER_RESULT_ROOT` | `/data/storage/navigation/plans` | 风险栅格持久目录 |
| `S57_WATERWAY_SNAPSHOT_ROOT` | `/data/storage/navigation/waterways` | 航道成果目录 |
| `S57_WATERWAY_SNAPSHOT_MAX_FEATURES` | `20000` | 单次保存最大要素数 |
| `S57_WATERWAY_PREVIEW_MAX_FEATURES` | `2000` | 地图专题总览单次上限 |
| `PLANNER_MAX_CELLS` | `20000` | 规划网格单元上限 |
| `PLANNER_MAX_CANDIDATES` | `20` | 候选航线上限 |
| `PLANNER_TIMEOUT_SECONDS` | `300` | 单任务超时 |
| `PLANNER_MAX_CONCURRENT_JOBS` | `1` | worker 并发规划数（串行） |

---

## 5. 坐标参考系统 (CRS)

| EPSG | 名称 | 用途 |
|------|------|------|
| 4326 | WGS84 | 全球经纬度 |
| 3857 | Web Mercator | 标准 Web 地图 |
| 3413 | Arctic Stereographic | 北极极地投影 |

---

## 5.5 智能渲染调度器 (会话 #11 新增)

在 `frontend/src/utils/mapRenderScheduler.ts` 中实现了纯函数渲染调度器，解决批量加载海图后浏览器性能问题。

### 状态模型
```
selectedLayerIds → 用户选择 (开关控制)
    ↓
attachedLayerIds → OpenLayers TileLayer 已创建
    ↓
activeLayerIds → 可见并允许请求瓦片
warmingLayerIds → 等待首块瓦片 (≤10 并发)
suspendedLayerIds → 视口外/比例尺外/预算不足 暂时休眠
manuallyForcedLayerIds → 用户强制显示 (免疫智能休眠)
failedLayerIds → 加载失败
```

### RenderPlan 算法
`buildRenderPlan(input) → RenderPlan` 为纯函数，接收当前地图状态快照，返回五类操作：
- **attach[]**: 创建 OpenLayers TileLayer (进入 warming)
- **activate[]**: setVisible(true) 恢复休眠图层
- **suspend[]**: setVisible(false) 休眠 (原因: 视口外/比例尺外/预算)
- **detach[]**: layer.dispose() LRU 卸载
- **remainActive[]**: 无需变更

### 三种渲染模式
| 模式 | 行为 | 用途 |
|------|------|------|
| `standard` | 完全保持原有行为，所有选中图层创建独立 WMS | 向后兼容、强制显示全部 |
| `smart` | 视口裁剪 + 比例尺过滤 + warming 预算 + LRU | 批量加载默认推荐 |
| `overview` | 仅显示全球概览 WMTS，不创建业务 WMS | 大范围浏览、快速定位 |

### 比例尺规则单源
`DEFAULT_SCALE_HINTS` (前端) 与 `_SCALE_RULES` (后端 s57_layer_catalog.py) 保持同步：
- SOUNDG: minScale=25,000 (仅大比例尺)
- LIGHTS/BOY*/BCN*/TOPMAR: minScale=50,000
- WRECKS/OBSTRN/UWTROC: minScale=100,000
- DEPCNT: minScale=500,000
- COALNE/LNDARE/DEPARE/SEAARE: 始终可见

### 可配置常量
```
SMART_MAX_ACTIVE_WMS_LAYERS = 30  (活动图层预算)
SMART_MAX_WARMING_LAYERS = 10     (同时 warming 上限)
SMART_MAX_ATTACHED_WMS_LAYERS = 60 (内存中对象上限)
SMART_SUSPEND_EVICT_DELAY_MS = 30000 (LRU 驱逐延迟)
SMART_RECONCILE_DEBOUNCE_MS = 150  (moveend 防抖)
```

## 5.6 前端显示性能优化 (会话 #12)

批导入海图图层后的页面加载缓慢和地图卡顿问题，在保留现有的智能调度器架构基础上进行了以下优化:

### 前端优化
- **瓦片加载重试**: TileWMS 源增加 tileLoadFunction，使用 fetch + 指数退避对 429/502/503/504 及网络错误重试最多 2 次
- **动态 zIndex**: 按 S-57 对象类分层 (填充层10→等深线20→岸线25→危险物30→水深点35→助航标志40)，解决随机绘制闪烁
- **响应式优化**: 7 个 Set 状态从 ref() 改为 shallowRef()，消除对 Set 内每个元素的深层追踪
- **调度器预算提升**: warming 3→10 / active 20→30 / attached 40→60，提升批量加载吞吐量

### 基础设施优化
- **HTTP/2**: nginx listen 80 http2，突破浏览器每源 6 连接限制，实现瓦片请求多路复用
- **WMS 瓦片缓存**: nginx proxy_cache 缓存 GeoServer 瓦片 1 小时，缓存命中时 0ms 延迟
- **静态资源缓存**: hashed 资源 Cache-Control: public, immutable (1year)
- **GeoServer JVM**: INITIAL_MEMORY=2G MAXIMUM_MEMORY=4G + G1GC 减少 GC 停顿

### 后端优化
- **PostGIS 空间索引**: 导入后自动 CREATE INDEX USING GIST (geom) + ANALYZE，GeoServer WMS 从 Seq Scan 转为 Index Scan
- **GWC 自动启用**: 发布后自动调用 ensure_gwc_layer() 为 S-57 空间图层开启瓦片缓存

## 5.7 组合图层渲染通道 Phase 1 (会话 #13)

在智能模式下将 20~30 个独立 TileWMS 压缩为约 3~6 个语义组合 TileWMS，通过逗号分隔的 LAYERS/STYLES 参数实现多图层单次 WMS 请求。

### 两层模型

| 层 | 职责 |
|------|------|
| **逻辑图层** (Logical Layer) | layerId, datasetId, objectClass, 单层开关, 图层顺序, 图例, 属性查询, 导出, 选择状态 |
| **渲染图层** (Render Layer) | 由多个同级逻辑图层组成渲染 Bundle，对应一个 TileWMS，负责视觉显示 |

### 默认语义分组 (5 Buckets)

| Bucket | zIndex | 包含 S-57 对象类 | 显示名称 |
|--------|--------|-------------------|----------|
| `area_fill` | 10 | DEPARE, SEAARE, LNDARE, ICEARE, UNSARE, CTNARE, RESARE, HRBARE | 面域填充 |
| `line_structure` | 20 | COALNE, DEPCNT, NAVLNE, FAIRWY, TSSBND, TSSLPT, SLCONS 等 | 线状结构 |
| `hazard_detail` | 30 | WRECKS, OBSTRN, UWTROC, SOUNDG | 危险物与水深 |
| `navigation_aid` | 50 | LIGHTS, FOGSIG, BOY*, BCN*, TOPMAR, RTPBCN | 助航标志 |
| `optional_other` | 100 | 未归入以上类别的可选图层 | 其他可选 |

分组规则从 `backend/app/services/s57_layer_catalog.py` 的 `get_render_bucket()` 派生，为分类事实的单一来源。

### 后端服务 (已实现)

- `backend/app/services/map_render_plan.py`: 纯函数 `build_bundles()` 接收 LayerRenderInput 列表，返回 (list[BundleConfig], list[StandaloneConfig])
- `backend/app/api/projects.py`: POST `/api/v1/projects/{id}/map-render/plan` API 端点
- `backend/tests/test_map_render_plan.py`: 32 纯函数测试
- `backend/tests/test_projects.py`: 6 API 集成测试

### 前端运行时

- `frontend/src/utils/mapRenderBundles.ts`: Bundle 生命周期管理 (createBundleTileSource, attachBundle, detachBundle, replaceBundle, disposeAllBundles)
- `frontend/src/utils/mapRenderScheduler.ts`: BundleRenderPlan 接口, ENABLE_RENDER_BUNDLES Feature Flag
- `frontend/src/views/MapWorkspaceView.vue`: executeBundlePlan() 执行路径, 智能模式自动调用 fetchRenderPlan()

### Standalone 拆离条件

以下情况图层不能合并，必须作为 standaloneLayer:
1. 用户修改了单层透明度 (opacity ≠ 1.0)
2. renderStandalone = true
3. 非空间图层 (已排除)

### Feature Flag

`VITE_ENABLE_RENDER_BUNDLES` (默认 true)。设为 false 时 smart 模式回退到独立 WMS 调度器。

## 5.8 GWC EPSG:3413 瓦片缓存链路 (会话 #18)

批量加载 160 层海图后平移空白、缩放卡顿的根治方案：接通 GeoWebCache 全链路，修复视口裁剪、Bundle 生命周期、SLD 比例尺与发布 bbox 四类缺陷。

### 瓦片请求数据流

```
前端 TileWMS
 ├─ cacheable 图层 (renderTransport=gwc_wms)
 │    → /geoserver/gwc/service/wms?VERSION=1.1.1&SRS=EPSG:3413&TILED=true&LAYERS=...
 │        ├─ GWC 命中 → 直接返回缓存瓦片 (X-GWC-Cache: HIT)
 │        └─ 未命中 → WMS 渲染 → 写入缓存 (X-GWC-Cache: MISS)
 ├─ 组合 Bundle (逗号分隔多图层)
 │    → /geoserver/wms 普通 WMS   (GWC WMS-C 不支持逗号图层，决策保留)
 └─ 非 cacheable 图层 (optional_other 等)
      → /geoserver/wms 普通 WMS
```

前端侧开关：`ENABLE_GWC_TILES`（`VITE_ENABLE_GWC_TILES=false` 回退普通 WMS）。cacheable 判定由后端 `_gwc_transport_for_layer()` 统一负责（`loadable` 且 `load_profile ∈ {core_chart, navigation_recommended}` → `cacheable=true / render_transport=gwc_wms / tile_service_url=/geoserver/gwc/service/wms`），经 `MapLayerConfig` 三字段透传前端。

> **⚠ 命名契约（会话 #18.2）**：GWC WMS facade 对图层/样式名**精确匹配**注册表（键为全限定名），裸名请求返回 `400 Unknown layer / Style invalid`；GeoServer 自带 WMS 则经默认命名空间解析裸名。因此所有 API 输出（`MapLayerConfig.serviceLayerName/styleName`、`BulkResolvedLayer.geoserverLayerName/styleName`、render-plan 的 `LayerRenderInput`）必须为 `workspace:name` 全限定名（DB 仅存裸名，workspace 取 `layer.geoserver_workspace` 或默认 `polar_gis`）。

### GeoServer / GWC (后端)

- **GridSet 创建**：发布 S-57 空间图层时 `ensure_gridset("EPSG:3413", "EPSG:3413", [-4194304, -4194304, 4194304, 4194304])` 幂等 PUT，extent 与 OpenLayers 默认 EPSG:3413 瓦片网格对齐；图层 GWC 启用覆盖三 gridset：`EPSG:3857` / `EPSG:4326` / `EPSG:3413`（mime 仅 image/png）
- **已有图层回填**：`backend/app/services/gwc_backfill.py` — `ensure_gwc_3413_backfill()` 查询全部 AVAILABLE 且未软删的 S-57 图层，GET-then-PUT 幂等补齐（GWC 中缺失或缺 3413 gridset 才 PUT）；lifespan 后台 daemon 线程自动执行（`GWC_3413_BACKFILL=0` 禁用），`POST /api/v1/admin/gwc/backfill` 管理员端点可手动触发
- **真实 bbox 发布**：`publish_feature_type` / `publish_feature_types_batch` 支持 `bounds` 参数（EPSG:4326 `[minx,miny,maxx,maxy]`），importer 按层从 `s57.extent` 传递；`_resolve_bounds` 对非法输入（长度≠4 / 非数值 / nan / inf / minx≥maxx 等）回退全球 -180..180 并仅告警
- **SLD 比例尺规则**：`render_sld(min_scale_denominator, max_scale_denominator)` 在 Rule 内、Symbolizer 之前输出 `<sld:Min/MaxScaleDenominator>`；导入时持久化 `s57.minScaleDenominator`。生产同步路径（`sync_s57_layer_style`）以 **`max_scale_denominator`** 输出——"SOUNDG 放大到至少 1:25000 才渲染"（SD ≤ 25000）对应 SLD `MaxScaleDenominator`；误用 `MinScaleDenominator` 会反向（缩远才渲染）
- **样式幂等刷新**：`backend/app/services/s57_style_refresh.py` — `sync_s57_layer_style()` 以 SLD sha256（`s57.sldHash`）对比判断，仅变化时 publish_style + set_default_style + `truncate_layer_cache`（best-effort，404 容忍）；`POST /api/v1/admin/styles/refresh-s57` 批量补齐已有图层

### 数据落库 (元数据)

导入时 `merge_s57_layer_metadata()` 向 `layers.metadata_json["s57"]` 写入：`extent`（ogrinfo `geometryFields[0].extent`，4 数值校验，NaN/Inf/缺失 → null）与 `minScaleDenominator`。前端 `isLayerInViewport` 消费 `extent` 实现视口裁剪，调度器据此休眠视口外图层。

### Bundle 生命周期修复

调度器 bundle 分支（`RenderPlanInput.attachedBundleIds`）真实四操作：视口内未挂载 → `attachBundles`；已挂载且视口内 → `activateBundles`；视口外 → `suspendBundles`；已挂载但不在新计划 → `detachBundles`（原恒空 TODO 导致图层泄漏）。`executeBundlePlan` activate 守卫仅激活 `status==='active'` 的 bundle（warming/failed/replacing 不强制显示）。renderMode 切换双向修复：切 standard 补 attach、切 smart/overview 清 per-layer 残留。

## 5.9 WMS 瓦片请求合并与缓存基础设施 (会话 #19)

标准模式批量加载 100+ 图层后，每次平移产生 `N×16` 并发 WMS fetch() 请求，远超浏览器连接池（HTTP/1.1 6-10/域名）。本节描述三层防线：

### 防线 1: 瓦片 LRU 缓存 (`tileCache.ts`)

- **位置**: `frontend/src/utils/tileCache.ts` — `LRUTileCache` 类
- **数据结构**: `Map<string, Blob>` (URL → 瓦片图片)，利用 Map 插入顺序实现 O(1) LRU
- **默认容量**: 2048 entries / 50MB
- **集成点**: `createRetryTileLoadFunction()` — fetch 前 `cache.get(src)` 命中则直接 `URL.createObjectURL` 赋值 img.src
- **失效时机**: 地图销毁 (`onBeforeUnmount`)、投影切换 (`switchProjection`) 时 `clear()`
- **常量**: `TILE_CACHE_MAX_ENTRIES`、`TILE_CACHE_MAX_BYTES` (定义于 `mapLayerBatch.ts`)

### 防线 2: 并发请求队列 (`tileRequestQueue.ts`)

- **位置**: `frontend/src/utils/tileRequestQueue.ts` — `TileRequestQueue` 类
- **默认参数**: maxConcurrent=16, maxQueue=512 (FIFO)
- **返回值**: 原始 `Response`（不消费 body），由调用方自行 `response.blob()` + 状态码判断 + 重试
- **AbortSignal 支持**: 排队中请求可被移除；进行中由 fetch signal 自然中断
- **重试解耦**: 队列只控并发，不重试——retry 逻辑完全由 `createRetryTileLoadFunction` 的 `tryLoad` `setTimeout` 递归处理
- **集成点**: `createRetryTileLoadFunction()` 中 `fetch()` 替换为 `tileRequestQueue.fetch(src, signal)`
- **常量**: `TILE_MAX_CONCURRENT_FETCH`、`TILE_MAX_QUEUED_FETCH` (定义于 `mapLayerBatch.ts`)

### 防线 3: TileWMS 源合并 (`mapTileMerger.ts`)

标准模式逐层 `attachWmsLayer()` 为每个图层创建独立 TileWMS 源。合并逻辑将可共享端点的图层归为一组，每组一个 TileWMS 源（逗号分隔 LAYERS + 逐层 STYLES），直接减少源数量 → 请求数量。

- **位置**: `frontend/src/utils/mapTileMerger.ts`
- **核心类型**:
  - `MergeGroupKey`: `{ serviceUrl, renderTransport }` — 合并键（会话 #20 起放宽为仅端点+协议，跨样式/类别合并）
  - `MergeGroup`: `{ key, layerIds[], layerNames[], styles[], minZoom, maxZoom, zIndex, regularServiceUrl }` — 合并组
- **核心函数**:
  - `computeMergeKey(layer)` → 从 `MergeableLayer` 计算键（GWC 图层使用 `tileServiceUrl`，受 `ENABLE_GWC_TILES` 门控）
  - `toMergeableLayer(config)` → 将 `MapLayerConfig` 适配为 `MergeableLayer`（buildMap/投影切换路径复用批量分组）
  - `groupResolvedLayers(candidates)` → 分组 + 组内按 (zIndex, sortOrder, id) 排序（GeoServer 按 LAYERS 顺序自底向上绘制）+ 分割 (>20 层自动分块)
  - `joinLayerParams(names, styles)` → 逗号拼接 LAYERS/STYLES（空位 = GeoServer 默认样式）
  - `globalWmsUrl(url)` → `/geoserver/<ws>/wms` 改写为全局 `/geoserver/wms`（跨 workspace 限定名可解析）
  - `createMergedTileSource(group, TileWMSCtor, tileLoadFn)` → 创建共享 TileWMS：多图层组强制普通 WMS（GWC WMS-C 不支持逗号 LAYERS）；单层 GWC 组保留 GWC 端点 + VERSION 1.1.1
- **Feature Flag**: `ENABLE_TILE_MERGING`（默认 on，`VITE_ENABLE_TILE_MERGING=false` 回退逐层）
- **变更点** (MapWorkspaceView.vue):
  - `attachWmsLayer(runtime, opts?, sharedSource?)`: 新增可选第三参数，传入时跳过 TileWMS 创建 + 事件接线
  - `registerMergedGroup` / `syncMergedGroup` / `attachRuntimeGroups` / `flushDirtyMergedGroups`: 合并组运行时管理（事件闭包迭代 `grpRuntime.memberIds` 而非捕获快照）
  - `detachWmsLayer`: 合并组成员移除 → 组空则销毁共享源，否则微任务合并重建 `updateParams(LAYERS/STYLES)`（已删图层名不再被请求）
  - `loadResolvedLayersInBatches` / `buildMap` / 模式切换 / `switchProjection`: 全部走合并组挂载

### 瓦片加载请求流（完整管线）

```
OpenLayers tileUrlFunction 生成 URL
    │
    ▼
createRetryTileLoadFunction(src, controller)
    ├── ① tileCache.get(src) 命中? → Blob → img.src (零网络 I/O)
    ├── ② tileRequestQueue.fetch(src, signal)
    │       ├── 排队 (FIFO, maxQueue=512)；溢出 → 拒绝最新请求 (QuotaExceededError)
    │       ├── 并发槽位可用? → fetch(src)
    │       └── 返回 Response (原始，不消费)
    ├── ③ response.ok? → response.blob()
    │       ├── tileCache.set(src, blob) — 缓存成功响应
    │       └── URL.createObjectURL(blob) → img.src
    ├── ④ 429/502/503/504? → stats.recordRetry() → setTimeout(tryLoad, backoff)
    │       （总尝试次数 ≤ TILE_RETRY_MAX_ATTEMPTS=2）
    ├── ⑤ TypeError (网络失败)? → stats.recordRetry() → setTimeout(tryLoad, backoff)
    └── ⑥ 不可恢复 / 重试耗尽 / 队列溢出? → tile.setState(TileState.ERROR)
            → OL 派发 source tileloaderror → 下次渲染自动重取（不再卡 LOADING）
```

### 设计决策

1. **合并键为 (serviceUrl, renderTransport)**（会话 #20 放宽）：原键含 styleName/objectClass 时，S-57 各对象类几乎一图层一组，合并形同虚设；普通 WMS 支持逐层 STYLES 逗号拼接（bundle 模式已实证），样式/类别不再是共享源障碍。组内按 zIndex 排序保证 GeoServer 自底向上绘制与客户端堆叠一致
2. **GWC 与普通 WMS 隔离分组**：不同端点 (gwc/service/wms vs 普通 wms) + 不同 WMS 版本 (1.1.1 vs 1.3.0) → 不可混用；多图层组强制普通 WMS 全局端点（GWC WMS-C 不支持逗号 LAYERS）；单层 GWC 组保留 GWC 瓦片缓存收益
3. **队列返回 Response 不返回 Blob**：保留 HTTP 状态码供调用方 retry 决策（429/502/503/504），关注点分离
4. **组级 tile 事件更新所有成员**：共享源每瓦片覆盖整组图层 → tileloadstart/end/error 同步更新组内所有 runtime 的 pendingTiles 和 loadState
5. **组成员移除 → `updateParams` 重建而非 dispose+recreate**：OL `TileWMS.updateParams` 合并进现有 params 并 `changed()` 触发重取（瓦片缓存键含 sourceKey），免重绑事件、免逐成员换源；微任务合并批量 detach 为一次重建
6. **队列溢出拒绝最新而非丢弃最老**：最新瓦片转 ERROR 后 OL 会在下次渲染重取；丢弃最老会让已加载中的瓦片永久搁置（空白无重试路径）
7. **`reset()` 不清零 inFlight**：在飞请求完成时自然递减计数，避免卸载/投影切换后 `tryDequeue` 瞬时超发

---

## 5.10 Smart 模式批量加载去重 (会话 #20)

**问题**：批量加载在 smart 模式下把全部图层挂为标准 TileWMS 层，随后 `reconcileRenderPlan` 又为同样 layerId 建 bundle；调度器有意跳过 bundle 覆盖图层的 per-layer 管理 → 批量挂载层永不 detach，同一图层每瓦片请求两次（一次 bundle 合并请求 + 一次单层 GWC 请求）。

**去重流程**（"bundle 胜出"原则）：

```
loadSelectedDatasets (批量确认后)
    │
    ├── ① smart 模式 + bundles 开启 → fetchBundlePlanInputFor(selected ∪ candidates)
    │       缓存键 = 排序选择集|CRS，与挂载后 reconcile 的键一致 → 不重复请求
    │       失败 → bundleCoveredIds 为空（回退全量挂载，由安全网兜底）
    ├── ② loadResolvedLayersInBatches(candidates, generation, bundleCoveredIds)
    │       ├── 被覆盖图层：仅登记（selected/visible/progress），不创建 OL 层
    │       └── 未覆盖图层（standalone）：合并组挂载（每成员自己的 minZoom/maxZoom）
    └── ③ reconcileRenderPlan()（缓存命中）
            ├── 挂 bundle（覆盖图层由 bundle 渲染）
            ├── executeBundlePlan 安全网：bundledLayerIds 中仍存 wmsLayers 的层 → detachWmsLayer
            └── standalone 层已被合并组挂载（attachedLayerIds 守卫跳过重挂）
```

**配套**：
- `BundleRenderPlan` 新增 `bundledLayerIds`（调度器已计算的覆盖集，供安全网使用）
- `layerStatusLabel`：smart 模式下 bundle 覆盖层显示"已显示"（不在 attached/active 集）
- 各挂载路径统一走 `attachRuntimeGroups`（buildMap / 模式切换 / 投影切换 / 批量加载），`VITE_ENABLE_TILE_MERGING=false` 时回退逐层

---

## 5.11 前端航路规划模拟 (会话 #21 / #23)

**定位**：纯前端航路规划沙箱（Route Planning Sandbox），模拟未来正式航线规划模块。不改后端、不新增数据库表，航路草稿存浏览器 localStorage，未来接入 Route API 时仅需替换 Store 的持久化入口。

### 数据不变量

- **业务坐标唯一真值 = WGS84 经纬度 `[lon, lat]`**，永远保存在 `RouteStore` 的 `RoutePoint[]` 中；`EPSG:3857` / `EPSG:3413` 投影坐标绝不落库。
- OpenLayers `Feature<LineString>` 仅为渲染结果：`Route Store → fromLonLat → Feature`，反向 `Modify/Draw → toLonLat → Store`。Feature 永远不是业务真值来源。
- 合法范围：经度 `[-180, 180]`、纬度 `[-90, 90]`；航路至少 2 个航路点；所有输入经 `validateRouteCoordinate()` 校验，错误输入拒绝写入 Store 并提示用户。

### Route Store 与 localStorage 草稿

- `stores/routes.ts`（Pinia Setup Store）：状态 `routes / activeRouteId / interactionMode / revision / loadedProjectId`；`revision` 为单调递增通知计数，地图同步只 watch 它（不做 deep watch）。
- 持久化 key：`polar-gis:route-drafts:${projectId}:v1`（按项目隔离）；payload `{ version: 1, routes }`。
- 容错读取（`parseStoredRoutes`）：JSON 损坏 / 旧版本结构 / 裸数组外形 / 字段缺失 / 非法经纬度 / 重复 id 一律降级处理，绝不抛异常、绝不阻断地图工作台加载；< 2 点的草稿只保留在内存、不写盘。
- 每次数据变更（新增/删除/改名/点位增删改/显隐/拖拽回写）统一经 `touch()` → `revision++` + 持久化。

### routeLayer 与样式

- `composables/useRouteDrawing.ts` 持有 1 个 `VectorLayer`（zIndex **95**：高于海图 WMS 10-40，低于测量层 100 / AIS 110）+ 1 个 `VectorSource({ wrapX: true })` + N 个 `Feature<LineString>`（属性 `routeId / routeName / routeType='route-draft'`）。
- 单条显隐：style function 对隐藏航路返回空值（绝不 `routeLayer.setVisible(false)`）。
- 样式工厂 `createRouteStyle()`：颜色由 routeId 哈希映射固定 8 色池（刷新后颜色稳定）；普通 2.5px、选中 4.5px、编辑中虚线 + 深色外描边（halo）；选中（非编辑）时叠加航路点圆点标记；线样式按 (color, variant) 模块级缓存。
- 缩放/平移零重建：VectorLayer + View resolution 自然完成，**不监听 zoom/moveend**，zoom/pan 全程 0 次 API / GeoServer 请求。

### 航路方向标记（起点 / 途经 / 终点，会话 #23）

- **方向语义**：途经点先后顺序即航路方向 —— `seq` 最小者 = 起点，最大者 = 终点，其余为途经点。角色一律由 `routePointRole(points, index)` 按 **seq** 判定（非数组下标），保证面板点表与地图标记方向一致。
- **渲染**：`createRoutePointStyles(routeId, coordinates)` 为每个投影坐标生成一个 `Point` 几何 + 圆形标记；起点绿 `#2e9e4f`（r=7）、终点红 `#e5484d`（r=7）、途经灰 `#8a94a6`（r=4.5），方向端半径更大且描边更粗；标记 image 按角色模块级缓存（起点/终点颜色恒定，与 routeId 无关），几何每帧新建，绝不跨坐标复用。
- **起点 / 终点标记始终随航路显示**（普通、选中、编辑中三态均含），缩远状态下也能读出航路方向；**途经点仅在选中且非编辑时**叠加，避免多航路同显时节点铺满屏幕。
- 颜色常量 `ROUTE_START_COLOR` / `ROUTE_END_COLOR` 刻意不取自 8 色配色池，避免方向端被线路本身颜色淹没；`styles.css` 中的图例与点表角色色值必须与之逐字一致（由 `RoutePlannerPanel.test.ts` 断言守护，杜绝两套色）。
- **UI 呈现**：点表新增「说明」列（`RoutePointRow.role` / `roleLabel`，派生数据不入 Store），首行标「起点」、末行标「终点」、中间标「途经」；详情区底部给出起点 / 终点图例与「按途经点先后顺序，由起点驶向终点」说明。
- Store 与持久化格式**零改动**：方向完全由既有 `seq` 推导，旧草稿刷新后自动获得方向标记。

### Draw / Modify / 选中

- 自由绘制：`Draw({ type: 'LineString', minPoints: 2 })`，草图走**独立 `Collection<Feature>`**（绝不落入 routeSource，避免重复线与海图遮挡），草图 overlay zIndex 抬到 96；`drawend` → `toLonLat` 全部坐标 → 写回 Store → 自动回到 idle；`removeLastPoint()` 撤销点、`abortDrawing()` 取消绘制（空草稿一并删除）。
- 拖拽编辑：`Modify({ features: Collection([activeFeature]) })` 只允许拖动当前选中航路；`modifyend` → `toLonLat` → `replaceRoutePoints`（按索引复用 point id，表格状态稳定）。
- **拖拽安全**：`modifystart/modifyend` 维护 `isDragging`，拖拽期间 reconcile 直接短路；坐标不变（1e-6 米容差 `coordinatesEqual`）绝不 `setGeometry`，保证 Feature 身份稳定、不打断 Modify 内部 rBush。
- 点击选中：不用 Select interaction，复用 `singleclick` 里的 `forEachFeatureAtPixel` 命中测试（layerFilter 限定 routeLayer + hitTolerance 6），守卫 `interactionMode === 'idle' && measureMode === 'none'`（**会话 #25 起不含面板可见性**——点选随时可用，折叠/关闭航路面板不影响点选；面板折叠后浮窗也不再被强制关闭，仅重算锚点让位），避免与测量/要素识别交互竞争。
- 命中细节（会话 #24）：`pickRouteAtPixel(pixel, coordinate)` 在命中要素后继续判定——先在**视空间**（`px × resolution`）找最近顶点（容差 9px，大于起终点标记半径 7px），再找最近航段（容差 6px，与 `forEachFeatureAtPixel` 的 hitTolerance 同源）。渲染几何的顶点按 `seq` 升序且已 unwrap，因此「渲染下标 i ↔ 第 i 个航路点」。EPSG:3857 下点击坐标先经 `shiftCoordinateIntoWorldCopy()` 平移到与渲染几何同一世界副本（`fromLonLat` 不回绕、`toLonLat` 会回绕，不这么做会命中到另一个副本）。
- 高亮走样式层：`RouteStyleContext.getHighlightedSegment / getHighlightedPointIndex`（**可选成员**，不影响既有调用点）在 `createRouteStyle` 末尾追加一条带自定义几何的 `Style`（高亮段用 `LineString`、定位点用 `Point`），**不新增 source / layer / interaction**；笔触与 image 走模块级缓存，只有 Style 包装器每帧新建（与既有的起终点标记同一成本模型）。隐藏航路返回 `undefined`，不进入渲染重放组，因此**天然不可命中**。
- 定位让位自适应（会话 #25）：`fitRoute` 的让位 padding 不再硬编码，由视图经 `getFitPadding` 按面板折叠状态注入（右侧抽屉开 550 / 折叠 40；左侧图层面板开 420 / 折叠 40），`ROUTE_FIT_PADDING = [90, 550, 90, 420]` 降级为未注入时的默认回退——两侧窗口折叠后「定位整条航路」占满完整地图大屏。

### 投影处理

- `switchProjection()` 中紧跟 `reloadAisGeometry()` 调用 `reloadRouteGeometry()`：先强制回到 idle，再从 **Store 原始 WGS84 点全量重建**所有 Feature 几何——与 AIS 范式一致，杜绝 `3857 → 3413 → 3857` 累积 transform。
- 跨 180° 经线：`unwrapLongitudes()` 连续化**仅作用于渲染几何**（3857 下 179→-179 展开为 179→181），业务数据永不改写；回写时 `normalizeLongitude()` 收拢到 ±180；`fitRoute()` 的 extent 经 `shiftExtentIntoProjection()` 平移回投影范围。EPSG:3413 下 proj4 `adjust_lon` 天然回绕。

### 交互互斥与生命周期

- 进入航路绘制/编辑时视图回调 `deactivateOtherMapInteractions()`（关闭要素识别/气象/结束测量 Draw）；反向切换（测量/识别/气象/关闭面板）一律先 `routesStore.setInteractionMode('idle')`；`interactionMode` 的 watcher 用 `flush: 'sync'` 消除两个 Draw 并存的微任务窗口。
- 航路抽屉为**非模态且可穿透**：`:modal="false"` 仅去掉遮罩，必须同时设置 `modal-penetrable`（EP 官方机制，overlay 获得 `is-penetrable` 类 → `pointer-events: none`），否则抽屉的全屏 overlay 会拦截整个视口的指针事件，导致地图平移/缩放/绘制/拖拽全部失效（会话 #22 根因，由 `RoutePlannerPanel.test.ts` 源码断言守护）。
- `singleclick` 首行守卫：航路交互或测量进行中不触发要素识别/气象/航路选中。
- `onBeforeUnmount` → `routeDrawing.dispose()`（移除交互、清 source、停 watcher）；**不清 localStorage 草稿**，页面回来自动恢复。
- 与海图体系完全解耦：卸载全部海图 / 批量加载卸载 / smart↔standard 切换 / Render Bundle / Tile Merge / GWC / 瓦片缓存均不触碰航路层；截图功能遍历 `.ol-layer canvas` 自动包含航路。

---

## 5.12 测量与地图内浮层 (会话 #24；#32 椭球测距)

### 测量真值与投影生命周期

- **真值口径**：测量结果一律由 WGS84 真值 `MeasureDraft { kind, lonLat }` 生成（`utils/mapMeasure.ts`），不由「当前投影下的几何」生成。因此**结果文本与投影无关**——切换投影只重建显示几何，同一组地理点必然得到同一数值，整类「旧投影几何配上新投影解释」的错值从构造上消失。
- **drawend 顺序陷阱**：`ol/interaction/Draw` 的 `finishDrawing()` 是**先派发 `drawend`、再把要素加入 source**（`Draw.js:1392-1401`）。因此 `drawend` 回调里**只落真值与文本**，绝不清空 `measureSource`，否则会与 OL 随后的 `addFeature` 撞成重复图形。显示几何的重建只发生在投影切换路径（`rebuildMeasureGeometry()`）。
- **`measureMode` 是测量态唯一真值**（`'none' | 'LineString' | 'Polygon'`）：驱动工具栏 `active`、`singleclick` 守卫与 Draw 生命周期；`measureInteraction` 退化为纯 OL 句柄（非响应式）。
- **投影切换**（`switchProjection()` 内紧跟 `reloadRouteGeometry()` 调用 `syncMeasureForProjection()`，与 `reloadAisGeometry()` 同范式）：绘制进行中 → 结束 Draw、清图形与真值、提示「投影已切换，请重新测量」；已完成 → 保留真值，按新投影重建显示几何并从真值重新生成结果。
- **互斥缺口修复**：原实现只有航路一侧完整——`activateMeasure` 不清 `queryMode`/`weatherMode`，`toggleQueryMode`/`toggleWeatherMode` 也不调 `stopMeasureInteraction()`，于是残留的测量 Draw 会让 `singleclick` 守卫**永久提前 return**，要素识别/气象静默失效。现为双向互斥，且测量按钮有激活态（可见而非静默）。

### 球面面积算法

`sphericalRingArea()` 采用 **Van Oosterom–Strackee 球面三角形立体角 + 以 0 号顶点扇形三角化**，半径取 `ol/sphere` 的 `DEFAULT_RADIUS`（与 `getDistance` 同一球体），并取环两侧中较小的一侧。

| 相对 `ol/sphere.getArea` | 结果 |
|---|---|
| 环绕极点的环 | OL 恒返回 **0**（80°N 环解析真值 3,874,523 km²）；新算法给出非零正确值 |
| 跨 180° 经线的环 | OL **偏大约 17 倍**（7,371,200 vs 433,600 km²）；新算法与同形状在常规经度下逐位相同 |
| 小多边形 | 与 OL 一致（0.000%） |
| 20°×6° 高纬盒 @70–76°N | 425,977 km²，比 OL 的 433,600 km² **小 1.76%** |
| 解析闭式对照 | 80°N 平行圈 720 顶点 → 3,874,475 vs 真值 3,874,523（**0.001%**） |

- 边按**大圆**处理，与 `getDistance`/`getLength` 的大圆语义一致；OL 的实现实际是 (λ, sinφ) 线性边（与其文档所称「大圆」不符）。
- **距离模型（会话 #32 起）**：测距工具的折线距离改用 **WGS84 椭球测地线**（`geodesicDistance.ts` + `geographiclib-geodesic`，Karney 算法）逐段求和，并在结果文本标注「WGS84 椭球测地线」；`MeasureDraft` 的 WGS84 真值、投影重建与面积算法不变。面积仍用球面 Van Oosterom–Strackee；航路面板的航段里程（`mapRoute.ts`）仍用球面模型，二者约有 0.3%–0.6% 差异，属有意的范围控制。界面按「近似地表距离 / 椭球测地线」表述，不宣称航海认证精度。
- 单位：距离 **km + NM（1 NM = 1852 m）**，短距离兼显 m；面积恒用 **m² / km²**（面积不换算海里）。

### 航段计算（唯一口径）

- `routeSegments(points)` 按 `seq` 升序切分（n 点 → n−1 段），给出每段距离、累计距离与**初始真方位角**（`[0,360)`；重合点返回 null）。
- `calculateRouteLength()` 重写为 `routeSegments(...).reduce(Σ distanceMeters)`——`ol/sphere` 的 `getLength` 内部本就是 `Σ getDistance`，故两者**逐位相同**，「分段之和 ≡ 总长」由构造成立。面板「入站航段 / 累计」两列与地图浮窗读同一份结果，不可能漂移。
- 方位角是**初始真方位**（相对真北、出发瞬间的值），不是磁方位，也不代表整段恒定航向（沿大圆航行航向持续变化）。

### 地图内浮层（坐标提示 + 航线信息浮窗）

- **DOM 归属**：浮层挂在 `.map-canvas` 的**兄弟节点** `.map-overlay-root`（`position:absolute; inset:0; z-index:30; pointer-events:none`），与既有 `.map-tools` / `.map-status` 同一模式——不往 OpenLayers 的 target 里塞 Vue 子节点，避免与 OL 争抢 `.map-canvas` 子元素。`.map-canvas` 最终为 `inset:0`（`styles.css:350` 覆盖 `:161` 的 `72px 0 0`），故两者与地图视口同框，`map.getPixelFromCoordinate()` 可直接使用。
- **不使用 `ol/Overlay`**：`ol.css` 无 overlay 容器规则且 OL 以行内样式置 `pointer-events:none`，Overlay 只省下重锚定，而重锚定本就是几行 `postrender` 监听。浮窗锚点点击时**原样保存 `event.coordinate`**（与渲染要素同一世界副本，平移缩放重锚定精确）；仅投影切换时由 WGS84 真值重算并用 `shiftCoordinateIntoWorldCopy()` 对齐副本。像素夹取在地图视口内（右侧让开 520px 抽屉），`flipX/flipY` 只由 `map.getSize()` 推导，**不读 DOM 布局**；`postrender` 仅在浮窗打开期间挂载，且仅当锚点真的移动时才写 ref（避免每帧重渲染）。
- **浮窗是只读的**：只调用 `fitRoute()` / `locateRoutePoint()` / `highlightSegment()`，没有改名、加点、删点入口，也不进入绘制/编辑模式（由 `RouteInfoFlyout.test.ts` 源码断言禁用写接口守护）。
- **指针事件**：容器 `pointer-events:none`，只有 `.route-info-flyout` 为 `auto`；坐标提示恒为 `none`（既不遮挡指针也不拦事件）。浮层不在 `.ol-viewport` 内，点击不可能冒泡到地图；`@media print` 中整体隐藏，故也不进入截图/打印输出。
- **生命周期**：一个 `watch([revision, activeRouteId, interactionMode, routePanelVisible, currentCrs])` 对账——航路被删除/隐藏、进入绘制编辑态 → 关闭；航段序号失效 → 清除高亮；其余实时刷新。`routePanelVisible` 仍保留在监听列表，但语义（会话 #25 起）是「面板折叠/展开时重算锚点让位（540↔16）」，**不再关闭浮窗**。`toggleQueryMode` / `toggleWeatherMode` / `activateMeasure` / `deactivateOtherMapInteractions` 均先关闭浮窗，保证识别/气象的点击行为不被抢占。
- **选线入口**：**始终可用**（会话 #25）——`pickRouteAtPixel` 无任何选择门控（原 `isSelectionEnabled: () => routePanelVisible.value` 与视图 `singleclick` 的 `else if (routePanelVisible.value)` 分支均已移除），仅剩 `interactionMode === 'idle' && measureMode === 'none'` 与识别/气象优先级守卫。状态栏提示改为「有可见航路即显示」（与面板无关）。浮窗打开时折叠/关闭航路面板，浮窗**保持显示**并重新夹取位置。
- **坐标提示门槛**：用 `ol/proj.getPointResolution()` 计算**指针处的地面分辨率**（米/像素）而非 zoom——同一 zoom 在 3857/3413 下地面精度相差数倍（实测 3857 zoom4 ≈ 2532 m/px、3413 zoom4 ≈ 39500 m/px），且同投影内随纬度变化。门槛 `HOVER_MIN_GROUND_RESOLUTION_METERS = 1000`；小数位 `clamp(floor(log10(111320 / 地面分辨率)), 2, 5)`，保证**末位数字不细于 1 像素**。复用既有 `pointermove` 监听 + `requestAnimationFrame` 合帧（每帧最多一次）。隐藏条件：低于门槛、指针离开地图、拖动期间、触控/触笔、浮窗打开、地图销毁、坐标非法。**`toLonLat` 对 EPSG:3413 的越界坐标会返回「有限但无意义」的值（不返回 NaN）**，故范围判定用显式检查（`containsCoordinate`，3857 因 `canWrapX()` 为 true 只校验纬度带）。

## 5.13 后端规划结果展示契约草案 (任务 D,会话 #24)

- `types/routePlanning.ts`：**纯类型文件,零运行时代码、零 API 调用、零演示数值**——`RoutePlanningStatus`（missing/loading/computing/failed/stale/complete）、`RoutePlanningRiskLevel`、`RoutePlanningSegmentResult`、`RoutePlanningResult`（routeId / resultVersion / computedAt / dataSource / 总距离 / 预计航时 / 风险等级与指标 / 分段结果）、`RoutePlanningResultAdapter`（接入层负责字段校验 + 单位与时间格式转换 + 身份区分）、`RoutePlanningViewState`（把「没有数值」编码进类型,避免 `?? 0` 把缺失当零）。
- **展示原则**：只有 `status === 'complete'` 且字段非 null 才渲染数值;其余状态只显示状态文案与占位符,不显示 0、不沿用上一次的旧值;`stale` 必须显式告知「结果已过期」;`failed` 给出原因且不留半截数据。
- **当前无任何页面消费该文件**（后端尚无航路规划接口,也没有可靠的航速/船舶参数/风险计算服务,不伪造这些数据）。接入方式与挂载位置见文件头注释。

---

## 5.14 冰情叠加 (Ice Overlay, 会话 #26)

**定位**：把参考项目 `polar-gis-ice-viewer` 的**冰情数据能力**（NetCDF → PNG XYZ → 独立 TileLayer）移植进主系统，作为**独立环境叠加层**：

```text
NetCDF (EPSG:3411 网格)
   ↓  app/services/ice.py(IceService,按需读网格 + 最近邻采样)
PNG XYZ 瓦片(/api/v1/ice/{field}/{projection}/tile/{z}/{x}/{y}.png?date=)
   ↓  frontend utils/mapIce.ts + composables/useIceOverlay.ts
OpenLayers 独立 TileLayer(密集度 zIndex 60 / 厚度 62,调试对齐 120)
```

**与 S-57 渲染管线彻底解耦**：冰情图层**不进入** runtimeLayers / runtimeDatasets / selectedLayerIds / attachedLayerIds / activeLayerIds / warming / suspended / manuallyForced / loaded / failed 任一状态集合，也**不进入** Render Bundle、mapRenderScheduler、mapTileMerger、GWC 与 S-57 导入/目录体系；卸载全部海图、smart↔standard 切换、LRU 驱逐均不触碰冰情（由 `useIceOverlay.test.ts` 源码断言守护）。冰情瓦片**复用**与海图相同的通用请求管线实例（`TileRequestQueue` 限流 + `LRUTileCache` 共享缓存 + 自定义 `tileLoadFunction`，见下方"瓦片加载性能"节）——**共用管线不等于进入 S-57 生命周期**：冰情图层仍不注册进任何 S-57 状态机/调度器。

### 后端

- **`app/services/ice.py`**（`IceService`，Settings 注入 `ice_data_root / ice_tile_cache_entries / ice_tile_max_zoom`）：
  - 日期识别 `(\d{8})\.nc$`（仅实际文件；`info()` 时重扫目录，并对 `(mtime,size)` 变化的日期逐日期失效 metadata/grid/tile 缓存）；
  - 字段别名 `FIELD_ALIASES`（密集度 `sic_merged|sea_ice_area_fraction|ice_concentration|sic`；厚度 `sea_ice_thickness|ice_thickness|sit|thickness`），不假设每个文件同时含两个变量；
  - **NoData 语义（唯一归一化入口 `_normalize`，hover 与瓦片共用，数值不可能漂移）**：concentration 有效域 **0..100（0 是有效值）**，127/101/255/负值/NaN/掩码 → NoData；thickness 掩码 + `_FillValue`/`missing_value` 哨兵 → NoData，`cm→m`、`mm→m`、**未知单位不猜测**（原样 + 一次性告警）。修复了参考实现的三处缺陷：锁内渲染（现为锁外）、`np.ma.filled(np.asarray())` 丢掩码（现显式 `getmaskarray` + 哨兵置 NaN）、`value_at` 与 `_render` 单位不一致；
  - **投影链**：3411 →(pyproj)→ WGS84 →(3411 米坐标绝不当作 3413)→ 显示投影 3413/3857；3857 加 ±85.05112878° 纬度钳制（极点区域保持透明/返回 null）；tile 渲染为像素中心批量变换 + 最近邻（与 hover 同口径），调色板按通道线性插值（含 alpha），`PALETTE_STOPS` 与前端 `ICE_PALETTES` 逐值一致（两侧测试各自锁定）；
  - **线程契约**：单个 RLock 只保护 netCDF4 Dataset 访问与缓存变更；numpy/PIL/pyproj 在锁外；pyproj Transformer 自 3.1 起内部按线程隔离 PROJ context（实测 8 线程×200 变换结果一致），共享不加锁；tile 缓存 LRU（cap=`ICE_TILE_CACHE_ENTRIES`），价值网格按日期缓存 2 个（LRU）；
  - 降级：目录缺失/为空/文件损坏 → 空索引/空字段，绝不抛到调用方之外（Ice failure ≠ Map failure）。
- **`app/api/ice.py`**（`/api/v1/ice`）：`GET /info`、`GET /value`（miss 响应**精确** `{"value": null}` 200，时间轴快速拖动不产生错误噪音）、`GET /alignment`（调试 GeoJSON）、`GET /{field}/{projection}/tile/{z}/{x}/{y}.png`（`Cache-Control: private, max-age=300`）。
  - **进程级共享实例**：`services/ice.py::shared_ice_service()` 按 `(root, cache, maxZoom)` 复用同一个 `IceService`；冰情 API 与导航环境 `IceProvider` 不再各自构造实例，首次进入项目只执行一次全目录元数据扫描/一次预热线程/一份网格缓存。
  - **`/info` 响应缓存**：目录 `(mtime,size)` 未变化时直接复用上次扫描结果；新增/修改日期才失效。`warm_default_grid()` 每个实例只启动一次（`_start_warm_once`），面板重试不会反复起线程。
  - **瓦片 PNG 压缩**：`Image.save(..., compress_level=1)` 替代 `optimize=True`（后者每张瓦片执行昂贵的 zlib 参数搜索）；瓦片体积略增、CPU 明显下降。
  - **鉴权边界（唯一无鉴权数据 API，刻意为之）**：OpenLayers XYZ 原生 `<img>` 无法携带 Bearer，生产地图瓦片（`/geoserver` 经 nginx）同为无鉴权读取，后端仅在内网 `internal`、外部唯一入口是 web/nginx —— 故选"与现有地图瓦片相同的只读访问边界"（任务书 §38-A）。熔断开关 `ICE_ENABLED=false` → 404 `ICE_DISABLED`。
  - 服务经懒工厂 `get_ice_service()`（双重检查；不用 lru_cache/Depends，便于 monkeypatch 与"导入期绝不因数据/PROJ 失败"）。
  - 状态码：畸形参数 422（框架）；未知字段/投影/日期/z>max/x≥2^z → 404（`ICE_*` 码）；`/value` 的一切不可用 → 200 null。
- **配置**：`ice_enabled` / `ice_data_root`（默认 `/data/ice`，代码中无任何机器绝对路径）/ `ice_tile_cache_entries` / `ice_tile_max_zoom`（对应 `ICE_*` 环境变量）。
- **依赖**：`netCDF4`、`numpy`、`Pillow`、`pyproj`（cp312 manylinux 轮子，`python:3.12-slim` 无需新增 apt 包）；不引入 `shapely`（仅参考项目临时 GeoPackage 底图使用，未迁移）。

### 前端

- **`utils/mapIce.ts`**（纯函数，jsdom 可测）：EPSG:3411（Hughes）proj4 按需注册、`createIceTileGrid`（3413: ±4194304/256/maxZoom 10 与后端 `half` 严格对齐；3857 标准 extent）、`buildIceTileUrl`（**URL 必带日期**）、`iceFieldAvailable`、`formatIceDate`、`projectIceExtent`（3411→当前投影，hover 预筛用）、`isIceValueValid`（0 有效）、`iceTimelineIndex` / `stepIceDate`（**数组索引边界，绝不按 date±1**）、`ICE_PALETTES` / `iceLegendGradient`（与后端同源）。
- **`composables/useIceOverlay.ts`**：`info/loading/error/selectedDate/密集度与厚度 visible+opacity/hover/debugAlignment` 状态；`attach()` 幂等、`dispose()` 彻底（removeLayer+dispose+abort）；**日期/可用性/投影变化只 `setSource` 不重建 layer**（换新 XYZ 源含日期参数，旧源自然 GC；`transition:0` 无淡入残影；`crossOrigin:'anonymous'` 供截图合成）；`reloadForProjection()` 保留日期/可见性/透明度只换源与 TileGrid；hover **100ms debounce + AbortController + 请求代次号**（旧响应绝不覆盖新位置），拖图/图层关/无日期/其他交互(`canQueryValue`)/离开范围/销毁一律停止；**不自行注册 map 事件**。
- **组件**（统一 `ice-` 前缀）：`IceLayerPanel`（密集度/厚度开关+透明度+图例+「当前日期无厚度变量」禁用态+定位冰区+对齐调试开关；会话 #30 起移除安全提示文案）、`IceTimeline`（`info.dates` 索引驱动、首尾禁用、`n / N 个可用日期`、只显示日期不构造文件名；**左右让位由视图注入**，随面板折叠自适应）、`IceValueTooltip`（原始值+日期+经纬度，像素锚定+边缘翻转，`pointer-events:none`）。
- **视图集成（最小侵入）**：`buildMap()` 中 `iceOverlay.attach()`；唯一 `pointermove` 分发 `handlePointerMove` 并在冰情浮窗显示期间抑制经纬度提示（优先级：航路浮窗/地图工具 > 冰情 > 经纬度）；`pointerleave` 与卸载同步清理；`switchProjection()` 在 `syncMeasureForProjection()` 后调用 `iceOverlay.reloadForProjection()`；环境叠加 dropdown 增「冰情信息」入口；时间轴挂载于 `.map-overlay-root`（打印/截图自动排除，冰情地图图层自然进入截图）。

### 瓦片加载性能（会话 #26.1 专项，实测驱动）

**实测根因（修复前）**：① 后端 `_grid` **惊群**——并发冷请求在"归一化在锁外"的窗口内各自完整装载 26M 单元网格（实测单次装载 ≈1.5s；8 张并发冷瓦片**每张 6.6s**、总 7.1s，互相挤占）；② 前端冰情走 OL 默认 `<img>` 加载器——无并发上限（z3 整个北极一次可发 ~64 张）、瓦片被丢弃不中止、无共享缓存 → 请求堆积占满浏览器连接与后端线程，新日期瓦片排队（表现为"时间轴更改无法重新加载"）、海图/底图瓦片被挤占（地图空白）。

**修复**：
- 后端**按日期单飞装载**（`_grid` 快路径 + per-date 装载锁 + 双检；等待者复用同一次装载结果），并将 `warm_default_grid()` 挂在 `info()` 的后台守护线程上预热默认日期（点击"海冰密集度"直接进入 ~0.1s 渲染路径）；`_refresh_files` 换文件时同步失效对应装载锁语义。会话 #30 进一步把 `/info` 元数据扫描结果缓存到目录变化为止，并让 API 与导航 Provider 共享同一个 `IceService`（见 5.14 后端节）。
- 前端冰情瓦片改用**自定义 `tileLoadFunction`**，复用与海图相同的 `TileRequestQueue`/`LRUTileCache` 实例：缓存优先 → 限流 fetch → blob/objectURL；**代次中止**（`refreshLayers` 即日期/投影/开关切换时，`abortStaleTileLoads()` 使上一代全部在飞请求立即中止让出名额）+ 瓦片被 OL 释放（ol10 中 `release()/dispose()` 置 `TileState.EMPTY`）即中止 + 429/502/503/504 与网络错误指数退避重试。

**修复后实测（经 nginx 真实数据）**：冷日期 8 张并发瓦片总耗时 **7.1s → 3.06s**（每张延迟一致、无饥饿）；`/info` 后（预热）全新冷瓦片 **0.13–0.39s**；已验证部署 bundle 含新加载器。**已知特性**：容器重启后**首次** `/info` 在 Windows bind-mount 上约 12s（149 个 HDF5 首次打开；逐日缓存后 0.1s），期间地图与其它功能不受影响，预热仍保证首次点击瓦片快速。

### 部署

- `data/ice/`（仅 `.gitkeep` + `README.md`，`.gitignore` 排除 `*.nc`；`sample-data/` 与 `sample-data.7z` 同样排除）；
- `deploy/compose.yml`：`- ${ICE_DATA_HOST_PATH:-../data/ice}:/data/ice:ro` + `ICE_ENABLED`/`ICE_DATA_ROOT`（经 YAML 锚点 worker 同样获得，但不读取数据）；不新增任何服务；
- **`deploy/nginx/default.conf`：`location /api/` → `location ^~ /api/`** —— 否则 `/api/v1/ice/.../*.png` 会被静态图片正则 location 拦截，经 `try_files` 回退成 `index.html`（200 text/html），表现为"瓦片永久空白"（已实测复现：旧配置返回 SPA index；修复后返回 image/png）。

---

## 6. 文件清单

> 2026-11-11 按磁盘实际清点（不含 `__pycache__` / `node_modules` / `.venv`）。

### 后端（`backend/`，91 个 app Python 文件 + 34 个测试 Python 文件）
- `app/api/`: 18（含 `__init__.py`）
- `app/core/`: 6
- `app/services/`: 17
- `app/navigation/`: 43（contracts/environment/providers/vessel/risk/planner/tasks/resources）
- `app/worker/`: 2
- `app/` 根文件: 5（`main.py`、`models.py`、`schemas.py`、`cli.py`、`__init__.py`）
- 迁移: `migrations/versions/` 6 个脚本（0001–0006）
- 测试: 32 个 `test_*.py` + `conftest.py` + `navigation_fixtures.py`
- 配置: `pyproject.toml`、`alembic.ini`、`.env.example`、`.dockerignore`、`Dockerfile`

### 前端（`frontend/src/`，65 个源码文件 + 41 个测试文件）
- Vue: `views/` 11（含 `admin/` 8）、`components/` 17、`layouts/` 1、`App.vue` 1 = 30
- TypeScript: `api/` 5、`stores/` 4、`types/` 4、`utils/` 21、`composables/` 6、`router/` 1、`main.ts` + `env.d.ts` = 43
- 测试: 41 个 `*.test.ts`（与源码同目录，vitest + jsdom）
- 配置: `package.json`、`package-lock.json`、`vite.config.ts`、`tsconfig.json` / `tsconfig.app.json` / `tsconfig.node.json`、`index.html`、`Dockerfile`、`.dockerignore`

### 部署（`deploy/`）
- `compose.yml`（5 服务）、`.env.example`、`nginx/default.conf`

## 7. 文档索引

| 文档 | 用途 |
|------|------|
| `docs/01-requirements.md` | 需求规范 (v1.0) |
| `docs/02-system-design.md` | 系统设计 |
| `docs/03-data-design.md` | 数据设计 |
| `docs/04-api-design.md` | API 设计 |
| `docs/05-ui-ux-design.md` | UI/UX 设计 |
| `docs/06-development-plan.md` | 开发计划 |
| `docs/07-testing.md` | 测试与验收 |
| `docs/08-deployment.md` | 部署说明 |
| `docs/09-system-architecture.md` | 系统架构文档 (本文件) |
| `docs/10-work-log.md` | 工作日志 |
| `docs/11-work-summary.md` | 工作总结 |
| `docs/12-user-manual.md` | **用户操作使用手册** ⭐ |
| `docs/13-presentation-slides.md` | 汇报材料 |
| `docs/14-s57-version-update-and-route-drawing-research.md` | S-57 版本更新与航路绘制研究 |
| `docs/15-Polar-GIS 集成 PolarOptionNav-System-V3 全功能开发任务书.md` | 导航集成总任务书 |
| `docs/plans/v3-integration-audit.md` | V3 集成审计（基线/差距矩阵/迁移计划） |
| `docs/plans/v3-integration-final-report.md` | V3 集成最终交付报告 |
| `docs/plans/Polar-GIS 地图瓦片加载稳定性修复与 S-57 航道专题信息开发任务书.md` | 会话 #31 任务书 |
| `docs/plans/Polar-GIS 测距精度优化、S-57 航道数据持久保存及海图图例开发任务.md` | 会话 #32 任务书 |
| `docs/plans/` 其余文件 | 历史计划/提示词（冻结原文，含冰情、批量加载、航路绘制等） |

---

## 8. 导航集成（PolarOptionNav-System-V3）— 批次 A 基座

> 2026-10-29 起实施。详细审计见 `docs/plans/v3-integration-audit.md`；实施计划文件不入库。

### 8.0 2026-10-10 后计划、任务与实现索引

| 日期 | 计划/任务来源 | 实际实现（会话） | 架构章节 | 状态 |
|------|---------------|------------------|----------|------|
| 2026-10-10 | 用户要求：术语修正 + 参考工程清理 | 会话 #27 | 5.14 / 10 日志 | ✅ 已完成并推送 |
| 2026-10-29–30 | `docs/15` 任务书 + `v3-integration-audit.md` + `v3-integration-final-report.md` | 会话 #28（A–E 批次）、#29、#30 | 8.1–8.10 | ✅ 已完成；真实环境数据未验证 |
| 2026-11-04 | `docs/plans/Polar-GIS 地图瓦片加载稳定性修复与 S-57 航道专题信息开发任务书.md` | 会话 #31 + 当日追加修复 | 8.11 | ✅ 已完成；GWC 3413 WMTS 未验证 |
| 2026-11-04 | `docs/plans/Polar-GIS 测距精度优化、S-57 航道数据持久保存及海图图例开发任务.md` | 会话 #32 + 当日追加优化 | 8.12 | ✅ 已完成；完整 Compose 端到端建议补验 |
| 2026-11-11 | 用户要求：核对 10.10 后计划并补全文档 09–12 | 会话 #33（文档维护） | 全文 | ✅ 本次更新 |

> 当前代码基线：`master` @ `ab57c2a`（2026-11-04）。上表之后无新的业务代码提交；
> 文档 09–12 于 2026-11-11 按真实代码与部署配置重新核对。

### 8.1 代码组织

导航业务不再使用 V3 的根级 `core/`、`services/` 包，而是作为 Polar-GIS 内部业务域：

```
backend/app/navigation/
├── __init__.py                 # NAVIGATION_CONTRACT_VERSION = "1.0"
├── contracts/                  # 坐标/方向/时间/单位/质量/证据/可行性
│   ├── coordinates.py          # WGS84 / 本地 ENU / bearing / math yaw
│   ├── directions.py           # Wind/Wave FROM, Current TO, (u,v) 转换
│   ├── time.py                 # UTC、TimeMetadata、TimeMatchInfo、max-lag
│   ├── units.py                # nm/m、kn/m/s、deg/rad
│   ├── quality.py              # AvailabilityStatus + DataQuality(real/synthetic/missing/unknown)
│   ├── evidence.py             # 参数来源证据
│   └── status.py               # PASS/FAIL/UNKNOWN（禁止布尔化）
├── environment/                # 环境源服务 + providers（GEBCO/CARRA2/TOPAZ5/WAM/ICE）
├── vessel/                     # 雪龙2静态资料 + 吃水安全
├── risk/                       # legacy_v1 / real_v1 风险模型
├── planner/                    # 25km 静态网格、D* Lite、DNSGA-III、能耗模型
├── tasks/                      # 规划任务状态机 + worker 处理器
├── resources/
│   ├── vessels/xuelong2.json   # 雪龙2静态资料（来源见文件 sources）
│   ├── grids/northeast_passage_25km_static.npz  # 25km NEP 静态网格（488KB）
│   └── risk/weights_v1.json    # legacy_v1 权重/公式与 real_v1 缺测策略
└── netcdf.py / schemas.py      # NetCDF 辅助与请求/响应模型
```

### 8.2 配置

`core/config.py` 新增（全部有默认值、可由环境变量覆盖、无 Windows 绝对路径）：

- `NAVIGATION_ENABLED`、`NAVIGATION_DATA_ROOT`、`NAVIGATION_ICE_DATA_ROOT`（缺省复用 `ICE_DATA_ROOT`）、
  `NAVIGATION_ICE_BACKEND`、`NAVIGATION_MANIFEST_PATH`、`NAVIGATION_DEFAULT_DATA_POLICY=real_only`、
  `NAVIGATION_ALLOW_FUTURE_MATCH`、各环境源 `NAVIGATION_MAX_LAG_*_HOURS`、瓦片/批量上限。
- `PLANNER_MAX_CELLS`、`PLANNER_MAX_CANDIDATES`、`PLANNER_MAX_GENERATIONS`、`PLANNER_POPULATION_SIZE`、
  `PLANNER_TIMEOUT_SECONDS`、`PLANNER_MAX_CONCURRENT_JOBS`、`PLANNER_MAX_QUEUED_RUNS`、
  `PLANNER_MAX_RETAINED_RUNS`、`PLANNER_RESULT_ROOT`、`PLANNER_RISK_GRID_MAX_CELLS`、`PLANNER_MAX_ROUTE_POINTS`。

### 8.3 边界约束

- 不新增第二个 FastAPI 应用、独立地图实例、认证系统或 V3 根级包。
- 所有规划/环境/风险接口后续统一挂 `/api/v1/navigation/`；规划耗时任务进入 worker，不占用地图 API。
- 业务坐标 WGS84 `[lon, lat]`；渲染时才转 EPSG:3413/3857。
- 质量/时间语义：每字段 `real|synthetic|missing|unknown`；缺失不填 0；`combinedRisk=null` 而非 0。
- 合成测试数据必须由 `navigation_manifest.json` 标记 `quality=synthetic`；`real_only` 拒绝。
- 现有 S-57/GeoServer/GWC/海冰/手绘航路/认证/权限保持不变。

### 8.4 批次 A 实际改动

- `.gitignore` 排除嵌套参考仓库 `PolarOptionNav-System-V3/`，避免 `git add -A` 污染提交；
  新增测试临时目录忽略项。
- `backend/app/navigation/contracts/*` + 资源文件 + `core/config.py` 导航配置。
- `backend/tests/conftest.py` 注入临时导航数据根/结果根；新增 `test_navigation_contracts.py`（10 测试）。
- 基线：后端 214 passed；前端 20 files/353 tests passed；ruff 既有 29 errors（未新增）。
- 本批次无 API、无数据库迁移、无前端可见变化。

### 8.5 批次 B：环境感知与船舶模型

**后端 Provider**（`backend/app/navigation/environment/`）
- `providers/base.py`：`available/times/sample/sample_many/coverage/close` 统一接口；单 Provider 失败返回 `ProviderSample(available=false, reason)`，不拖垮其他字段。
- `gebco.py`：GEBCO NetCDF elevation → 正向下深度；陆地 elevation≥0 → `depthM=0,isLand=true`；NoData/越界显式 unavailable；`tile()` 渲染 3413/3857 256px PNG（透明陆地/NoData，LRU+单飞）。
- `ice.py`：`polar_gis` 后端包装现有 `IceService.value_at`（浓度 %→0–1，厚度缺失只标该分量 missing，不把整个冰字段置 unavailable）；`nextsim` 后端读 `siconc/sithick`；`auto` 按数据根/文件名探测。会话 #30：`polar_gis` 后端复用**共享** `IceService`，`info()` 结果缓存 60s，4326→3413 `Transformer` 只构建一次，避免每个规划格点重扫目录/重建投影器。
- `carra2.py`：月度 `si10/wdir10`（兼容 `u10/v10`）2D 网格；FROM 风向；输出 speed/from/u/v。会话 #30：`coverage` 网格元数据缓存到月份切换；`sample()` 不再逐点 `nanmin/nanmax`（真实 1200×1200 网格实测 200 点 1.34s→0.17s）。
- `topaz5.py`：原生极地 x/y（100km 坐标单位，自动识别米制）、`vxo/vyo`；按本地 ENU 方位角旋转为地理东/北，输出 u/v/speed/directionTo。
- `wam.py`：`VHM0/VTPK/VMDR`；双线性高度/周期、环形方向插值；VMDR 明确为 FROM。同样只计算一次 coverage；`sample()` 使用缓存值。
- `gebco.py`：先读 1-D 坐标轴做覆盖判断，越界点不再加载完整 elevation 数组；coverage 缓存；瓦片 PNG 使用 `compress_level=1`。
- `manifest.py`：数据根可选 `navigation_manifest.json`，逐字段 `quality=real|synthetic`；`real_only` 拒绝 synthetic 文件（reason=`synthetic_data_not_allowed`），合成研究数据不会伪装成真实观测。
- `time_manager.py`：`latest_not_after`（默认）只取 requested 之前有效时次；provider 提供 issue_time 时要求 issue≤requested；按源 max-lag（风 6h、冰/流/浪 24h）；研究模式允许 nearest；不把未来预报当历史分析。
- `service.py`：五字段故障隔离查询/批量/矢量场/快照；`EnvironmentSnapshot` 冻结 requested time、每字段 matched/valid/issue/quality；质量汇总 `combine_quality`。

**API**
- `GET /api/v1/navigation/environment/sources`、`GET /times`、`POST /query`、`POST /batch-query`：JWT 鉴权；每个字段返回 `available/value/unit/source/matchedTime/validTime/issueTime/quality/reason`；单 Provider 失败不影响其他字段。
- `POST /field`：bbox+time+zoom+maxPoints，最多 900 点；风/流/浪矢量采样，逐点返回 source/matchedTime/quality/reason。
- `GET /environment/tiles/bathymetry/{crs}/{z}/{x}/{y}.png`：公开只读标量瓦片（与海冰一致的访问边界）；nginx `^~ /api/` 已优先。
- `GET /api/v1/navigation/vessels`、`/{id}`、`/{id}/depth-safety?depth_m=`：静态雪龙2资料，明确 `liveStateAvailable=false`；`requiredDepth=draft+UKC=7.85+2.0=9.85m`。

**前端**
- `useEnvironmentOverlays.ts`：注入既有唯一 Map、`tileCache`、`tileRequestQueue`；水深 XYZ 瓦片 + 风/流/浪 VectorLayer；每层独立 visible/opacity/loading/error/source/matchedTime/quality；`attach/dispose/reloadForProjection`；瓦片 generation abort；矢量 moveend 300ms 防抖、旧请求 abort、最多 600 点。
- `utils/mapEnvironment.ts`：WGS84 地理方位角构造箭头端点后再投影（不在 EPSG:3413 平面直接使用 u/v）；风/浪 FROM→箭头指向 TO，流 TO；箭头长度随 zoom；颜色按风速/流速/浪高。
- `EnvironmentValueTooltip.vue` / `EnvironmentLayerPanel.vue` / `EnvironmentTimeControl.vue`：显示原始值、单位、source、matchedTime、quality；`EnvironmentLayerPanel` 内含 UTC 时间控制与研究数据开关；不替换底部 `IceTimeline`。
- `MapWorkspaceView.vue`：`buildMap` attach；`switchProjection` reload；`moveend` 刷新矢量；唯一 `pointermove` 分发 hover；唯一 `singleclick` 关闭 hover；unmount dispose。zIndex：水深 50、风 64、流 66、浪 68；不进入 `runtimeLayers`/bundle/scheduler。
- 环境叠加菜单：AIS/冰情/环境图层/水深/风场/海流/海浪/风险评估（风险需规划结果，暂禁用）。

**测试**
- 后端新增 32 tests（契约 10、Provider/Service 10、环境 API 8、船舶 API 4）；全套 246 passed。
- 前端新增 `mapEnvironment.test.ts`（双投影箭头/bbox/格式化）、`EnvironmentLayerPanel.test.ts`、`VesselProfilePanel.test.ts`；全套 365 passed；`vue-tsc` 零错误。

**已知限制**
- 本机无真实环境数据；Provider 只读配置数据根，缺文件显式 unavailable；E2E 只能用 manifest 标记的合成数据。
- 环境图层默认允许显示合成研究数据；规划阶段默认 `real_only`，两者策略相互独立。会话 #30 起不再显示“含合成数据”黄色标签。
- 风险栅格/规划图层/采纳编辑在 C/D 批次。

### 8.6 批次 C：风险、规划算法、异步任务与持久化

**风险（`backend/app/navigation/risk/`）**
- `evaluator.py`：`legacy_v1` 精确复现 V3 公式（冰 load/1.35 阻断、深度 draft+UKC、风 11.7/5.0、浪 5.0/1.2、雾先验、原权重 0.4/0.2/0.2/0.1/0.1）；`real_v1` 禁止合成，雾 null，冰/深度缺测→combined null + traversable null，风/浪缺失按可用权重归一；输出分项/综合/quality/sources/blockedReason/modelVersion。
- `weights_v1.json` 是权重/公式版本源；`real_v1` 不把缺测当 0 风险。

**规划核心（`backend/app/navigation/planner/`）**
- `static_grid.py`：只读 V3 NPZ（110×240，15,731 格，8,738 可通行）；校验 version=3；不依赖 rasterio；网格是 EPSG:3413 25km 业务网格，不是瓦片/像素/zoom。
- `environment_adapter.py`：按 policy 构建逐格环境；`real_only` 缺字段→obstacle/unknown，全区域缺字段→`ENVIRONMENT_DATA_MISSING`；`allow_synthetic_research` 才用 V3 确定性 gap-fill，并逐格标 `synthetic`+`gap-fill-v1`。
- `grid.py` + `energy_model.py`：唯一 `EdgeTransitResult`；船舶参数注入（max speed/power/UKC/冰能力）；静水/冰/风/浪功率、流沿航向 SOG、MWh/hours/kn；两艘不同功率/航速船产生不同 speed/energy。
- `dstar.py`：一次性 D* Lite（g/rhs/key），三种目标种子路径；协作式 `should_stop`/deadline。
- `dnsga3.py`：三目标 Risk/Energy/Time，Distance 仅统计；D* 三种子填初始种群，非支配/去重/代表解（最低风险推荐）；默认 pop36/gen20/seed42。
- `service.py`：快照→网格→风险→D*/NSGA→候选航线→风险栅格；`NO_FEASIBLE_ROUTE` 时仍返回风险栅格；`risk_only` 只生成风险栅格；`evaluate_route` 读取持久化风险栅格，按 ≤5km 加密并逐格检查可通行，跨陆地/浅水/缺测拒绝。

**持久化 / worker**
- `planning_runs` + `planning_routes`（Alembic `0005_navigation_planning`）；路线坐标 JSON、风险栅格 gzip 文件（临时文件+原子 rename），避免大数组入 DB JSON。
- `worker/main.py`：`run_once(session_factory)` 可注入测试库；batch→import→planning；`claim_planning_run` 用 `SKIP LOCKED`，10 分钟心跳超时→failed；规划异常只标 failed，不杀唯一 worker；短事务心跳、取消 flag 新会话读取、worker_id 租约 fencing。
- `PlanningRunProcessor`：queued/running/completed/failed/cancelled；超时/取消/环境缺失/无路线/算法失败分别映射错误码；风险栅格先写后置 completed。

**API**
- `POST /api/v1/navigation/plans`（202；project/vessel/UTC/三目标/网格校验；返回 planId + 请求坐标）；`GET /plans`、`GET /plans/{id}`、`GET .../routes`、`GET .../routes/{routeId}`。
- `GET .../risk-grid?field=&bbox=&stride=`（GeoJSON，property 只含 cellId/value/traversable/quality/riskModelVersion；服务端自动 stride 限流）；`GET .../risk-grid/{cellId}` 完整格详情。
- `POST .../cancel`（queued 立即 cancelled，running 置 flag；requester/admin）。
- `POST .../evaluate-route`（≤1000 点；读取 run 风险栅格；≤5km 加密；返回 metrics/quality/traversable/reason/blockedCellId）。
- `POST /api/v1/navigation/risk/evaluate`：`mode=risk_only` 区域风险任务，无航线。
- 鉴权沿用 JWT + published project；取消 requester/admin；错误码 `ENVIRONMENT_DATA_MISSING/NO_FEASIBLE_ROUTE/PLANNER_TIMEOUT/PLANNER_CANCELLED/PLANNER_FAILED/PLANNER_LIMIT_EXCEEDED/PLANNER_RESULT_NOT_READY/PLANNING_GRID_MISSING/...`。

**测试**：新增 31 个（风险 9、网格/适配 4、D*/NSGA/能耗 6、规划服务 3、Worker 3、规划 API 6），全套 **277 passed**；迁移在全新 SQLite 与“0004 后无 planning 表”两种场景升级通过；同时修正 0004 幂等性以支持 fresh DB。`ruff` 新增代码通过。

### 8.7 批次 D：前端规划工作台与航路融合

**状态与 API**
- `stores/navigation.ts`：项目/船舶/任务列表/当前 run/候选/选中/风险字段/风险格/单格/`pickMode`/`riskInspect`/focusRoute；2s 轮询（queued/running），completed 自动拉候选；failed/cancelled 停止；`adoptRoute` 复制候选到 `routesStore`，`refreshAdoptedMetrics` 调用 evaluate-route。
- `api/navigation.ts`：创建/列表/详情/候选/取消/风险格/单格/区域风险/采纳重评；请求体 camelCase，查询参数由既有 axios 拦截器转 snake_case。
- `types/navigation.ts`：planning run/route/risk/Evaluate/RoutePlanningSnapshot；`types/index.ts` 的 `RouteDraft` 增可选 `origin/sourcePlanId/sourceRouteId/planningSnapshot`。

**地图图层**
- `usePlanningRouteLayer`：独立 VectorLayer zIndex 90；推荐/候选不同颜色线型，未选低透明、选中加粗；`attach/setRoutes/setSelected/reloadForProjection/dispose/fitRoute/pickRouteAtPixel`；WGS84→投影用既有 `buildRouteLineString`（跨 180° unwrap/world copy）。
- `useRiskGridLayer`：WGS84 GeoJSON VectorLayer zIndex 70；undefined/null 用灰色独立样式（绝不按 0 风险着色）；可点选 cellId；planId 快照绑定；`reloadForProjection/dispose`。
- `MapWorkspaceView`：唯一 Map 上 attach/卸载/投影重载；`singleclick` 优先级 pickMode → 测量/手绘 guard → riskInspect → weather → identify → 手绘航路 → 算法航线；不新增第二 handler；风险/环境/规划失败不阻塞地图。

**UI**
- `RoutePlannerPanel` 顶部“手动绘制 / 智能规划”；手动原内容保留；智能侧 `IntelligentPlanningPanel`（任务/船舶/候选对比/风险/结果）。
- `NavigationTaskPanel`：经纬度+地图选点+手绘航路端点、UTC 出发时间、船舶、固定三目标、real_only/合成研究、种群/代数/seed；合成提示。
- `RouteComparisonPanel`：表格 + ECharts Pareto 散点（x 能耗、y 风险、tooltip 航时）；只绘制真实候选；采纳按钮。
- `RiskAnalysisPanel`：综合/冰/深/雾/风/浪切换、风险格加载、地图点选、单格环境值/分项/质量/来源/通航/阻断原因；区域风险评估（bbox+time+vessel+policy）。
- `PlanningResultPanel`：状态/进度/错误码/取消/历史；快照时间与当前环境时间不一致提示；缺测字段。会话 #30 起不再显示合成/模拟/安全横幅；错误信息拼接后端可操作细节（超时秒数、缺失字段、阻断原因）。
- 采纳/编辑：`RouteDraft` localStorage 仍用 v1 key，payload 升 v2；`coerceRoute` 保留 adopted/source/snapshot；手动内容不受影响；采纳后切回手动并 fit；修改后 `routeMetricsStale` 显示“已修改，需重新计算”，不把旧指标当当前值，可一键重评。

**测试**：前端新增 `mapEnvironment`（双投影箭头）、环境/船舶面板、`routePlanning`（hash/stale）、navigation store、planning layers、planning panels、MapWorkspace 规划不变量；全套 **28 files / 385 tests passed**；`vue-tsc` 零错误；生产构建通过。

### 8.8 批次 E：部署、E2E、回归与交付

**部署**
- `deploy/compose.yml`：backend + worker 均挂载 `${NAVIGATION_DATA_HOST_PATH:-../data/navigation}:/data/navigation:ro`；
  worker 增加 `${ICE_DATA_HOST_PATH:-../data/ice}:/data/ice:ro`；`PLANNER_RESULT_ROOT=/data/storage/navigation/plans`
  位于共享存储；`NAVIGATION_*`/`PLANNER_*` 环境变量；不新增服务。
- `deploy/.env.example`、`backend/.env.example` 同步；`data/navigation/{bathymetry,ice,wind,current,wave,planning}/README.md`
  提交，`.gitignore` 忽略实际 NetCDF/JSON/NPZ 数据。合成 fixture 生成到 `sample-data/navigation/`（gitignored）。
- `docker compose --env-file .env.example config` 通过；Nginx `^~ /api/` 已优先，无需改。

**合成研究 E2E**
- `scripts/navigation/generate_synthetic_fixtures.py` 生成五字段 NetCDF + `navigation_manifest.json`
  （全部 `quality=synthetic`）。
- `scripts/navigation/e2e_synthetic.py`：真实 FastAPI/DB/worker processor/planner/risk/evaluate 链；
  环境 query → 船舶 → allow_synthetic_research 计划 → D*/NSGA → 3 条 Pareto → 风险格 15,731 单元
  → evaluate-route；推荐与重评 risk/energy/time 完全一致；real_only 负例被拒绝并返回
  `ENVIRONMENT_DATA_MISSING`；risk_only 区域任务完成。全链 17.0s，worker 10.7s。
- `scripts/navigation/e2e_ui_smoke.cjs`（Playwright，临时安装不写入依赖）：登录/项目地图/智能规划/
  完成/候选/采纳/编辑/stale/重评/风险格通过；截图 `output/navigation-e2e-{result,stale,risk}.png`。

**测试与回归**
- 后端 **277 passed**；前端 **28 files / 385 tests passed**；typecheck/build 通过；`ruff` 新增代码通过。
- 未运行真实 GeoServer/GWC/S-57 批量导入与浏览器 44 项手工清单（本环境无真实服务/数据）；
  报告中不得宣称真实服务回归通过。D*/NSGA/环境/风险/规划 API/worker 均有自动化测试。

**性能 / 限制**
- 合成全网格规划 10.7s；规划 worker 串行（`PLANNER_MAX_CONCURRENT_JOBS=1`），会延迟导入；
  风险格按 gzip 存盘、API bbox/stride 裁剪；环境矢量 ≤600 点/视口、防抖/abort。
- 无真实环境数据；真实 Provider/规划未验证。详细限制见 `docs/plans/v3-integration-final-report.md`。

### 8.9 后续修复：合成参数、进度、任务列表、抽屉对比度

- **合成环境参数可见/可改**：`PlanningCreateRequest.syntheticOverrides` 支持
  `depthM/iceConcentration/iceThicknessM/windSpeedMs/windDirectionFromDeg/currentSpeedMs/
  currentDirectionToDeg/waveHeightM/wavePeriodS/waveDirectionFromDeg`；仅
  `allow_synthetic_research` 有效，API 校验字段和范围。任务面板在合成策略下展示算法所需字段，
  选择合成策略自动“从起点读取当前环境值”，也支持手动读取和逐项修改；环境查询在合成研究模式下
  对缺失字段使用与规划器相同的确定性 gap-fill 并标 synthetic，因此输入框显示实际值而非仅有“自动”。
  空值表示不覆盖；覆盖应用到全规划区并逐格标 `synthetic` + `research-override`。
- **进度不再停在 10%**：Provider 采样按 1000 点分块，进度 2→10…55→65（环境采样）→95（结果保存）
  →100；Worker 阶段显示“环境采样/多目标优化/结果保存”。取消检查在分块间执行。
- **随机/极端合成值不会无限拖死规划**：D* Lite 增加 `PLANNER_MAX_SEARCH_EXPANSIONS`（默认 200000）
  搜索上限；超限返回 `NO_FEASIBLE_ROUTE`（保留风险栅格），不再以 `PLANNER_TIMEOUT` 结束。
- **规划历史管理**：`planning_runs.title`（Alembic `0006_navigation_run_title`）；API
  `PATCH /plans/{planId}` 重命名、`DELETE /plans/{planId}` 删除（仅终态；删除风险栅格文件与级联
  航线）；结果面板历史项提供重命名/删除按钮，选中项为深色文字+浅青底+左边框。
- **历史时间**：后端把 SQLite 丢失时区的 datetime 统一补为 UTC；前端历史列表使用浏览器本地时区
  `toLocaleString('zh-CN')` 展示，不再直接显示 UTC ISO 片段。
- **风险格地图可见性**：S-57 `optional_other` bundle zIndex 从 100 调整为 45，避免可选海图图层
  盖住风险格/环境/规划航线；风险页打开时若任务已完成会自动加载 combined 风险格，`setGrid` 显式
  设置图层可见。
- **抽屉配色**：智能规划工作台使用亮色抽屉主题；新增面板/历史/风险详情/表单输入改为深色文字+
  浅色背景，修复选中行浅青底上浅色文字不可读；环境图层（左侧深色面板）保持原暗色样式。
- 测试：后端 **280 passed**（新增重命名/删除、覆盖校验、覆盖落地、合成查询补值等）；前端
  **386 passed**；typecheck/build 通过；API E2E + Playwright UI smoke 通过。

### 8.10 会话 #30：智能规划超时、环境叠加首载与冰情性能

**智能规划超时/失败根因**
- `CARRA2WindProvider` 与 `WAMWaveProvider` 的 `sample()` 每个格点都调用 `coverage()`，后者对完整 2-D/1-D 坐标数组执行 `nanmin/nanmax`。真实数据规模下实测单次约 6 ms；全网格 15,731 格 × 风/浪两字段会产生数百秒 CPU，直接撞上 `PLANNER_TIMEOUT=300s`。
- `GEBCOBathymetryProvider.sample()` 在越界/NoData 分支也重复计算 coverage；`IceProvider` 的 `polar_gis` 分支每个格点调用 `IceService.info()` 并新建 `Transformer`，同样把环境采样拖到分钟级。
- **修复**：coverage 作为网格元数据只计算一次并缓存（月份/文件切换时失效）；`sample()` 只读缓存；GEBCO 先读坐标轴再决定是否加载 elevation；冰情 Provider 缓存 info 60s 并复用 Transformer。基准（1200×1200 风/浪、600×600 流、1200×1200 冰/水深，15,731 格）：环境采样合计 **19.78s**（风 7.24s、浪 3.60s、流 3.16s、冰 1.54s、水深 1.28s），加 NSGA-III 后仍远低于 300s。
- **错误可操作性**：worker 的 `PLANNER_TIMEOUT / ENVIRONMENT_DATA_MISSING / NO_FEASIBLE_ROUTE` 统一输出中文原因与建议；`real_only` 在 API 入队前探测起点五字段，缺失立即 422 并提示改用“合成研究数据”；前端错误标签保留后端细节。

**正确使用方式（写给用户/运维）**
1. 无真实 GEBCO/NetCDF 环境文件时，数据策略选择**合成研究数据**；`real_only` 需要航线沿途冰/风/流/浪真实值齐全。
2. 起终点必须落在东北航道规划网格内（60°–90°N、30°E–191°E）且位于可航水域；默认 `120,75 → 122,77` 可直接得到候选航线。
3. 合成覆盖优先留空，由 Provider/确定性 gap-fill 自动处理；水深覆盖不得低于船舶所需水深（雪龙2 为 9.85 m）；过高冰密集度/冰厚会把整片区域判为不可通行。
4. 默认 pop36/gen20 已足够；任务由**独立 worker** 串行执行，需确认 worker 服务运行。规划失败时结果面板会保留风险栅格，可切换“风险”页查看阻断原因。

**环境叠加首次进入无信息**
- 后端：冰情 API 与导航 `IceProvider` 共享同一个 `IceService`，避免两份全目录扫描/预热；`/info` 结果按目录变化缓存；FastAPI `lifespan` 启动后台 `ice-prewarm` 线程，在用户进入项目前完成元数据扫描与默认网格预热（失败只降级冰情显示）。
- 前端：`/ice/info` 与 `/navigation/environment/sources` 在 `onMounted` 读取 map-config 后**立即**启动，不再等待默认数据集加载与 `buildMap()`；超时从 30s 提升到 120s；面板首次打开/失败后再次打开会重试；菜单状态区分“加载中/待加载/无数据/不可用”。
- 冰情面板与菜单不再把“尚未返回”误显示为“无数据”。

**冰情图层加载**
- `info()` 只扫描一次并缓存；`warm_default_grid()` 每实例只启动一次；共享实例使规划与环境面板复用同一份 26M 单元网格缓存。
- 瓦片 PNG 改用 `compress_level=1`；GEBCO 瓦片同步调整。
- 前端瓦片仍复用 `TileRequestQueue + LRUTileCache`，日期/投影切换沿用代次中止。

**提示文案清理**
- 移除合成/模拟/安全类黄色提示与声明：智能规划辅助决策原型、含合成环境数据、当前航路仅用于功能模拟、天气演示数据、AIS 演示提示、冰情“非认证/不可替代”说明、管理概览“非认证航海信息系统”、地图页“非认证航海显示”等；保留数据加载失败/缺测/操作失败等真实错误提示。

**验证**
- 后端新增 coverage 不重算、`/info` 缓存、共享实例 3 个回归测试；全套后端通过。
- 前端 29 files / 389 tests passed；`vue-tsc` 零错误；`npm run build` 通过；合成 E2E（含 real_only 422 负例）通过。

### 8.11 会话 #31：瓦片生命周期、底图恢复与 S-57 航道专题

#### 8.11.1 统一瓦片生命周期（任务 A/B 共同根因）

- 根因：OpenLayers 的 `ImageTile.load()` 先置 `LOADING` 再调用自定义 `tileLoadFunction`；全局 `TileQueue` 仅在 `LOADED/ERROR/EMPTY` 时释放 loading 槽位，且 Map 全局上限 16。旧的海冰、S-57、环境水深 loader 在代次/来源切换时 abort 后直接 return，从不设置终态，槽位逐步泄漏；累计到 16 后**所有瓦片（包括原生加载的底图）停止加载**，只有投影切换（清 renderer tile cache）或刷新页面才能恢复。
- 新增 `frontend/src/utils/tileLoader.ts`：
  - `TileLoadLifecycle` 统一持有 controllers/timers/tiles/cleanups；`deactivateTileLoadLifecycle` 中止请求、清定时器、移除 image 监听/objectURL，并对未终态瓦片调用 `cancelTile`。
  - `cancelTile` 仅在 `IDLE/LOADING` 时置 `TileState.EMPTY`（主动取消/源替换，释放全局槽位且不触发 `tileloaderror`）；`failTile` 置 `ERROR`（真实失败）。绝不覆盖 `LOADED/ERROR`。
  - `createQueuedTileLoadFunction`：LRU 缓存校验（size/type）、Content-Type 校验、429/408/500/502/503/504/Timeout/Queue overflow 有界重试、404 可按来源配置为 EMPTY/ERROR、204 EMPTY、objectURL revoke、decode 超时、deactivate 时立即释放退避中的瓦片。
  - `createNativeRetryTileLoadFunction`：底图原生图片加载，失败通过 `tile.load()` 有限重试，最终失败保持 ERROR；超时/失活取消。
- `TileRequestQueue` 增加 high/normal 双通道、公平调度（高优先连续 3 个后插入 1 个 normal）、可选超时、同步 fetch 抛异常时的 inFlight 释放；海冰瓦片使用 high 优先级。
- `tileDiagnostics.ts` 记录有上限的诊断事件/计数（started/settled/cancelled/failed/retries/stuck、队列与缓存统计）；URL 只保留 path+date；DEV 或 `VITE_TILE_DIAGNOSTICS=true` 开启，开发环境暴露 `window.__polarTileDiagnostics` 与 `__polarMapTileQueueStats()`。生产关闭。
- S-57/环境水深 loader 最小修补：所有 abort 路径调用 `cancelTile`、失败调用 `failTile`，追踪/清理重试定时器，缓存毒化删除、image error revoke、decode 超时；`EMPTY` 不触发 tile 事件，因此 detach/suspend/bundle 失败路径同步复位 pendingTiles/loadStateTimer/warming 状态，避免卡在“加载中”。

#### 8.11.2 海冰时间轴

- `useIceOverlay` 改为 per-field + per-source lifecycle：源 key = `field|date|projection|visible`；只有 key 变化的字段替换 Source，切换厚度不再 abort 密集度。
- 时间轴输入 120ms debounce；日期变化立即 deactivate 旧 lifecycle（旧源已加载瓦片仍短暂显示），防抖结束后替换新源；`loadInfo` 的 finally 与 watcher 通过 key 去重。
- `/ice/info` 失败保留上一次可用元数据，不再清空工作图层；面板提供“重新加载冰情”；瓦片最终失败计数 + 独立重试。
- 修正 alignment 旧请求清除新结果、厚度-only hover 不查询的问题。
- 后端 `IceService` 增加全局冷网格加载信号量 `ICE_MAX_CONCURRENT_GRID_LOADS`（默认 2）：per-date single-flight 仍保证同一日期只装载一次；不同日期并发冷加载受上限保护，避免快速切换在服务端堆积多个 26M 单元网格（实测可把容器推到 4.6GB/100% CPU）。共享实例 key 包含该参数，API/导航 Provider 复用同一实例。

#### 8.11.3 底图稳定性

- WMTS 按 `baseMap.crs` 选择匹配的 `TileMatrixSet`，优先 overview 标识；`SupportedCRS` 归一化并校验 `options.projection`；无法唯一确定时明确失败并允许手动重试，不再盲取 `Layer[0]/TileMatrixSetLink[0]`。
- Capabilities 获取 3 次重试（500ms/1500ms、15s 超时）；失败记录 `baseMapConfigErrors`，可“重试”重建图层。
- 底图使用 native retry loader；健康统计由 loader 的**最终**成功/失败回调驱动，`source.refresh()` 仅在当前可见底图错误率达到阈值时触发，冷却 30s、最多 3 次；手动“重新加载当前底图”重置统计并 refresh。
- 按 CRS 记忆底图选择（`activeBaseMapByCrs`）；3413 无可用底图时显示提示，不强行使用 3857 瓦片；`setOverviewVisible` 不再覆盖用户选择。
- 网络恢复 `online` 事件（1s debounce）重试冰情/失败底图。
- 卸载清理：`disposeAllBundles`、map 事件 `unByKey`、reconcile/evict/layerSearch/online/bundle retry 定时器、底图 lifecycle/source/图层；`map.dispose()`。修复 bundle registry 跨会话泄漏与重挂载污染。
- S-57 suspended 选中图层可被 LRU 驱逐/“清理休眠”（保留 selected 状态，重新入视口再 attach），使 `SMART_MAX_ATTACHED_WMS_LAYERS` 生效。
- 附带修复 `s57_basemap._collect_basemap_layers` 从 `metadata_json["s57"]["objectClass"]` 读取对象类（兼容旧顶层键），避免概览底图收集不到图层。

#### 8.11.4 S-57 航道专题

- 新增独立 taxonomy `backend/app/services/s57_waterway_catalog.py`，不改动既有 `CORE_CHART/NAVIGATION_RECOMMENDED/OPTIONAL_THEMATIC`：
  - 主类别：FAIRWY/RECTRC/NAVLNE/TWRTPT/CANALS（航道与推荐路线）、TSSLPT/TSSBND/TSEZNE/TSSRON（交通分隔制）、CTNARE（限制/管制）、DRGARE（航道环境）；辅助类别 RESARE/ACHARE/BERTHS/PILPNT/DEPARE/DEPCNT/SOUNDG 单独标记，不当作航道。
- `s57_waterways.py` 通过 `ProjectLayer→Layer→DatasetVersion→Dataset` 解析项目当前有效版本，强制 available/queryable；批量内省实际列/主键/几何列；跨图层 `UNION ALL` 搜索，关键字/bbox 全部绑定参数，bbox 支持跨 180° 经线拆分，稳定排序 + LIMIT/OFFSET，PostgreSQL statement_timeout；opaque 复合 ID=layer_id+feature_key；详情返回原始属性与中文标签（CAT*/STATUS 等保留原始代码，不臆造枚举翻译；DRVAL 注明不是保证水深）。
- API：`GET /projects/{id}/s57-waterways/catalog`、`POST .../search`、`GET .../{featureId}`；`project_or_404(include_unpublished=False)` + 当前版本约束；不新增迁移。
- 前端 `useS57Waterways` + `S57WaterwayPanel` + 独立 VectorLayer（zIndex 78）：搜索/类别/当前视口/分页/显示/定位/详情；只叠加有限结果，点选并入既有唯一 `singleclick`，仅“地图点选”模式且面板展开时优先；不进入 routesStore、Draw/Modify/Select、runtimeLayers/bundle。
- 真实样本未见 FAIRWY/RECTRC/NAVLNE/DRGARE；已实查 CANALS/TSSLPT/TSSBND/TSEZNE/TWRTPT/TSSRON，真实 C110408A 的 CANALS `OBJNAM=Jinghang Yunhe`、`NOBJNM=京杭运河` 可检索/详情/定位；US1AK90M 基础+`.001` 更新链导入为 v2，TWRTPT=6 可检索。

#### 8.11.5 真实 S-57 导入修复（验证中发现）

真实 ENC 导入暴露并修复了三处既有导入问题：
1. `LAUNDER=YES` 后 PostgreSQL 表名为小写，旧代码按原对象类大写 `"DSID"` 移动表，报 relation 不存在；改为 `source_name.lower()`。
2. 非空间对象类（DSID/C_ASSO/C_AGGR）没有 `geom` 列，旧代码对所有表建 GIST 索引导致整个 cell 导入失败；仅 `has_valid_geometry` 时建索引。
3. 多 cell/对象类移动进 `geo` schema 时，主键约束/索引/序列名（如 `dsid_pkey`、`buaare_geom_geom_idx`、`dsid_ogc_fid_seq`）跨表冲突；导入时先重命名为 `<table>_pkey/_src_idx_N/_seq_N`，序列脱离 ownership→迁移→恢复 ownership，再移动/重命名表。

#### 8.11.6 验证与限制

- 前端 `typecheck/build` 通过；39 文件 / 459 tests passed。
- 后端 304 tests collected（303 passed + 1 需 `S57_WATERWAY_TEST_DATABASE_URL` 的 PostGIS 集成测试；配置后通过）；ruff 新增/修改文件通过。
- 真实 S-57：C110408A（CANALS/CTNARE 等）、GB1DD000（TSSLPT/TSSBND/TSEZNE）与 US1AK90M 基础+`.001` 更新链（TWRTPT=6，v2）导入成功；
- 真实项目搜索曾因 PostgreSQL 并行查询使用 64MB 默认 `/dev/shm` 报 `DiskFull: could not resize shared memory segment`；已为 postgres 增加 `shm_size: 1gb`，并在 waterway 搜索会话中关闭并行查询（`max_parallel_workers_per_gather=0`），500 修复；前端“航道专题”徽标只统计主类别，不再把 DEPARE/DEPCNT/SOUNDG 等辅助要素计入（真实项目 301 vs 旧 11210）。catalog 计数 CANALS=2、TSSLPT=8、TSSBND=6、TSEZNE=4、CTNARE=3；名称/属性/几何/bbox/详情均来自真实表。
- 隔离项目浏览器：连续 100 次日期切换后 `q.loading=0、stuck=0`；3857/3413 来回切换后仍为 0；抖动底图 503 自动重试恢复；无 pageerror。
- 30 分钟 soak 已完成：1804s，结束时 q.loading=0、stuck=0、pageerrors=[]（`output/soak-30min.log`）。
- 未验证：真实 GWC WMTS 3413 matrix set 未在本次环境配置成功（GWC capabilities 仅 EPSG:4326），作为残留；公共第三方底图限流仅以本地 503 mock 验证。

### 8.12 会话 #32：WGS84 椭球测距、航道快照与图层内联图例

#### 8.12.1 WGS84 椭球测距

- 新增 `frontend/src/utils/geodesicDistance.ts`，依赖 `geographiclib-geodesic@^2.2.0`（官方 GeographicLib JS，MIT，Karney 椭球测地线，含 TS 类型）：
  - `geodesicDistanceWGS84(pointA, pointB)`：入参 WGS84 `[lon, lat]`，返回米；非法坐标返回 `NaN`，同点返回 0，跨 180° 由库内部归一化。
  - `measurePolylineLength(points)`：相邻航点逐段椭球反算求和，少于 2 点返回 0。
- `mapMeasure.ts` 的折线距离由 `ol/sphere.getDistance`（球面 haversine，R=6371008.8 m）改为上述函数；`formatMeasureResult` 折线文本追加“· WGS84 椭球测地线”。面积仍用 Van Oosterom–Strackee 球面算法，`mapRoute.ts` 航段里程仍用球面模型（避免改变航线规划显示）。
- WGS84 真值、`MeasureDraft`、投影重建、Draw 交互与状态栏位置均未改变；切换 3857/3413 仍由 WGS84 真值重算，数值不变。

#### 8.12.2 S-57 航道快照

- `s57_waterways.py` 新增：
  - `WaterwayLayerRef.version_id/content_hash`（默认值，用于成果溯源）；`resolve_waterway_layers()` 填充。
  - `build_waterway_export_batch_sql()`：按图层键集分页（`WHERE key > :after_key ORDER BY key LIMIT :limit`），复用 keyword/bbox 条件；SELECT 真实几何 `ST_AsGeoJSON(ST_Transform(geom,4326))` 与原始属性 `to_jsonb(w.*) - geom`；所有值绑定参数。
- 新增 `backend/app/services/s57_waterway_export.py`：
  - 复用 `resolve_waterway_layers()` + `_selected_codes()`，逐图层分批读取全部匹配记录（默认 500/批，单次上限默认 20000）。
  - 要素保留真实几何类型，properties 含 `objectClass/objectName/objectNameZh/group/groupNameZh/auxiliary/sourceLayerId/sourceDatasetId/sourceVersionId/sourceCell/originalAttributes` 等；坐标 EPSG:4326。
  - 原子写盘：临时目录 `.<snapshotId>.tmp/` 写入 `waterways.geojson` + `manifest.json` 后 `os.replace` 重命名为最终目录；默认根 `<STORAGE_ROOT>/navigation/waterways/<projectId>/<snapshotId>/`（Compose 中为共享卷 `/data/storage/navigation/waterways`）。
  - manifest 含 snapshotId/projectId/name/createdAt/crs/featureCount/truncated/objectClasses/sourceDatasets/sourceVersionIds/sourceContentHashes/filters/schemaVersion/warnings/geojsonSha256。
  - 列表/详情比较 manifest 与当前 `version_id` 集合，输出 `stale`；旧成果不覆盖、仍可下载。
- API（固定路径在 `/{feature_id}` 之前）：`POST .../snapshots`（201）、`GET .../snapshots`、`GET .../snapshots/{id}`、`GET .../snapshots/{id}/download`（`application/geo+json`）。
- 地图专题总览：新增 `POST .../preview`（`S57WaterwayPreviewRequest/Response`），复用同一套 `_resolve_usable_layers()/_extract_features()` 键集提取，返回与搜索结果同形状的要素、`groupCounts/objectClassCounts`、`truncated`、`warnings`；不写文件。默认上限 `S57_WATERWAY_PREVIEW_MAX_FEATURES=2000`。
- 前端：`useS57Waterways` 增加 `loadSnapshots/createSnapshot/downloadSnapshot` 与 `showOverview`；`S57WaterwayPanel` 增加“地图专题图例”+“在地图显示选中类别”按钮、保存对话框与已保存抽屉。总览把返回要素写入独立航道矢量图层，按组颜色渲染并自动 fit；图例颜色与 `mapS57Waterway` 的 `waterwayGroupColor()` 同源。
- 成果入口位于目录状态判断之前、始终显示，确保当前项目没有可查询航道图层时仍能访问历史快照；不进入航路 store。保存对话框与详情/成果抽屉均 `append-to-body`，避免被左侧窄面板裁剪。
- 布局：侧边专题展开时 `.layer-panel` 加 `has-side-panel`，图层列表限制为 22vh；`.waterway-panel` 使用 `flex:1 1 0/min-height:0/overflow-y:auto` 内部滚动，footer 固定可见；地图图例与“在地图显示选中类别”前置并 `position:sticky`，解决小屏/低分辨率下必须缩小浏览器才能看到下方控件的问题。Playwright 已在 1440×900、1280×720、1024×768 验证。

#### 8.12.3 图层内联图例

- `GET /layers/{id}/legend` 保持 `url` 不变，新增 `objectClass`、`geometryType`、`fallback`（来自 `s57_styles.preset_for_object_class`：geometry/color/fillColor/opacity/label；无预设为 null）。
- 新增 `frontend/src/utils/s57LayerLegend.ts`：模块级缓存，key=`layerId:styleName:objectClass`；失败删除缓存以便重试。
- 新增 `frontend/src/components/S57LayerLegend.vue`：仅在用户展开图例时请求；优先显示 GeoServer GetLegendGraphic `<img>`（1–2px 空图或错误时降级）；有预设时用 s57_styles 颜色/几何绘制简化 swatch；无预设只显示名称/代码并提示“无可用图例/预设符号”；说明文案明确图例为样式示意、非实时航行状态。
- `MapWorkspaceView.vue` 图层状态行增加“图例”按钮，行下渲染内联图例；保留原有“图例与元数据”抽屉。图例请求与 TileRequestQueue/Render Bundle/GWC 独立。
- `s57ObjectNames.ts` 新增 `s57ObjectDescriptions`（常见类别用途说明）与 `s57ObjectDescription()`。

### 8.13 会话 #34：S-57 专题提取与航道完整性诊断

#### 8.13.1 后端模块

- `app/services/s57_project_layers.py`：不按航道类过滤的通用项目 S-57 图层解析。连接 `ProjectLayer→Layer→DatasetVersion→Dataset`，只取项目当前版本/未删除/`available` 状态；分批 `load_table_metadata()`，无 200 层截断；返回 table/key/fields/geometry/extent/featureCount/dataset/version/cell/contentHash，供航道诊断与专题导出复用。
- `app/services/s57_waterways.py`：
  - `resolve_waterway_layers()` 移除 `candidates[:s57_waterway_max_layers]`；改为按 `S57_WATERWAY_INTROSPECTION_BATCH_SIZE`（默认 200）分批遍历全部候选。`WaterwayResolution` 新增 `candidate_layer_count/resolved_layer_count`；`truncated` 固定 false（保留字段兼容）。
  - 新增 `build_waterway_count_sql()` / `_build_waterway_union_sql()`；`source_cells` 过滤；`normalize_source_cells()` / `layer_matches_source_cells()`。
  - `/preview` 改为按对象类公平分配预算（最多 2 轮），每类独立 cursor；响应新增 `matchedTotal/returnedCount/hasMore/classHasMore/nextCursors/classMatchedTotals/countComplete/truncatedLayers`；`total` 兼容字段在可计数时等于 matchedTotal。
- `app/services/s57_waterway_export.py`：`_extract_features()` 读取 `max_features+1`，精确判断截断；新增 `encode/decode_preview_cursor()`、`_extract_class_page()`、`_class_matched_total()`；快照文件格式不变（仍 `waterways.geojson + manifest.json`）。
- `app/services/s57_waterway_diagnostics.py` + `GET /projects/{id}/s57-waterways/diagnostics`：
  - 统计当前项目已关联 Cell/航道层/可检索/可渲染/要素数/计数完整性；按 Cell 返回 dataset/version/object classes/bbox/coverageSource/coverageVerified/reasons。
  - 覆盖 bbox 优先 M_COVR（若存在 `catcov` 字段仅取 CATCOV=1）`ST_Extent(ST_Transform(geom,4326))`；否则图层 `metadata_json.s57.extent` 并集；不把 bbox 说成完整测深覆盖。
  - `REGIONS`：挪威/巴伦支海入口、喀拉海、拉普捷夫海、东西伯利亚海、楚科奇/白令；状态枚举 `imported_enc_coverage/only_basemap_or_auxiliary/no_waterway_objects/no_enc_imported/unknown`；输出 `northeastPassage.hasGap/missingRegions/summary`。区域是研究对照范围，不是法定边界。
  - `REFERENCES` 记录 USNIC/PAME/Arctic Portal/IHO/GDAL URL、scope、checkedAt=2026-11-16；不返回 SQL/表名/凭据。
- `app/services/s57_thematic_catalog.py`：
  - 分类 depth（SOUNDG/DEPCNT/DEPARE）、depth_supplement（DRGARE/SWPARE/UNSARE/M_QUAL）、hazards（OBSTRN/WRECKS/UWTROC）、other（动态实际导入空间类）。
  - SOUNDG 通过 `ST_NDims/ST_ZMin/ST_ZMax` 诊断几何维度；`depthPreserved=false` 时警告，不用 DEPARE 范围替代。
  - `featureCount` 明确是 S-57 **feature 条数**，SOUNDG 一条 MultiPoint 可含多个测深点。
  - 大项目目录计数使用 `_fill_layer_counts()`：50 张表/批 `UNION ALL COUNT(*)`，每批 savepoint/rollback；避免 5,781 张表在一个事务中耗尽 `max_locks_per_transaction`。`s57_project_layers.py` 本身不再逐表自动 COUNT，缺失计数明确为 unknown。
- `app/services/s57_thematic_export.py` + `app/api/s57_thematics.py`：
  - 目录 `<STORAGE_ROOT>/navigation/s57-thematics/<projectId>/<exportId>/<category>/<CLASS>[_CELL].geojson`；按单文件 50k 分卷 `.partNNN`；`preview.geojson` 每类≤50/总计≤500；`manifest.json` 原子 temp→final。
  - 流式键集分批（默认 500/批），Feature 保留真实 GeoJSON（含 Z）、`originalAttributes`、`sourceLayer/Dataset/Version/Cell`、`geometryNdim`、`sourceKeyField/FeatureKey`；SOUNDG 增加 `depthSources/depthUnits/depthSign/verticalDatum/depthPreserved`。
  - 上限：单类 300k、总计 1M、时间 300s；`limit+1` 探测，确认真截断才 `truncated=true`；`complete=false` 的可下载成果明确列 `truncationReasons`；不可用层列 `skippedLayers`，读取错误整体失败并清理。
  - 列表/详情按当前项目全部 S-57 版本计算 `stale`；下载单文件 GeoJSON、多文件 ZIP（含 manifest），支持 `?file=`；`preview` 端点仅返回样例。
- `app/cli.py`：只读 `s57-inventory --root <dir> [--output <json>]`，调用 `ogrinfo -ro -so -al -json` 检查 `.000`/更新链/对象类/数量/extent；不导入、不访问 DB。

#### 8.13.2 分类修正

- `s57_layer_catalog.py`：`RCRTCL` 由“雷达测距线”改为“推荐航线中心线”，`RCTLPT` 由“雷达控制点”改为“推荐通航车道部分”，并从 `_NAVIGATION_AIDS` 移入 `_ROUTING`；新增 `DWRTCL=深水航道中心线`、`DWRTPT=深水航道部分` 到 `NAVIGATION_RECOMMENDED/_ROUTING`。依据 IHO S-57 UOC / S-101 DCEG（DWRTCL=deep water route centreline，DWRTPT=deep water route part，RCRTCL=recommended route centreline，RCTLPT=recommended traffic lane part）。
- `s57_waterway_catalog.py`：新增上述四类（RCTLPT 默认不选，面/点状推荐车道，不是连续中心线，也不属于 TSS）；`TSSLPT` 改为“分道通航制车道部分”；补充 VALDCO/VALSOU/WATLEV/EXPSOU/TECSOU/VERDAT/LNAM 原始代码标签与说明，不翻译枚举值。

#### 8.13.3 前端

- 新增 `api/s57Thematics.ts`、`types/s57Thematics.ts`、`composables/useS57Thematics.ts`、`components/S57ThematicDialog.vue`、`utils/mapS57Thematic.ts`、`composables/useS57ThematicPreview.ts`。
- `MapWorkspaceView.vue`：左侧 footer 增加“专题提取”入口，打开 `append-to-body` 对话框；独立样例预览 `VectorLayer`（zIndex 79，位于航道 78 与规划 90 之间）；投影/卸载清理；点击优先级 `point-pick→绘制/测量→风险格点→天气/识别→手绘航路→规划候选→航道要素→默认`。
- `useS57Waterways.ts`：`loadOverviewPage(append)`/`loadMoreOverview()`；按 feature id 合并去重；filter key 防旧 cursor 跨筛选；6,000 浏览器叠加预算；`overviewMatchedTotal/overviewHasMore/classCursors/classHasMore/classMatchedTotals`；`visibleGroups/visibleCount`；`sourceCellFilter`；`loadDiagnostics()`；详情 generation 防旧响应。
- `S57WaterwayPanel.vue`：顶部统计（ENC Cell/可检索层/匹配/已加载/可见/未加载）、覆盖缺口警告、诊断抽屉（Cell 表+区域状态+参考）、加载更多、分组开关、详情测地线长度（仅线状，MultiLineString 逐段）、复制经纬度/来源、同 Cell 其他对象；空值“未提供”。
- `mapS57Waterway.ts`：style 接收 `resolution`，低缩放降低线宽/点半径/填充透明度；面/线真实几何不变，不把 TSS 面线化拼接。
- `waterwayViewportBbox()`：经度归一化，跨 180° 允许 west>east，后端拆分；近全球视口返回全经度。
- 专题成果不进入 runtimeLayers/bundle/route store；航道快照保存/下载逻辑不变。

#### 8.13.4 配置与成果上限

- 新增 `S57_WATERWAY_INTROSPECTION_BATCH_SIZE=200`、`S57_WATERWAY_QUERY_WARNING_LAYERS=500`；`S57_WATERWAY_MAX_LAYERS` 保留为 deprecated，不再用于截断。
- 新增 `S57_THEMATIC_ROOT`（默认为 `<STORAGE_ROOT>/navigation/s57-thematics`）、`S57_THEMATIC_MAX_FEATURES_PER_CLASS=300000`、`S57_THEMATIC_MAX_FEATURES=1000000`、`S57_THEMATIC_MAX_FEATURES_PER_FILE=50000`、`S57_THEMATIC_BATCH_SIZE=500`、`S57_THEMATIC_EXPORT_TIMEOUT_SECONDS=300`、`S57_THEMATIC_PREVIEW_PER_CLASS=50`、`S57_THEMATIC_PREVIEW_MAX_FEATURES=500`。
- `deploy/compose.yml` 的 postgres 增加 `command: ["postgres", "-c", "max_locks_per_transaction=4096"]`；大型 ENC 项目一次查询可跨数百张 `geo.*` 表。
- 专题导出每处理一个图层前 `db.rollback()` 并重设 `statement_timeout`，释放上一张表的 AccessShareLock；诊断每个 Cell 后 rollback；无新增数据库表/迁移。

#### 8.13.5 验证与限制

- 后端定向 49 tests passed；全量 pytest 为 **327 passed, 1 skipped**（PostGIS 集成测试按环境跳过）；ruff 本轮文件通过。前端 typecheck 通过；**44 文件 / 490 tests passed**；build 成功。
- **真实栈验证**：`polar-gis` 项目 188 Cell/5,781 图层/1,279 航道层（RU=113 Cell/306 层）；修复后 catalog 61,888 条、preview `matchedTotal=1690`、Kara bbox preview 405 条；diagnostics 五个区域全部 `imported_enc_coverage`、`hasGap=false`、188/188 Cell 有 M_COVR bbox；thematic catalog 5,487 可提取层，SOUNDG 183 层/1,583 条且全部 3D；真实导出 RU2M6WF1 886 条/6 文件，SOUNDG 2,058 个 3D 点，manifest SHA 匹配；现有 FAIRWY 快照 13 条且包含 RU Cell。
- 本轮未做浏览器点击级 E2E；前端 typecheck/tests/build 已通过。用户提供的 `output/航道成果_2026-11-11_04_51.geojson` 是独立文件（无 manifest），其 269 条结果对应旧的 200 层截断状态；本轮不修改该文件。
- 专题成果受配置上限约束；触发时明确 `complete=false/truncated=true`，可按 Cell/类/视口缩小范围。SOUNDG 实测 3D，无需源文件回退；若其他环境为 2D，按 manifest 警告处理，不伪造深度。

#### 8.13.6 航道面板可读性与免责提示清理

- `S57ThematicDialog.vue`：删除顶部安全/免责横幅、专题 `semantics` 展示、预览“非完整成果”提示；保留截断/未知/2D 深度等事实性警告。
- `S57WaterwayPanel.vue`：删除“交通分隔制 ≠ 推荐航路；局部 S-57 要素 ≠ 完整规划航线”和长度“不代表整条东北航道里程”；动作卡前置到类别前，类别/辅助/分组显示在前，颜色图例在后并 `position: static`；快照动作 2×2、统计 3×2、分组 2 列；字号整体提升。
- `S57LayerLegend.vue`/`s57ObjectNames.ts`：删除“不代表实时航行状态或已验证的安全通道”“不表示保证水深”等文案。
- 后端 `s57_thematic_catalog.py`/`s57_thematic_export.py`/`s57_waterway_diagnostics.py`/`s57_waterway_catalog.py`：同步清理 semantics、references/notes、region note、summary、类目描述中的安全免责措辞；保留 M_COVR/图层 extent 近似、数量未知、截断等事实说明。
- `MapWorkspaceView.vue`：`has-waterway-panel` 打开航道专题时隐藏左侧图层过滤器/图层树，关闭后恢复；航道专题与冰情/环境面板互斥，避免侧栏高度竞争。`.layer-panel` 内部仍 `overflow:hidden`，`.waterway-panel` 内部滚动，footer 固定。
- Headless Edge 1440×960：航道面板 226×669px，首屏 13/15 类别行可见；`scrollWidth=clientWidth`；footer 在面板下方且命中 footer 按钮；页面无被删除的免责文案。截图：`output/ui-waterway-20261116.png`、`output/ui-waterway-scrolled-20261116.png`。
- 平台级 ECDIS/法律声明、演示数据声明与数据质量/截断/未知提示保留。

#### 8.13.7 专题提取未分类说明与预览取消

- `s57_thematic_catalog.py` 动态 `other` 类只返回中性名称/描述，不再返回“按原始对象类导出，不做业务安全解释”或“不保证与水深/障碍物直接相关”caveat；前端 `S57ThematicDialog` 对 `category=other` 不渲染类说明。
- `S57ThematicDialog` 新增 `previewActive` prop；当 `s57ThematicPreview.exportId` 非空时顶部显示“地图上正在显示样例预览 / 取消地图预览”。取消按钮 emit `clear-preview` → `MapWorkspaceView` 调用 `useS57ThematicPreview.clear()`，隐藏样例图层、清空 `exportId`；提示条在“提取”和“已保存成果”两个 tab 均可见。
- Headless Edge 验证：提取页无该说明；已保存成果页点击“在图上预览样例”后提示条出现，点击“取消地图预览”后提示条/按钮消失；截图 `output/ui-thematic-preview-cancel-20261116.png`。
