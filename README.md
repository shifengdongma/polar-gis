# 极地海洋环境信息平台 (Polar-GIS)

`polar-gis` 是面向极地和高纬海域的海图与海洋环境 WebGIS 平台。一期正式支持 S-57 电子海图数据的导入、管理、发布、空间查询与可视化，提供项目协作、图层管理、批量加载、测量工具和受控数据导出能力。

> ⚠️ 本系统不是认证 ECDIS，不替代法定航海设备。

---

## 核心功能

### 数据管理
- **S-57 批量导入**：支持 `.000` 基座 + `.001`/`.002` 顺序更新链，自动识别校验，暂停/恢复/取消控制
- **数据集版本管理**：父子版本链，支持更新回退与历史追溯
- **多格式支持**：矢量数据 (S-57/Shapefile) 与栅格数据导入
- **数据清理**：软删除 + 级联清理（GeoServer 图层 + 数据库 schema + 文件资产）

### 地图可视化
- **双投影支持**：EPSG:3413 (北极极地投影) + EPSG:3857 (Web Mercator)
- **智能渲染调度**：三种渲染模式 (standard / smart / overview)，视口裁剪 + 比例尺过滤 + warming 预算 + LRU 驱逐
- **组合图层渲染**：智能模式下 20~30 个独立图层压缩为 3~6 个语义 Bundle，减少 WMS 请求数
- **GWC 瓦片缓存**：EPSG:3413 GridSet 全链路缓存，批量加载 160 层海图流畅平移缩放
- **SLD 比例尺规则**：按 S-57 对象类自动生成比例尺过滤样式
- **动态 zIndex**：30 级分层渲染（面域填充 → 线状结构 → 危险物 → 水深点 → 助航标志）
- **属性查询**：点击识别 + 属性表分页搜索 + 字段过滤
- **测量工具**：距离与面积测量
- **底图切换**：支持 WMTS / WMS / XYZ 多种底图配置

### 项目协作
- **项目门户**：已发布项目浏览与搜索
- **地图工作区**：全屏地图 + 图层树 + 图例 + 属性面板
- **图层控制**：可见性/透明度/顺序/缩放范围独立控制
- **数据导出**：受控空间数据导出

### 管理后台
- **仪表盘**：系统概览统计
- **用户管理**：系统管理员/普通用户双角色，JWT + Argon2 认证，账户锁定保护
- **项目管理**：项目 CRUD + 发布/取消发布 + 地图配置
- **系统配置**：底图管理、SLD 样式管理、审计日志
- **导入监控**：实时导入任务状态与进度

### 演示数据
- **AIS 船舶轨迹**：模拟极地船舶动态数据
- **水文气象**：温度/盐度/海流预报数据可视化

---

## 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 后端框架 | Python / FastAPI | 3.12+ / 0.115+ |
| ORM + 迁移 | SQLAlchemy + Alembic | 2.0+ |
| 数据库 | PostgreSQL + PostGIS | 16 / 3.4 |
| 空间引擎 | GDAL/OGR (含 S-57 驱动) | — |
| 地图服务器 | GeoServer + GeoWebCache | 2.25+ |
| 前端框架 | Vue 3 + Vite + TypeScript | 3.5 / 7 / 5.9 |
| UI 组件库 | Element Plus (中文) | 2.11 |
| 地图渲染 | OpenLayers | 10.6 |
| 图表 | ECharts | 6.0 |
| 状态管理 | Pinia | 3.0 |
| 容器化 | Docker Compose (5 服务) | — |
| 反向代理 | Nginx | — |

---

## 仓库结构

```text
backend/         FastAPI 后端 + 后台 Worker + Alembic 迁移 (52 文件)
frontend/        Vue 3 SPA 前端 (31 源文件)
deploy/          Docker Compose 编排 + Nginx 反向代理配置
docs/            设计文档 (01-08) + 动态文档 (09-12)
scripts/         S-57 检测与开发辅助脚本
data/            脱敏开发样例数据
```

---

## 快速开始

### 环境要求

- Python 3.12+
- Node.js LTS
- PostgreSQL 16 + PostGIS 3.4
- GeoServer 2.25+ (含 GeoWebCache)
- GDAL/OGR (含 S-57 驱动)

验证 GDAL S-57 支持：

```powershell
./scripts/check-s57.ps1 -FilePath D:\data\CELL.000
```

### 1. 后端

```powershell
cd backend

# 创建虚拟环境 (必须在 F:\polar-gis\.venv\)
py -3.12 -m venv F:\polar-gis\.venv
F:\polar-gis\.venv\Scripts\activate

# 安装依赖
pip install -e ".[dev]"

# 配置环境
Copy-Item .env.example .env
# 编辑 .env 填写数据库连接、GeoServer 地址等

# 初始化数据库
alembic upgrade head

# 创建管理员
py -3.12 -m app.cli create-admin --username admin --password "your-password"

# 启动 API 服务 (端口 8000)
uvicorn app.main:app --reload --port 8000
```

另开终端启动后台 Worker（处理导入任务）：

```powershell
F:\polar-gis\.venv\Scripts\activate
cd backend
py -3.12 -m app.worker.main
```

### 2. 前端

```powershell
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`。Vite 开发代理将 `/api` 转发到后端 `:8000`，`/geoserver` 转发到本机 GeoServer `:8080`。

### 3. 远程开发虚拟机

内网虚拟机 `192.168.92.129` 提供共享 PostgreSQL (`:5432`) 和 GeoServer (`:8080`)。配置已写入 `backend/.env`，确认网络可达后直接启动即可。

若本机不运行 Worker 但使用服务器 Worker 处理上传，前端 `.env` 需设置：
```
VITE_API_PROXY_TARGET=http://192.168.92.129:8088
```

---

## API 概览

所有端点挂载在 `/api/v1`，共约 60 个端点：

| 模块 | 路由 | 说明 |
|------|------|------|
| 认证 | `/auth` | 登录/刷新/登出 (JWT + Argon2) |
| 用户管理 | `/admin/users` | 管理员用户 CRUD |
| 项目 (公开) | `/projects` | 已发布项目浏览 + 地图配置 |
| 项目 (管理) | `/admin/projects` | 项目 CRUD + 发布管理 |
| 数据集 | `/admin/datasets` | 数据集 CRUD + 版本管理 |
| 上传 | `/admin/uploads` | 文件上传 |
| S-57 批量导入 | `/admin/s57-import-batches` | 批量导入 + 暂停/恢复/取消 |
| 导入任务 | `/admin/import-jobs` | 导入进度监控 |
| 图层 (公开) | `/layers` | 元数据 + 属性查询 + 导出 |
| 图层 (管理) | `/admin/layers` | 图层管理 |
| 底图 | `/base-maps` | 底图 CRUD |
| 样式 | `/admin/styles` | SLD 样式管理 + 批量刷新 |
| 演示数据 | `/demo` | AIS 船舶 + 天气预报 |
| 系统 | `/health` | 健康检查 + 审计日志 |
| GWC 回填 | `/admin/gwc/backfill` | EPSG:3413 缓存批量补齐 |
| 渲染计划 | `/projects/{id}/map-render/plan` | 组合图层 Bundle 渲染计划 |

---

## 验证

```powershell
# 后端测试 (168 个)
cd backend
pytest tests/ -v
ruff check app tests

# 前端测试 (77 个)
cd frontend
npm test
npm run typecheck
npm run build
```

---

## 生产部署

```bash
cd deploy
cp .env.example .env
# 编辑 .env — 替换所有密码、密钥和公开地址
docker compose up -d --build
```

5 个容器服务：`postgres` / `geoserver` / `backend` / `worker` / `web`(nginx)。详见 `docs/08-deployment.md`。

---

## 文档

| 文档 | 内容 |
|------|------|
| `docs/01-requirements.md` | 需求规范 |
| `docs/02-system-design.md` | 系统设计 |
| `docs/03-data-design.md` | 数据设计 |
| `docs/04-api-design.md` | API 设计 |
| `docs/05-ui-ux-design.md` | UI/UX 设计 |
| `docs/06-development-plan.md` | 开发计划 |
| `docs/07-testing.md` | 测试与验收 |
| `docs/08-deployment.md` | 部署说明 |
| `docs/09-system-architecture.md` | **系统架构文档** (动态更新) |
| `docs/10-work-log.md` | **工作日志** (动态更新) |
| `docs/11-work-summary.md` | **工作总结** (动态更新) |
| `docs/12-user-manual.md` | **用户操作使用手册** |

---

## 坐标参考系统

| EPSG | 名称 | 用途 |
|------|------|------|
| 4326 | WGS84 | 全球经纬度 (数据存储) |
| 3857 | Web Mercator | 标准 Web 地图 |
| 3413 | Arctic Stereographic | 北极极地投影 (主要工作投影) |

---

## 外部验收项

- 提供脱敏 S-57 `.000` / `.001` / `.002` 样本进行全流程验证
- 在安装 GDAL / PostGIS / GeoServer 的环境中完成真实导入、更新、发布和回退验证
- AIS 和水文气象为明确标识的演示数据
