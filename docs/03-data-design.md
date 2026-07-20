# 极地海洋环境信息平台数据设计

## 1. 设计原则

- 业务元数据、空间派生数据和原始文件分离。
- 原始文件不可变，任何更新产生新的数据集版本。
- 项目引用图层，不复制数据。
- 当前有效版本通过显式指针管理。
- 所有空间数据记录坐标系和范围。
- 所有管理对象默认软删除。

## 2. 逻辑关系

```text
users ─────────────── audit_logs

projects ── project_layers ── layers ── dataset_versions ── datasets
                     │            │              │               │
                     │            └── styles     ├── files       │
                     │                           └── import_jobs  │
                     └── layer_groups                            │

base_maps
refresh_tokens
system_settings
s57_import_batches ── s57_import_batch_files
                  └── s57_import_batch_items ── datasets
```

## 3. 数据库模式

建议使用三个PostgreSQL schema：

- `app`：业务表。
- `geo`：平台生成的空间派生表和稳定视图。
- `audit`：审计日志。

GeoServer使用只读数据库账号访问 `geo` schema。Worker使用受限写入账号管理派生表，API账号不直接创建或删除空间表。

## 4. 核心表

### 4.1 `app.users`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 主键 |
| username | varchar | 唯一登录名 |
| display_name | varchar | 显示名称 |
| password_hash | varchar | Argon2哈希 |
| role | varchar | `system_admin` 或 `user` |
| is_active | boolean | 是否可登录 |
| failed_login_count | integer | 连续失败次数 |
| locked_until | timestamptz | 临时锁定时间 |
| last_login_at | timestamptz | 最近登录时间 |
| created_at/updated_at | timestamptz | 审计时间 |
| deleted_at | timestamptz | 软删除时间 |

### 4.2 `app.refresh_tokens`

保存刷新令牌的哈希、用户、设备摘要、过期时间、撤销时间和轮换关系。数据库不得保存可直接使用的明文令牌。

### 4.3 `app.projects`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 主键 |
| code | varchar | 稳定英文标识；仅对未软删除项目保持唯一，删除后允许复用 |
| name | varchar | 中文名称 |
| description | text | 描述 |
| status | varchar | `draft/published/archived` |
| default_crs | varchar | 默认 `EPSG:3857` 或 `EPSG:3413` |
| initial_extent | text | EPSG:4326范围WKT |
| cover_file_id | uuid | 可选封面 |
| published_at | timestamptz | 发布时间 |
| created_by/updated_by | uuid | 操作用户 |
| created_at/updated_at/deleted_at | timestamptz | 时间字段 |

### 4.4 `app.layer_groups`

保存项目内分组名称、父分组、排序号和默认折叠状态。分组只属于项目，不属于数据集。

### 4.5 `app.datasets`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 主键 |
| code | varchar | 稳定内部标识 |
| name | varchar | 数据集名称 |
| data_type | varchar | `s57/raster/vector/demo_ais/demo_weather` |
| description | text | 描述 |
| current_version_id | uuid | 当前有效版本 |
| created_by | uuid | 创建者 |
| created_at/updated_at/deleted_at | timestamptz | 时间字段 |

### 4.6 `app.dataset_versions`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 主键 |
| dataset_id | uuid | 数据集 |
| version_no | integer | 平台版本号 |
| source_format | varchar | 原始格式 |
| source_crs | varchar | 原始坐标系 |
| extent | text | EPSG:4326范围WKT |
| status | varchar | `processing/valid/failed/retired` |
| content_hash | varchar | 原始内容摘要 |
| parent_version_id | uuid | 来源版本 |
| metadata | jsonb | 格式特有元数据 |
| created_at/activated_at | timestamptz | 时间字段 |

S-57专有元数据放入结构化字段或 `metadata`，至少包括：

- cell_name
- edition_number
- update_number
- issue_date
- compilation_scale
- usage_band

### 4.7 `app.files`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 主键 |
| dataset_version_id | uuid | 所属版本 |
| purpose | varchar | `source/derived/log/cover/export` |
| original_name | varchar | 用户文件名，仅展示 |
| storage_key | varchar | 平台生成的相对存储键 |
| size_bytes | bigint | 文件大小 |
| sha256 | varchar | 内容摘要 |
| media_type | varchar | 内容类型 |
| created_at/deleted_at | timestamptz | 时间字段 |

### 4.8 `app.import_jobs`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 主键 |
| dataset_id | uuid | 目标数据集 |
| dataset_version_id | uuid | 候选版本 |
| job_type | varchar | `initial_import/s57_update/republish/cleanup` |
| status | varchar | `queued/running/succeeded/failed/cancelled` |
| stage | varchar | 当前阶段 |
| progress | integer | 0–100 |
| worker_id | varchar | Worker标识 |
| attempt | integer | 尝试次数 |
| error_code | varchar | 稳定错误代码 |
| error_message | text | 脱敏摘要 |
| log_file_id | uuid | 详细日志文件 |
| requested_by | uuid | 请求用户 |
| queued_at/started_at/finished_at | timestamptz | 时间字段 |

任务领取使用 `FOR UPDATE SKIP LOCKED` 或等价机制，避免多个Worker重复处理。

### 4.9 `app.s57_import_batches`

| 字段 | 类型 | 说明 |
|---|---|---|
| id/name | uuid/varchar | 批次主键和显示名称 |
| status | varchar | `queued/running/succeeded/partial_failed/failed` |
| stage/progress | varchar/integer | 当前阶段和0至100进度 |
| total_cells/processed_cells | integer | 识别单元总数和已完成数 |
| succeeded_cells/failed_cells | integer | 成功和失败单元数 |
| requested_by/worker_id | uuid/varchar | 发起管理员和Worker标识 |
| created_at/started_at/heartbeat_at/finished_at | timestamptz | 生命周期和超时检测 |

### 4.10 `app.s57_import_batch_files`

保存批次原始ZIP或目录模式下逐个上传的S-57源文件，字段包括`batch_id`、原始名称、唯一存储键、大小、SHA-256、媒体类型和创建时间。该表不替代数据版本的`file_assets`；Worker完成归组后会为每个数据集版本复制并登记对应不可变源文件。

### 4.11 `app.s57_import_batch_items`

| 字段 | 类型 | 说明 |
|---|---|---|
| id/batch_id | uuid | 单元结果及所属批次 |
| cell_name | varchar | S-57单元名；批次内唯一 |
| status/stage/progress | varchar/varchar/integer | 单元处理状态、阶段和进度 |
| update_count/current_update | integer | 最高更新号和当前已应用更新号 |
| dataset_id | uuid | 自动创建或自动匹配的S-57数据集；校验前失败时为空 |
| error_code/error_message | varchar/text | 稳定错误码和脱敏失败原因 |
| created_at/finished_at | timestamptz | 生命周期 |

### 4.12 `app.layers`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 主键 |
| dataset_version_id | uuid | 数据版本 |
| code | varchar | 稳定图层标识 |
| name | varchar | 显示名称 |
| geometry_type | varchar | 几何类型或栅格 |
| source_table | varchar | `geo` schema中的表或视图 |
| source_crs | varchar | 数据坐标系 |
| status | varchar | `processing/available/publish_failed/disabled` |
| geoserver_workspace | varchar | 工作区 |
| geoserver_layer_name | varchar | GeoServer资源名 |
| queryable | boolean | 是否允许查询 |
| exportable | boolean | 是否允许普通用户导出 |
| allowed_fields | jsonb | 可见和可筛选字段 |
| metadata | jsonb | 图层元数据 |

### 4.13 `app.styles`

保存名称、SLD文件、样式类别、版本、是否默认、GeoServer样式名和发布状态。SLD文件本身通过 `files` 表管理。

### 4.14 `app.project_layers`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 主键 |
| project_id | uuid | 项目 |
| layer_id | uuid | 图层 |
| group_id | uuid | 可选分组 |
| style_id | uuid | 样式 |
| sort_order | integer | 顺序 |
| visible_by_default | boolean | 默认显隐 |
| opacity | numeric | 0到1 |
| min_zoom/max_zoom | numeric | 可选显示范围 |

项目与图层组合必须唯一。

项目配置读取时按`layers -> dataset_versions -> datasets`聚合为一个数据集逻辑行，只统计当前版本且可用的物理图层。保存数据集逻辑行时，服务端删除旧项目关联并将每个选中数据集的当前可用物理图层展开写入`project_layers`；内部行复用同一分组、默认显隐和透明度，样式为空以使用各对象图层的GeoServer默认样式。

### 4.15 `app.base_maps`

保存底图类型、URL模板、投影、版权说明、是否离线、显示范围、启用状态和访问参数。敏感访问令牌不直接存入普通配置字段。

### 4.16 `audit.audit_logs`

保存事件时间、用户、角色、动作、资源类型、资源ID、结果、IP摘要、请求ID和脱敏变更摘要。审计记录不允许通过业务接口修改。

## 5. 空间派生表

### 5.1 命名

平台生成表名使用不可猜测但稳定的内部标识，例如：

```text
geo.ds_<dataset_short_id>_v<version_no>_<layer_code>
```

不得直接使用上传文件名或用户输入名称作为表名。

### 5.2 公共字段

矢量派生表至少包含：

- `id`：平台内部主键。
- `geom`：PostGIS几何列。
- `source_fid`：原始要素标识。
- `source_attrs`：未结构化保留属性，可选。
- 业务筛选所需的结构化字段。

### 5.3 索引

- `geom` 建立GiST索引。
- 常用标识、对象类别和时间字段建立B-tree索引。
- 不为所有S-57属性盲目建立索引。

## 6. S-57 数据模型

### 6.1 处理策略

- 使用GDAL S-57驱动解析。
- 保留对象类别代码和关键原始属性。
- 点、线、面按对象类别或表达需求生成图层。
- 原始文件和更新文件始终保留。
- 当前有效版本不直接就地修改。

### 6.2 版本切换

每次更新生成候选版本和候选派生表。只有数据库导入、空间校验、样式校验和GeoServer发布全部成功后，才更新 `datasets.current_version_id`。

回退只切换到仍保留的有效版本和对应GeoServer资源，不逆向修改原始更新链。

### 6.3 核心对象

一期优先映射：

- 岸线、陆地和海域。
- 等深线、水深点和疏浚区。
- 航道、推荐航线、锚地和交通分道。
- 灯标、浮标和其他助航标志。
- 沉船、障碍物和危险物。
- 限制区、禁航区和保护区。

## 7. 文件存储

### 7.1 目录布局

```text
storage/
  sources/<dataset_id>/<version_id>/
  derived/<dataset_id>/<version_id>/
  styles/<style_id>/<version>/
  job-logs/<year>/<month>/
  exports/<user_id>/<export_id>/
  temp/<upload_or_job_id>/
```

数据库只保存相对存储键。存储根目录由环境变量配置。

### 7.2 生命周期

- 临时上传在任务结束后按策略清理。
- 原始文件不随项目删除。
- 导出文件设置短期过期时间。
- 物理清理命令必须检查项目引用、当前版本和审计要求。仅允许清理已软删除数据集；支持单项和批量预检，批量必须全部通过才执行。执行前返回原始文件、PostGIS派生表和GeoServer资源清单，确认后逐数据集提交删除，以释放大型 S-57 批量清理产生的数据库 DDL 锁；若后续项失败，返回已清理项和失败项。删除内容包括文件、资源、版本、图层及任务记录，并将批次项的数据集引用置空以保留批次审计轨迹。

## 8. 事务与并发

- 用户、项目和配置修改使用数据库事务。
- 大文件转换不持有长事务。
- 数据导入先写候选表，成功后短事务切换有效版本。
- 同一S-57数据集同时只允许一个初始导入或更新任务。
- S-57批次使用数据库行锁领取；同一单元的版本和导入任务由领取该批次的Worker顺序创建和执行，避免普通任务领取器并发抢占更新链。
- 单元失败单独提交失败项并继续下一单元；批次计数和心跳在每个单元结束后提交。匹配已有数据集时，以当前有效版本作为新更新的父版本；导入时仅遍历父版本链，孤立失败版本不参与。若该链的源文件缺失，可由本批次同更新号源文件修复。
- 项目发布使用乐观锁或 `updated_at` 防止覆盖他人修改。

## 9. 数据校验

- 所有上传文件计算SHA-256。
- GeoJSON校验结构、几何和坐标范围。
- Shapefile压缩包校验必需组成文件和编码。
- 栅格校验波段、范围、坐标系和NoData。
- S-57校验单元、版本、更新序号和GDAL可读性。
- 未识别坐标系的数据必须由管理员明确指定后才能继续。

## 10. 演示数据

AIS和气象演示数据使用独立数据集类型和固定标志：

- `is_demo = true`
- `source_name`
- `observed_at` 或 `forecast_at`
- `disclaimer`

前端根据该标志展示“演示数据”徽标。正式适配器不得复用演示数据表作为生产时序库。
