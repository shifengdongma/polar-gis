# 极地海洋环境信息平台开发与部署说明

## 1. 环境原则

- 开发环境直接运行，不要求Docker。
- 开发人员手动安装PostgreSQL/PostGIS、GeoServer、GDAL和Java。
- 生产环境为Linux，使用Docker Compose。
- 所有路径通过配置提供，不绑定开发机绝对路径。
- 所有版本在项目脚手架建立和S-57 PoC完成后锁定。

## 2. 开发环境组件

建议准备：

- Python受支持稳定版本。
- Node.js当前LTS版本。
- PostgreSQL及兼容PostGIS版本。
- GDAL/OGR及S-57驱动。
- Java运行环境。
- GeoServer和GeoWebCache。

必须验证：

```text
ogrinfo --formats
```

输出中存在S-57驱动，并使用真实脱敏样本执行一次 `ogrinfo` 和 `ogr2ogr` 验证。

## 3. 推荐开发配置

项目脚手架建立后提供：

- `.env.example`：只包含变量名和安全示例。
- `backend/.env`：本地后端配置，不提交。
- `frontend/.env.local`：本地前端配置，不提交。
- GeoServer本地工作区和测试数据库。
- 仓库外的本地测试数据目录。

前端开发服务器通过`/geoserver`代理访问GeoServer，避免浏览器直接跨域请求WMS。GeoServer不在本机时，在未提交的`frontend/.env`中设置`VITE_GEOSERVER_PROXY_TARGET`为实际GeoServer根地址（例如`http://host:8080`），并在后端设置`GEOSERVER_PUBLIC_URL=/geoserver`。

### 3.1 核心环境变量

```text
APP_ENV
APP_SECRET_KEY
DATABASE_URL
ACCESS_TOKEN_TTL_MINUTES
REFRESH_TOKEN_TTL_DAYS
STORAGE_ROOT
TEMP_ROOT
MAX_UPLOAD_BYTES
GEOSERVER_URL
GEOSERVER_ADMIN_USER
GEOSERVER_ADMIN_PASSWORD
GEOSERVER_WORKSPACE
GDAL_DATA
PROJ_DATA
CORS_ALLOWED_ORIGINS
VITE_API_PROXY_TARGET
```

不得在示例文件中提供真实密码。

当开发环境使用服务器上的 Worker 时，Vite 的`VITE_API_PROXY_TARGET`应指向服务器应用入口，保证上传 API 和 Worker 使用同一共享存储。修改该变量后必须重启 Vite；不得让本机 API 向远程数据库创建由服务器 Worker 领取的上传任务，除非两端已挂载同一存储根目录。

## 4. 开发启动顺序

1. 启动本地PostgreSQL/PostGIS。
2. 创建开发数据库和受限账号。
3. 启动GeoServer并创建测试管理员。
4. 配置后端环境变量。
5. 执行Alembic迁移。
6. 启动FastAPI API进程。
7. 启动同代码库Worker进程。
8. 配置前端API地址并启动Vite。
9. 检查 `/health/live` 和 `/health/ready`。

脚手架生成后，应在根目录提供统一开发说明，但不得强制开发者使用Docker。

## 5. 生产Docker Compose设计

建议服务：

```text
reverse-proxy   HTTPS、静态前端和API反向代理
backend         FastAPI API进程
worker          同一后端镜像的导入Worker进程
postgres        PostgreSQL + PostGIS
geoserver       GeoServer + GeoWebCache
```

前端构建产物由反向代理提供，不需要长期运行Node服务。

### 5.1 网络

- `public`：仅反向代理加入。
- `internal`：backend、worker、postgres和geoserver加入。
- PostgreSQL和GeoServer管理端口不直接暴露公网。
- 普通WMS/WMTS通过反向代理的受控路径访问。

### 5.2 持久卷

- PostgreSQL数据。
- GeoServer数据目录。
- 原始和派生文件存储。
- 导入任务日志。
- 反向代理证书和必要配置。

一期未建设自动备份，但不得把持久数据放在容器临时文件系统中。

## 6. 反向代理

反向代理负责：

- HTTPS终止。
- 前端静态文件。
- `/api/` 转发至FastAPI。
- 受控地图服务路径转发至GeoServer。
- 上传大小和超时配置。
- 安全响应头。

5GB上传需要同时调整代理和后端限制，并使用流式转发，禁止代理缓存完整请求体到内存。

## 7. PostgreSQL与账号

建议至少区分：

- `app_api`：业务表读写，不创建空间派生表。
- `app_worker`：导入和候选空间表管理。
- `geoserver_reader`：只读 `geo` schema。
- `migration_admin`：仅在迁移时使用。

生产应用不得使用PostgreSQL超级用户。

## 8. GeoServer

- 使用独立工作区 `polar_gis`。
- 数据目录必须持久化。
- 管理密码通过Secret或环境注入，不写入Compose文件。
- 禁止公开GeoServer管理页面。
- 开启GeoWebCache并按项目图层设置合理缓存。
- 修改样式和资源必须通过后端集成和REST接口。

## 9. GDAL与Worker

- backend和worker镜像使用相同代码版本。
- Worker镜像包含经验证的GDAL和Proj数据。
- 大型转换写入专用临时目录。
- 容器设置CPU、内存和临时磁盘限制。
- Worker收到终止信号时停止领取新任务，并安全结束或标记当前任务。
- 启动时恢复超时的 `running` 任务，不能永久卡住。
- S-57批次源文件总量最多5GB，ZIP最多10000个成员且允许的解压后总量最多20GB；Worker临时卷必须按最大并发批次数和解压上限预留空间。
- 批次Worker会同时保留原始批次源文件和按数据集版本复制的源文件，持久存储容量规划必须计入这部分可追溯数据。
- 批次处理心跳超时阈值为30分钟；普通导入任务为10分钟。故障恢复前应确认原Worker已停止，避免外部GDAL进程仍在写入。

## 10. 健康检查

### `/health/live`

只验证API进程事件循环可响应，不访问外部服务。

### `/health/ready`

验证：

- PostgreSQL可连接。
- 存储根目录可读写。
- 必要配置存在。

GeoServer状态可以作为降级项返回，不应因短暂不可用导致所有只读业务被编排器反复重启。

## 11. 日志

- API和Worker输出JSON结构化日志到标准输出。
- 日志至少包含时间、级别、服务、请求ID或任务ID、事件和错误代码。
- 生产环境由Docker日志驱动进行基础轮转。
- 导入详细日志写入持久存储并在数据库登记。
- 日志不得包含密码、JWT、刷新令牌、GeoServer凭据或完整敏感属性。

一期不部署Prometheus、Grafana或Loki。

## 12. 安全配置

- 生产环境强制HTTPS。
- 刷新Cookie使用 `HttpOnly`、`Secure` 和适当 `SameSite`。
- CORS只允许实际前端来源。
- 设置内容安全策略、`X-Content-Type-Options` 和点击劫持防护。
- 禁止目录列表。
- 上传和导出目录不直接作为静态目录公开。
- 初始管理员密码必须在首次部署后修改。

## 13. 发布流程

1. 运行后端和前端测试。
2. 构建固定版本的前端和后端镜像。
3. 在临时数据库验证Alembic迁移。
4. 更新生产Compose镜像标签，不使用浮动 `latest`。
5. 先执行数据库迁移。
6. 更新backend和worker。
7. 验证健康检查、登录、项目列表和测试地图。
8. 检查GeoServer图层和导入任务。
9. 记录发布版本和已知问题。

## 14. 故障处理

### API不可用

- 检查健康检查、数据库连接、配置和迁移状态。
- 不要通过删除数据库或数据卷快速恢复。

### Worker任务卡住

- 检查任务心跳、GDAL进程和临时磁盘。
- 使用管理命令将确认失效的任务标记为失败后重试。

### GeoServer不可用

- 已发布地图服务降级，管理端提示。
- 项目和数据目录仍应可访问。
- 恢复后重试发布失败图层。

### 磁盘不足

- 停止新导入。
- 清理已过期临时文件和导出文件。
- 不直接删除原始文件、当前版本或GeoServer数据目录。

## 15. 当前明确限制

- 一期不提供自动备份。
- 一期不提供自动水平扩容。
- 一期不提供多节点数据库高可用。
- AIS和气象为演示数据。
- S-101/S-102不是生产功能。
- 系统不是认证航海设备。
