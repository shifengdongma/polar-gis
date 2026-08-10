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
    ├── styles.css              # 全局样式 (1284行, CSS 自定义属性)
    │
    ├── api/
    │   └── client.ts           # Axios 实例 + 自动令牌刷新
    │
    ├── components/
    │   └── WeatherChart.vue    # ECharts 天气图表组件
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
    │   └── projects.test.ts    # Store 单元测试
    │
    ├── types/
    │   └── index.ts            # TypeScript 类型定义
    │
    ├── utils/
    │   ├── mapExtent.ts        # 地图范围解析
    │   ├── mapExtent.test.ts   # 工具函数测试
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
│   └── useProjectsStore → 项目列表分页加载
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

---

## 6. 文件清单

### 后端 (52 files)
- Python 源文件: `app/api/` (10), `app/core/` (6), `app/services/` (9), `app/worker/` (2), 根文件 (4) = 31
- 迁移文件: `migrations/` (5)
- 测试文件: `tests/` (9)
- 配置文件: `pyproject.toml`, `alembic.ini`, `.env.example`, `.dockerignore`, `Dockerfile` (5)

### 前端 (31 source files)
- Vue 组件: `src/views/` (11), `src/components/` (1), `src/layouts/` (1) = 13
- TypeScript 模块: `src/api/` (1), `src/stores/` (3), `src/types/` (1), `src/utils/` (6), `src/router/` (1) = 12
- 入口: `src/main.ts`, `src/App.vue`, `src/env.d.ts` = 3
- 配置文件: `package.json`, `vite.config.ts`, `tsconfig.json` (x3), `index.html`, `Dockerfile`, `.dockerignore` (7)

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
