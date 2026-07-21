# 10 — 工作日志 (Work Log)

> 记录每次开发会话的任务计划、修改内容与决策过程
> 最后更新: 2026-07-20

---

## 会话 #1 — 项目初始化与环境配置

**日期**: 2026-07-20
**目标**: 初始化项目开发环境, 创建规范文档, 配置 Git 远程仓库, 安装依赖, 启动项目

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 创建 CLAUDE.md 项目规范文件 | ✅ 完成 |
| 2 | 创建 docs/09-system-architecture.md 系统架构文档 | ✅ 完成 |
| 3 | 创建 docs/10-work-log.md 工作日志文档 | ✅ 完成 |
| 4 | 创建 docs/11-work-summary.md 工作总结文档 | ✅ 完成 |
| 5 | 配置 Git 远程仓库 + 初始提交 + 推送 | ✅ 完成 |
| 6 | 创建 .venv 虚拟环境 + 安装 Python 依赖 | ✅ 完成 |
| 7 | 配置 Docker Compose 环境并启动 | ✅ 完成 |
| 8 | 验证服务健康状态 | ✅ 完成 |
| 9 | 更新文档并提交最终版本 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-20 | `CLAUDE.md` | 新建 | 项目规范: 虚拟环境路径、文档规约、Git工作流 |
| 2026-07-20 | `docs/09-system-architecture.md` | 新建 | 系统架构文档: 前后端代码结构、API路由、数据模型、部署架构 |
| 2026-07-20 | `docs/10-work-log.md` | 新建 | 工作日志文档 (本文件) |
| 2026-07-20 | `docs/11-work-summary.md` | 新建 | 工作总结文档 |
| 2026-07-20 | `deploy/compose.yml` | 修改 | GeoServer版本 2.26.2→2.25.3 (使用本地缓存镜像); 移除version字段; backend/worker改用预构建镜像; web改用预构建镜像 |
| 2026-07-20 | `backend/Dockerfile` | 修改 | apt-get增加 --fix-missing 参数以应对网络不稳定 |
| 2026-07-20 | `frontend/Dockerfile` | 修改 | node版本 22-alpine→20-alpine (使用本地可用镜像) |
| 2026-07-20 | `backend/migrations/versions/0003_project_code_active_unique.py` | 修复 | 使用 IF NOT EXISTS 避免重复创建索引错误 |
| 2026-07-20 | `deploy/.env` | 新建 | 从 .env.example 复制, 使用默认开发配置 |

### 遇到的问题与解决方案

1. **docker.osgeo.org 不可达**: DNS超时 + TLS握手超时 → 使用本地已有的 geoserver:2.25.3 镜像
2. **daocloud镜像不稳定**: 部分Docker Hub镜像401/EOF → 使用预构建镜像策略
3. **Debian包下载失败**: 网络不稳定导致2个包下载失败 → 增加 --fix-missing 参数
4. **Alembic迁移0003失败**: uq_projects_code_active索引已存在 → 添加IF NOT EXISTS

### 环境信息

- **开发机**: Windows 11 Home China 10.0.26200
- **Python**: 3.12.7
- **Node.js**: v22.14.0
- **Docker Desktop**: 29.6.1 + Compose v5.2.0
- **项目路径**: `F:\polar-gis\`
- **GitHub 仓库**: https://github.com/shifengdongma/polar-gis.git

### 服务运行状态

| 服务 | 端口 | 状态 |
|------|------|------|
| PostgreSQL + PostGIS | 5432 | ✅ healthy |
| GeoServer | 8080 | ✅ healthy |
| Backend (FastAPI) | 8000 (内部) | ✅ healthy |
| Worker | - (内部) | ✅ running |
| Web (Nginx + Frontend) | 8088 | ✅ running |

---

## 会话 #2 — 修复登录 401 错误

**日期**: 2026-07-20
**目标**: 诊断并修复 admin 用户登录报 401 Unauthorized 错误

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 诊断登录 401 错误原因 | ✅ 完成 |
| 2 | 修复数据库中的 admin 账户状态 | ✅ 完成 |
| 3 | 验证修复结果 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-20 | (数据库) | 修改 | 重置 admin 用户: failed_login_count→0, locked_until→NULL, 更新 password_hash |

### 问题诊断

1. **账户锁定**: admin 用户 failed_login_count=5, locked_until 已设置 — 因多次密码错误被锁定15分钟
2. **密码可能不匹配**: .env 中 INITIAL_ADMIN_PASSWORD 与数据库中哈希不一致
3. **429 Too Many Requests**: 锁定后继续尝试导致触发 rate limiting

### 解决方案

直接在 PostgreSQL 中更新 users 表:
- 重置 `failed_login_count = 0`
- 清除 `locked_until = NULL`
- 使用 Argon2 重新哈希密码并更新 `password_hash`

### 知识点

- `.env` 修改后不需要重新构建镜像, `docker compose down && docker compose up -d` 重启即可
- `ensure_initial_admin()` 仅在用户不存在时创建, 不会更新已存在用户的密码
- 因此改密码需要同步更新数据库, 或删除用户后重启让系统重建

---

## 会话 #3 — 生成用户操作使用手册

**日期**: 2026-07-21
**目标**: 全面分析项目代码文件与功能, 生成一份完整详细的用户操作使用手册

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 分析后端 API 结构 (71 个端点) | ✅ 完成 |
| 2 | 分析前端视图与路由 (10 个页面组件) | ✅ 完成 |
| 3 | 分析后端服务与 Worker | ✅ 完成 |
| 4 | 分析部署配置与现有文档 | ✅ 完成 |
| 5 | 撰写用户手册 (9 大章节) | ✅ 完成 |
| 6 | 更新文档 09/10/11 并提交推送 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-21 | `docs/12-user-manual.md` | 新建 | 完整用户操作使用手册: 系统概述、安装部署、快速入门、用户界面指南、管理功能指南、数据格式、API参考、常见问题、附录 |
| 2026-07-21 | `docs/09-system-architecture.md` | 修改 | 更新文档索引, 添加用户手册引用 |
| 2026-07-21 | `docs/10-work-log.md` | 修改 | 添加会话 #3 工作日志 |
| 2026-07-21 | `docs/11-work-summary.md` | 修改 | 添加会话 #3 工作总结 |

### 手册内容概览

手册共 9 大章节, 覆盖:

1. **系统概述**: 平台简介、核心特性、技术架构、用户角色
2. **安装与部署**: 环境要求、Docker Compose 部署、运维命令、开发环境
3. **快速入门**: 首次登录、典型工作流程、一分钟体验
4. **用户界面指南**: 登录认证、项目门户、地图工作台(图层面板/地图工具/投影切换/属性表/导出)
5. **管理功能指南**: 管理仪表盘、用户管理、项目管理(生命周期/图层配置)、数据目录(上传/版本管理/批量删除)、S-57批量导入、导入任务监控、数据清理、图层与系统管理(图层/SLD样式/底图/审计日志)
6. **数据格式支持**: S-57/GeoJSON/Shapefile/GeoTIFF、文件大小限制、S-57更新链规则
7. **API 参考**: 认证API、公开API、管理API、演示数据API、健康检查、请求示例
8. **常见问题**: 登录/数据导入/地图显示/项目管理/性能/安全合规 FAQ
9. **附录**: 坐标系、S-57对象类对照表、数据库表结构、错误代码、快捷键、环境变量参考
