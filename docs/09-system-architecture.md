# 09 — 系统架构文档 (System Architecture)

> 极地海洋环境信息平台 (Polar-GIS) 系统架构说明
> 最后更新: 2026-08-10

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
| 地图服务器 | GeoServer 2.26.2 + GeoWebCache |
| 前端框架 | Vue 3 + Vite + TypeScript |
| UI 组件库 | Element Plus (中文) |
| 地图渲染 | OpenLayers 10.6 |
| 图表 | ECharts 6.0 |
| 状态管理 | Pinia 3.0 |
| 容器化 | Docker Compose (5 服务) |
| 反向代理 | Nginx |

---

## 2. 后端架构 (backend/)

### 2.1 目录结构与职责

```
backend/
├── app/
│   ├── main.py                 # FastAPI 应用入口点
│   ├── models.py               # SQLAlchemy ORM 模型定义 (16张表)
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── cli.py                  # 命令行工具 (创建管理员)
│   │
│   ├── api/                    # API 路由层
│   │   ├── auth.py             # 认证: 登录/刷新/登出/当前用户
│   │   ├── users.py            # 管理员用户管理 CRUD
│   │   ├── projects.py         # 项目 CRUD + 发布 + 地图配置
│   │   ├── datasets.py         # 数据集管理 + S-57批次导入 + 上传
│   │   ├── layers.py           # 图层元数据 + 空间查询 + 导出
│   │   ├── base_maps.py        # 底图 CRUD
│   │   ├── styles.py           # SLD 样式管理
│   │   ├── demo.py             # 演示数据 (AIS/天气)
│   │   ├── system.py           # 健康检查 + 审计日志
│   │   └── deps.py             # 依赖注入 (认证/鉴权)
│   │
│   ├── core/                   # 核心基础设施
│   │   ├── config.py           # Pydantic Settings (读取 .env)
│   │   ├── database.py         # SQLAlchemy 引擎 + 会话工厂
│   │   ├── security.py         # JWT 令牌 + Argon2 密码哈希
│   │   ├── errors.py           # AppError 异常 + 全局处理器
│   │   └── middleware.py       # 请求上下文中间件 (Request ID)
│   │
│   ├── services/               # 业务逻辑层
│   │   ├── storage.py          # 本地文件存储 + 上传校验
│   │   ├── geoserver.py        # GeoServer REST API 客户端
│   │   ├── importer.py         # GDAL 导入处理器 (矢量/栅格/S-57)
│   │   ├── s57.py              # S-57 文件识别 + GDAL 检测
│   │   ├── s57_batch.py        # S-57 批次导入处理器
│   │   ├── s57_styles.py       # S-57 SLD 样式预设 (10种) + 比例尺规则
│   │   ├── s57_layer_catalog.py # S-57 图层分类事实来源（纯函数）
│   │   ├── s57_style_refresh.py # SLD 样式幂等刷新 (sldHash 对比 + 缓存截断)
│   │   ├── map_render_plan.py  # 组合图层渲染计划纯函数 (build_bundles)
│   │   ├── gwc_backfill.py     # GWC EPSG:3413 瓦片缓存回填 (GridSet + 图层)
│   │   └── audit.py            # 审计日志写入
│   │
│   └── worker/                 # 后台工作进程
│       └── main.py             # 轮询导入任务 + 批次任务

├── migrations/                 # Alembic 数据库迁移
│   └── versions/               # 迁移脚本 (3个)
│
├── tests/                      # pytest 测试套件（按业务模块组织）
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
- **Worker 层**: 独立轮询进程, 异步处理导入任务

### 2.3 API 路由总览

所有 API 端点均挂载在 `/api/v1` 前缀下, 共约 **60 个端点**:

| 模块 | 路由前缀 | 功能 |
|------|----------|------|
| 认证 | `/api/v1/auth` | 登录/刷新/登出/当前用户 |
| 用户管理 | `/api/v1/admin/users` | 用户 CRUD |
| 项目(公开) | `/api/v1/projects` | 已发布项目浏览 + 地图配置 |
| 项目(管理) | `/api/v1/admin/projects` | 项目 CRUD + 发布/取消发布 |
| 数据集 | `/api/v1/admin/datasets` | 数据集 CRUD + 版本管理 + 清理 |
| 上传 | `/api/v1/admin/uploads` | 文件上传 |
| S-57批导入 | `/api/v1/admin/s57-import-batches` | 批量 S-57 导入 |
| 导入任务 | `/api/v1/admin/import-jobs` | 导入任务监控 |
| 图层(公开) | `/api/v1/layers` | 图层元数据 + 识别 + 搜索 + 导出 |
| 图层(管理) | `/api/v1/admin/layers` | 图层管理 |
| 底图(公开) | `/api/v1/base-maps` | 启用的底图列表 |
| 底图(管理) | `/api/v1/admin/base-maps` | 底图 CRUD |
| 样式 | `/api/v1/admin/styles` | SLD 样式管理 |
| 演示 | `/api/v1/demo` | AIS 船舶 + 天气预报数据 |
| 系统 | `/api/v1/health` | 存活/就绪检查 + 审计日志 |
| S-57批暂停 | `/api/v1/admin/s57-import-batches/{id}/pause` | 暂停批量导入 |
| S-57批恢复 | `/api/v1/admin/s57-import-batches/{id}/resume` | 恢复暂停的批量导入 |
| S-57批取消 | `/api/v1/admin/s57-import-batches/{id}/cancel` | 取消批量导入 |
| GWC缓存回填 | `/api/v1/admin/gwc/backfill` | 为已有 S-57 图层幂等补齐 EPSG:3413 GridSet/缓存配置 |
| S-57样式刷新 | `/api/v1/admin/styles/refresh-s57` | sldHash 幂等刷新 SLD 样式 + 截断瓦片缓存 |

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

### 2.5 数据模型 (16张表)

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

### 2.6 核心业务流程

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
    ├── styles.css              # 全局样式 (1383行, CSS 自定义属性)
    │
    ├── api/
    │   └── client.ts           # Axios 实例 + 自动令牌刷新
    │
    ├── components/
    │   ├── WeatherChart.vue    # ECharts 天气图表组件
    │   └── RoutePlannerPanel.vue # 航路规划模拟面板 (非模态抽屉)
    │
    ├── composables/
    │   └── useRouteDrawing.ts  # 航路地图交互 (Draw/Modify/重建/定位)
    │
    ├── layouts/
    │   └── AppLayout.vue       # 应用外壳 (侧边栏 + 顶栏 + 内容区)
    │
    ├── router/
    │   └── index.ts            # 路由配置 + 导航守卫
    │
    ├── stores/
    │   ├── auth.ts             # 认证状态 (登录/引导/登出)
    │   ├── projects.ts         # 项目列表状态
    │   ├── routes.ts           # 航路草稿状态 (WGS84 真值 + localStorage)
    │   ├── projects.test.ts    # Store 单元测试
    │   └── routes.test.ts      # 航路 Store 单元测试
    │
    ├── types/
    │   └── index.ts            # TypeScript 类型定义 (含 RouteDraft / RoutePointRole)
    │
    ├── utils/
    │   ├── mapExtent.ts        # 地图范围解析
    │   ├── mapExtent.test.ts   # 工具函数测试
    │   ├── mapRoute.ts         # 航路纯 GIS 逻辑 (校验/解析/投影/样式/方向角色)
    │   ├── mapRoute.test.ts    # 航路工具函数测试
    │   └── s57ObjectNames.ts   # S-57 对象名称映射
    │
    └── views/
        ├── LoginView.vue       # 登录页
        ├── MapWorkspaceView.vue # 全屏地图工作区
        ├── ProjectsView.vue    # 项目门户
        │
        └── admin/              # 管理后台
            ├── AdminDashboardView.vue     # 仪表盘
            ├── UserManagementView.vue     # 用户管理
            ├── ProjectManagementView.vue  # 项目管理
            ├── DataCatalogView.vue        # 数据目录
            ├── BatchImportView.vue        # S-57 批量导入
            ├── DatasetCleanupView.vue     # 数据集清理
            ├── ImportJobsView.vue         # 导入任务
            └── SystemManagementView.vue   # 系统配置
```

### 3.2 技术架构

```
Vue 3 (Composition API + <script setup>)
├── Pinia (状态管理)
│   ├── useAuthStore    → 登录/引导/登出 + 令牌管理
│   ├── useProjectsStore → 项目列表分页加载
│   └── useRoutesStore  → 航路草稿 (WGS84 真值 + localStorage 持久化)
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

- **postgres**: postgis/postgis:16-3.4
- **geoserver**: docker.osgeo.org/geoserver:2.26.2
- **backend**: FastAPI + Uvicorn (from `backend/Dockerfile`)
- **worker**: 同 backend 镜像, 运行 `app.worker.main`
- **web**: Nginx 提供前端静态文件 + 反向代理

### 4.2 网络
- `public`: web 对外暴露
- `internal`: 内部服务间通信

### 4.3 卷
- `postgres-data`: 数据库持久化
- `geoserver-data`: GeoServer 数据
- `shared-storage`: 文件存储 (上传/导入)

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

## 5.12 测量与地图内浮层 (会话 #24)

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
- **与椭球测地线的差异**：球面模型比 WGS84 椭球测地线**偏短约 0.28%–0.42%**（高纬更大，中纬 45°N 约 −0.28%）。界面按「近似地表距离」表述，不宣称航海认证精度。
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
  - **鉴权边界（唯一无鉴权数据 API，刻意为之）**：OpenLayers XYZ 原生 `<img>` 无法携带 Bearer，生产地图瓦片（`/geoserver` 经 nginx）同为无鉴权读取，后端仅在内网 `internal`、外部唯一入口是 web/nginx —— 故选"与现有地图瓦片相同的只读访问边界"（任务书 §38-A）。熔断开关 `ICE_ENABLED=false` → 404 `ICE_DISABLED`。
  - 服务经懒工厂 `get_ice_service()`（双重检查；不用 lru_cache/Depends，便于 monkeypatch 与"导入期绝不因数据/PROJ 失败"）。
  - 状态码：畸形参数 422（框架）；未知字段/投影/日期/z>max/x≥2^z → 404（`ICE_*` 码）；`/value` 的一切不可用 → 200 null。
- **配置**：`ice_enabled` / `ice_data_root`（默认 `/data/ice`，代码中无任何机器绝对路径）/ `ice_tile_cache_entries` / `ice_tile_max_zoom`（对应 `ICE_*` 环境变量）。
- **依赖**：`netCDF4`、`numpy`、`Pillow`、`pyproj`（cp312 manylinux 轮子，`python:3.12-slim` 无需新增 apt 包）；不引入 `shapely`（仅参考项目临时 GeoPackage 底图使用，未迁移）。

### 前端

- **`utils/mapIce.ts`**（纯函数，jsdom 可测）：EPSG:3411（Hughes）proj4 按需注册、`createIceTileGrid`（3413: ±4194304/256/maxZoom 10 与后端 `half` 严格对齐；3857 标准 extent）、`buildIceTileUrl`（**URL 必带日期**）、`iceFieldAvailable`、`formatIceDate`、`projectIceExtent`（3411→当前投影，hover 预筛用）、`isIceValueValid`（0 有效）、`iceTimelineIndex` / `stepIceDate`（**数组索引边界，绝不按 date±1**）、`ICE_PALETTES` / `iceLegendGradient`（与后端同源）。
- **`composables/useIceOverlay.ts`**：`info/loading/error/selectedDate/密集度与厚度 visible+opacity/hover/debugAlignment` 状态；`attach()` 幂等、`dispose()` 彻底（removeLayer+dispose+abort）；**日期/可用性/投影变化只 `setSource` 不重建 layer**（换新 XYZ 源含日期参数，旧源自然 GC；`transition:0` 无淡入残影；`crossOrigin:'anonymous'` 供截图合成）；`reloadForProjection()` 保留日期/可见性/透明度只换源与 TileGrid；hover **100ms debounce + AbortController + 请求代次号**（旧响应绝不覆盖新位置），拖图/图层关/无日期/其他交互(`canQueryValue`)/离开范围/销毁一律停止；**不自行注册 map 事件**。
- **组件**（统一 `ice-` 前缀）：`IceLayerPanel`（密集度/厚度开关+透明度+图例+「当前日期无厚度变量」禁用态+定位冰区+对齐调试开关+免责声明）、`IceTimeline`（`info.dates` 索引驱动、首尾禁用、`n / N 个可用日期`、只显示日期不构造文件名；**左右让位由视图注入**，随面板折叠自适应）、`IceValueTooltip`（原始值+日期+经纬度，像素锚定+边缘翻转，`pointer-events:none`）。
- **视图集成（最小侵入）**：`buildMap()` 中 `iceOverlay.attach()`；唯一 `pointermove` 分发 `handlePointerMove` 并在冰情浮窗显示期间抑制经纬度提示（优先级：航路浮窗/地图工具 > 冰情 > 经纬度）；`pointerleave` 与卸载同步清理；`switchProjection()` 在 `syncMeasureForProjection()` 后调用 `iceOverlay.reloadForProjection()`；环境叠加 dropdown 增「冰情信息」入口；时间轴挂载于 `.map-overlay-root`（打印/截图自动排除，冰情地图图层自然进入截图）。

### 瓦片加载性能（会话 #26.1 专项，实测驱动）

**实测根因（修复前）**：① 后端 `_grid` **惊群**——并发冷请求在"归一化在锁外"的窗口内各自完整装载 26M 单元网格（实测单次装载 ≈1.5s；8 张并发冷瓦片**每张 6.6s**、总 7.1s，互相挤占）；② 前端冰情走 OL 默认 `<img>` 加载器——无并发上限（z3 整个北极一次可发 ~64 张）、瓦片被丢弃不中止、无共享缓存 → 请求堆积占满浏览器连接与后端线程，新日期瓦片排队（表现为"时间轴更改无法重新加载"）、海图/底图瓦片被挤占（地图空白）。

**修复**：
- 后端**按日期单飞装载**（`_grid` 快路径 + per-date 装载锁 + 双检；等待者复用同一次装载结果），并将 `warm_default_grid()` 挂在 `info()` 的后台守护线程上预热默认日期（点击"海冰密集度"直接进入 ~0.1s 渲染路径）；`_refresh_files` 换文件时同步失效对应装载锁语义。
- 前端冰情瓦片改用**自定义 `tileLoadFunction`**，复用与海图相同的 `TileRequestQueue`/`LRUTileCache` 实例：缓存优先 → 限流 fetch → blob/objectURL；**代次中止**（`refreshLayers` 即日期/投影/开关切换时，`abortStaleTileLoads()` 使上一代全部在飞请求立即中止让出名额）+ 瓦片被 OL 释放（ol10 中 `release()/dispose()` 置 `TileState.EMPTY`）即中止 + 429/502/503/504 与网络错误指数退避重试。

**修复后实测（经 nginx 真实数据）**：冷日期 8 张并发瓦片总耗时 **7.1s → 3.06s**（每张延迟一致、无饥饿）；`/info` 后（预热）全新冷瓦片 **0.13–0.39s**；已验证部署 bundle 含新加载器。**已知特性**：容器重启后**首次** `/info` 在 Windows bind-mount 上约 12s（149 个 HDF5 首次打开；逐日缓存后 0.1s），期间地图与其它功能不受影响，预热仍保证首次点击瓦片快速。

### 部署

- `data/ice/`（仅 `.gitkeep` + `README.md`，`.gitignore` 排除 `*.nc`；`sample-data/` 与 `sample-data.7z` 同样排除）；
- `deploy/compose.yml`：`- ${ICE_DATA_HOST_PATH:-../data/ice}:/data/ice:ro` + `ICE_ENABLED`/`ICE_DATA_ROOT`（经 YAML 锚点 worker 同样获得，但不读取数据）；不新增任何服务；
- **`deploy/nginx/default.conf`：`location /api/` → `location ^~ /api/`** —— 否则 `/api/v1/ice/.../*.png` 会被静态图片正则 location 拦截，经 `try_files` 回退成 `index.html`（200 text/html），表现为"瓦片永久空白"（已实测复现：旧配置返回 SPA index；修复后返回 image/png）。

---

## 6. 文件清单

### 后端 (54 files，会话 #26 按磁盘实际清点修正)
- Python 源文件: `app/api/` (11), `app/core/` (6), `app/services/` (10), `app/worker/` (2), 根文件 (4) = 33
- 迁移文件: `migrations/` (5)
- 测试文件: `tests/` (11)
- 配置文件: `pyproject.toml`, `alembic.ini`, `.env.example`, `.dockerignore`, `Dockerfile` (5)

### 前端 (44 source files + 20 test files，会话 #26 按磁盘实际清点修正)
- Vue 组件: `src/views/` (11，含 `admin/` 8), `src/components/` (6), `src/layouts/` (1), `src/App.vue` (1) = 19
- TypeScript 模块: `src/api/` (3), `src/stores/` (3), `src/types/` (2), `src/utils/` (12), `src/composables/` (2), `src/router/` (1), `src/main.ts` + `src/env.d.ts` (2) = 25
- 测试: `*.test.ts` (20，与源码同目录，vitest + jsdom)
- 配置文件: `package.json`, `vite.config.ts`, `tsconfig.json` (x3), `index.html`, `Dockerfile`, `.dockerignore` (8)

### 后端 (52 files)
- Python 源文件: `app/api/` (10), `app/core/` (6), `app/services/` (9), `app/worker/` (2), 根文件 (4) = 31
- 迁移文件: `migrations/` (5)
- 测试文件: `tests/` (9)
- 配置文件: `pyproject.toml`, `alembic.ini`, `.env.example`, `.dockerignore`, `Dockerfile` (5)

### 前端 (38 source files + 14 test files，会话 #24 按磁盘实际清点修正)
- Vue 组件: `src/views/` (11，含 `admin/` 8), `src/components/` (3), `src/layouts/` (1), `src/App.vue` (1) = 16
- TypeScript 模块: `src/api/` (2), `src/stores/` (3), `src/types/` (2), `src/utils/` (11), `src/composables/` (1), `src/router/` (1), `src/main.ts` + `src/env.d.ts` (2) = 22
- 测试: `*.test.ts` (14，与源码同目录，vitest + jsdom)
- 配置文件: `package.json`, `vite.config.ts`, `tsconfig.json` (x3), `index.html`, `Dockerfile`, `.dockerignore` (8)

---

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
| `docs/plans/` | 优化方案文档 (global enc 导入 / 批量加载性能优化) |

---

## 8. 导航集成（PolarOptionNav-System-V3）— 批次 A 基座

> 2026-10-29 起实施。详细审计见 `docs/plans/v3-integration-audit.md`，实施计划见
> `C:\Users\liyang\.claude\plans\docs-15-polar-gis-polaroptionnav-system-joyful-toast.md`（计划文件不入库）。

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
├── resources/
│   ├── vessels/xuelong2.json   # 雪龙2静态资料（来源见文件 sources）
│   ├── grids/northeast_passage_25km_static.npz  # 25km NEP 静态网格（488KB）
│   └── risk/weights_v1.json    # legacy_v1 权重/公式与 real_v1 缺测策略
└── (environment/vessel/risk/planner 由后续批次加入)
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
