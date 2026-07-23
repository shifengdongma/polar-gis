# 09 — 系统架构文档 (System Architecture)

> 极地海洋环境信息平台 (Polar-GIS) 系统架构说明
> 最后更新: 2026-07-23

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
│   │   ├── s57_styles.py       # S-57 SLD 样式预设 (10种)
│   │   └── audit.py            # 审计日志写入
│   │
│   └── worker/                 # 后台工作进程
│       └── main.py             # 轮询导入任务 + 批次任务

├── migrations/                 # Alembic 数据库迁移
│   └── versions/               # 迁移脚本 (3个)
│
├── tests/                      # pytest 测试套件 (40个测试)
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

## 6. 文件清单

### 后端 (50 files)
- Python 源文件: `app/api/` (10), `app/core/` (6), `app/services/` (7), `app/worker/` (2), 根文件 (4) = 29
- 迁移文件: `migrations/` (5)
- 测试文件: `tests/` (8)
- 配置文件: `pyproject.toml`, `alembic.ini`, `.env.example`, `.dockerignore`, `Dockerfile` (5)

### 前端 (29 source files)
- Vue 组件: `src/views/` (11), `src/components/` (1), `src/layouts/` (1) = 13
- TypeScript 模块: `src/api/` (1), `src/stores/` (3), `src/types/` (1), `src/utils/` (3), `src/router/` (1) = 9
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
