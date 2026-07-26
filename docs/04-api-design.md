# 极地海洋环境信息平台 API 设计

## 1. 基本约定

- 基础路径：`/api/v1`
- 数据格式：JSON，文件上传和下载除外。
- 时间格式：ISO 8601 UTC。
- 主键：UUID字符串。
- API字段：英文 `camelCase`。
- 数据库字段：英文 `snake_case`。
- OpenAPI由FastAPI生成，并作为接口实现事实来源。

## 2. 认证

### 2.1 访问令牌

- 访问令牌通过 `Authorization: Bearer <token>` 传递。
- 访问令牌短期有效，前端只保存在内存中。
- 刷新令牌通过HttpOnly Secure Cookie传递。
- 刷新令牌轮换，旧令牌使用后失效。

### 2.2 角色

- `system_admin`
- `user`

所有管理端点要求 `system_admin`。读取已发布项目和普通地图功能允许两个角色。

## 3. 通用响应

### 3.1 成功列表

```json
{
  "items": [],
  "page": 1,
  "pageSize": 15,
  "total": 0
}
```

### 3.2 错误

```json
{
  "code": "PROJECT_NOT_FOUND",
  "message": "项目不存在或无权访问",
  "requestId": "01J...",
  "details": null
}
```

### 3.3 分页与排序

- `page`：从1开始。
- `pageSize`：默认15，最大100。
- `sort`：允许的字段名。
- `order`：`asc` 或 `desc`。

服务端必须使用字段白名单，不得把客户端排序字段直接拼接到SQL。

## 4. 认证接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/auth/login` | 公开 | 用户名密码登录 |
| POST | `/auth/refresh` | 刷新Cookie | 刷新令牌 |
| POST | `/auth/logout` | 登录用户 | 撤销刷新令牌 |
| GET | `/auth/me` | 登录用户 | 当前用户信息 |

登录请求：

```json
{
  "username": "admin",
  "password": "example"
}
```

登录响应不返回刷新令牌明文。

## 5. 用户管理接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/users` | 用户列表 |
| POST | `/admin/users` | 创建用户 |
| GET | `/admin/users/{userId}` | 用户详情 |
| PATCH | `/admin/users/{userId}` | 修改名称、角色或状态 |
| POST | `/admin/users/{userId}/reset-password` | 重置密码 |
| DELETE | `/admin/users/{userId}` | 软删除用户 |

禁止停用或删除最后一个有效系统管理员。

## 6. 项目接口

### 6.1 普通用户

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/projects` | 已发布项目列表 |
| GET | `/projects/{projectId}` | 已发布项目详情 |
| GET | `/projects/{projectId}/map-config` | 地图、投影、底图和数据集摘要 |
| GET | `/projects/{projectId}/map-datasets/{datasetId}/layers` | 读取一个数据集当前有效版本的项目图层目录 |
| **POST** | **`/projects/{projectId}/map-layers/resolve`** | **✨ 批量解析 S-57 图层** |

查询参数包括 `search`、`sort=createdAt` 和 `order`。

#### 批量图层解析接口

**请求**：`POST /api/v1/projects/{projectId}/map-layers/resolve`

```json
{
  "datasetIds": ["uuid1", "uuid2"],
  "profile": "navigation_recommended",
  "includeMetadata": false
}
```

- `datasetIds`：1–100 个数据集 UUID（仅允许当前项目已关联的 S-57 数据集）。
- `profile`：`core_chart` | `navigation_recommended` | `all_spatial`。
- `includeMetadata`：是否包含元数据/质量图层（默认 `false`）。

**响应**：`BulkMapLayerResolveResponse`

```json
{
  "datasets": [
    {
      "datasetId": "uuid",
      "datasetCode": "DK20925C",
      "datasetName": "S-57 海图 DK20925C",
      "versionNo": 1,
      "layers": [
        {
          "id": "layer-uuid",
          "code": "dk20925c_v1_depare",
          "objectClass": "DEPARE",
          "objectNameZh": "水深区域",
          "displayCategory": "bathymetry",
          "loadProfile": "core_chart",
          "displayPriority": 10,
          "recommended": true,
          "renderable": true,
          "loadable": true,
          "styleMapped": true,
          "skipReason": null,
          "extent": [-10.0, 60.0, 10.0, 75.0],
          "featureCount": 923,
          "minZoom": null,
          "maxZoom": null
        }
      ]
    }
  ],
  "summary": {
    "datasetCount": 1,
    "candidateCount": 22,
    "loadableCount": 18,
    "metadataSkippedCount": 2,
    "nonSpatialSkippedCount": 1,
    "unavailableSkippedCount": 0,
    "unmappedStyleCount": 1
  }
}
```

**筛选规则**：
- `core_chart`：仅已映射样式的核心海图层（12 种对象类）。
- `navigation_recommended`：核心 + 航行推荐（36 种对象类）。
- `all_spatial`：所有有几何且可渲染的图层（含未映射样式图层）。
- `includeMetadata=false`：排除 metadata_quality 图层。
- non_spatial（DSID、C_AGGR）始终不可加载，仅计入 `nonSpatialSkippedCount`。
- 未映射样式的核心/推荐图层在对应档案中 `loadable=false`、`skipReason="unmapped_style"`。

**错误码**：
- `BULK_LAYER_DATASET_LIMIT_EXCEEDED`（超 100 个 datasetIds）
- `PROJECT_DATASET_NOT_FOUND`（数据集不属于当前项目）
- `NO_LOADABLE_LAYERS`（无匹配的可加载图层）
- `INVALID_LAYER_PROFILE`（profile 不合法）

**兼容性**：不改变 `GET /projects/{projectId}/map-datasets/{datasetId}/layers` 的语义。

### 6.2 管理员

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/projects` | 包含所有状态的项目列表 |
| POST | `/admin/projects` | 创建项目 |
| GET | `/admin/projects/{projectId}` | 管理详情 |
| PATCH | `/admin/projects/{projectId}` | 修改项目 |
| POST | `/admin/projects/{projectId}/publish` | 发布前校验并发布 |
| POST | `/admin/projects/{projectId}/unpublish` | 撤回为草稿 |
| POST | `/admin/projects/{projectId}/archive` | 归档 |
| DELETE | `/admin/projects/{projectId}` | 软删除 |
| PUT | `/admin/projects/{projectId}/layers` | 原子保存项目图层配置 |
| GET | `/admin/projects/{projectId}/layers` | 读取项目当前图层配置 |
| GET | `/admin/projects/{projectId}/dataset-layers` | 分页读取数据集级项目配置候选项 |
| PUT | `/admin/projects/{projectId}/dataset-layers` | 按数据集原子保存项目配置并展开内部图层 |

项目图层配置请求包含分组、排序、默认显隐、透明度、样式和缩放范围；仅允许引用未删除数据集的当前有效版本图层。

管理端默认使用`dataset-layers`，一行对应一个数据集或S-57海图单元。响应包含`datasetId`、`datasetCode`、`datasetName`、`dataType`、`versionNo`、`availableLayerCount`及配置字段。保存请求为`{"datasets":[{"datasetId":"uuid","groupName":"电子海图","sortOrder":0,"visibleByDefault":false,"opacity":1}]}`。服务端只展开当前版本的可用物理图层，内部图层沿用GeoServer默认样式；保留`/layers`接口用于兼容已有技术管理流程。

`map-config.datasets`一行对应一个数据集，包含`id`、名称、分组、默认显示、透明度和`memberLayerCount`，不返回全部内部图层。用户展开数据集后调用`map-datasets/{datasetId}/layers`取得物理图层目录；客户端仅在用户显示某个具体图层时创建该图层的WMS对象。

## 7. 上传与数据集接口

### 7.1 上传

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/admin/uploads` | 流式上传单个文件 |
| GET | `/admin/uploads/{uploadId}` | 上传校验结果 |
| DELETE | `/admin/uploads/{uploadId}` | 删除未使用临时上传 |

一期使用单请求流式上传，不实现断点续传。服务端和反向代理限制均为5GB，并设置合理超时。

### 7.2 数据集

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/datasets` | 数据目录列表，支持`search`按名称或代码检索及分页参数 |
| POST | `/admin/datasets` | 基于上传创建数据集和导入任务 |
| GET | `/admin/datasets/{datasetId}` | 数据集详情和版本 |
| PATCH | `/admin/datasets/{datasetId}` | 修改元数据 |
| DELETE | `/admin/datasets/{datasetId}` | 软删除或返回引用冲突 |
| POST | `/admin/datasets/bulk-delete` | 批量软删除，逐项返回已删除项和项目引用阻塞项 |
| GET | `/admin/datasets/{datasetId}/references` | 查看引用该数据集的项目 |
| GET | `/admin/datasets/deleted` | 已软删除数据集及永久清理预览清单 |
| GET | `/admin/datasets/{datasetId}/cleanup-preview` | 单个已删除数据集的清理资源清单 |
| POST | `/admin/datasets/{datasetId}/purge` | 输入`DELETE {datasetCode}`后永久清理资源 |
| POST | `/admin/datasets/bulk-purge-preview` | 批量永久清理预检及完整资源清单 |
| POST | `/admin/datasets/bulk-purge` | 输入`PURGE {count} DATASETS`后批量永久清理 |
| POST | `/admin/datasets/{datasetId}/s57-updates` | 上传记录创建S-57更新任务 |
| POST | `/admin/datasets/{datasetId}/rollback` | 切换到上一有效版本 |

创建数据集示例：

```json
{
  "name": "北极示例海图",
  "dataType": "s57",
  "uploadId": "uuid",
  "sourceCrs": null,
  "description": "脱敏测试数据"
}
```

### 7.3 S-57 批量导入

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/admin/s57-import-batches` | 以`multipart/form-data`提交批次名称和一个ZIP或多个S-57文件 |
| GET | `/admin/s57-import-batches` | 分页读取批次进度和汇总计数 |
| GET | `/admin/s57-import-batches/{batchId}` | 读取批次及按单元排序的成功、失败详情 |

POST字段为`name`和重复的`files`。ZIP必须单独提交；目录模式只接受文件名以三位数字扩展名结尾的S-57文件。单批次直接上传1至5000个文件、总量最大5GB。接口在文件安全校验和持久化后返回`queued`批次，GDAL处理仅由Worker执行。

批次详情中的单元项返回`cellName`、`status`、`stage`、`progress`、`updateCount`、`currentUpdate`、`datasetId`、`errorCode`和`errorMessage`。若单元已存在，Worker自动跳过不高于当前更新号的文件，并仅追加后续连续更新；无新增文件时返回`up_to_date`阶段。若历史源文件丢失且批次未提供对应文件，返回`S57_HISTORICAL_SOURCE_MISSING`。批次状态为`queued/running/succeeded/partial_failed/failed`。

## 8. 导入任务接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/import-jobs` | 任务列表 |
| GET | `/admin/import-jobs/{jobId}` | 任务、阶段和错误详情 |
| POST | `/admin/import-jobs/{jobId}/retry` | 重试失败任务 |
| POST | `/admin/import-jobs/{jobId}/cancel` | 取消尚未完成任务 |
| GET | `/admin/import-jobs/{jobId}/logs` | 下载或分页查看脱敏日志 |

前端一期通过轮询任务详情获取进度，默认间隔2秒，任务终止后停止轮询。

## 9. 图层和样式接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/admin/layers` | 管理员 | 图层目录，仅返回未删除数据集的当前有效版本图层 |
| GET | `/admin/layers/{layerId}` | 管理员 | 图层详情 |
| PATCH | `/admin/layers/{layerId}` | 管理员 | 查询、导出和元数据配置 |
| POST | `/admin/layers/{layerId}/publish` | 管理员 | 发布或重新发布 |
| POST | `/admin/layers/{layerId}/disable` | 管理员 | 停用图层 |
| GET | `/admin/styles` | 管理员 | 样式列表 |
| POST | `/admin/styles` | 管理员 | 上传并校验SLD |
| PATCH | `/admin/styles/{styleId}` | 管理员 | 修改样式元数据 |
| DELETE | `/admin/styles/{styleId}` | 管理员 | 软删除未使用样式 |
| GET | `/layers/{layerId}/metadata` | 登录用户 | 已发布图层元数据 |
| GET | `/layers/{layerId}/legend` | 登录用户 | 图例信息或GeoServer图例代理 |

图例接口返回后端构造的只读`GetLegendGraphic`地址，不暴露GeoServer管理凭据。

## 10. 地图查询接口

### 10.1 要素识别

`POST /layers/{layerId}/identify`

```json
{
  "coordinate": [80.12, 72.34],
  "crs": "EPSG:4326",
  "tolerance": 8,
  "resolution": 250
}
```

返回最多配置数量的要素摘要。属性只包含图层允许字段。

### 10.2 属性表

`POST /layers/{layerId}/features/search`

```json
{
  "page": 1,
  "pageSize": 50,
  "filters": [
    {"field": "objectClass", "operator": "eq", "value": "DEPARE"}
  ],
  "bbox": null,
  "bboxCrs": "EPSG:4326",
  "sort": [{"field": "id", "order": "asc"}]
}
```

允许操作符由字段类型决定，至少包括 `eq`、`ne`、`contains`、`gt`、`gte`、`lt`、`lte` 和 `in`。字段和操作符必须通过服务端白名单验证。

### 10.3 单要素定位

`GET /layers/{layerId}/features/{featureId}` 返回允许属性、几何摘要和范围，用于表格与地图联动。

## 11. 导出接口

`POST /layers/{layerId}/exports`

```json
{
  "format": "csv",
  "filters": [],
  "bbox": null,
  "fields": ["objectClass", "name"]
}
```

一期只允许 `csv` 和 `geojson`。服务端应用与查询相同的字段和数量限制。超出限制返回 `EXPORT_LIMIT_EXCEEDED`，不得自动导出完整表。

## 12. 底图和系统配置接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/base-maps` | 登录用户 | 当前启用底图 |
| GET | `/admin/base-maps` | 管理员 | 全部底图配置 |
| POST | `/admin/base-maps` | 管理员 | 创建WMTS/XYZ底图 |
| PATCH | `/admin/base-maps/{baseMapId}` | 管理员 | 修改或启停 |
| DELETE | `/admin/base-maps/{baseMapId}` | 管理员 | 软删除 |

XYZ底图的`urlTemplate`使用`{z}/{x}/{y}`模板；WMTS底图的`urlTemplate`填写GetCapabilities地址，前端从能力文档读取首个图层和矩阵集。底图坐标系必须与当前地图投影一致。
| GET | `/admin/settings` | 管理员 | 可管理系统配置 |
| PATCH | `/admin/settings` | 管理员 | 更新允许配置 |

## 13. 演示数据接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/demo/ais/vessels` | 返回演示船位，响应含 `isDemo=true` |
| POST | `/demo/weather/point` | 返回演示温度、风、浪数据 |

水文气象请求：

```json
{
  "coordinate": [80.0, 70.0],
  "crs": "EPSG:4326"
}
```

响应必须包含 `isDemo`、`disclaimer`、数据时间和指标单位。

## 14. 审计与健康检查

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/admin/audit-logs` | 管理员 | 审计日志分页查询 |
| GET | `/health/live` | 公开或内网 | 进程存活 |
| GET | `/health/ready` | 公开或内网 | 数据库、存储和必要依赖就绪 |

就绪检查不得执行高成本GeoServer全量扫描。

## 15. 主要错误代码

- `AUTH_INVALID_CREDENTIALS`
- `AUTH_ACCOUNT_DISABLED`
- `AUTH_RATE_LIMITED`
- `FORBIDDEN`
- `PROJECT_NOT_FOUND`
- `PROJECT_PUBLISH_VALIDATION_FAILED`
- `UPLOAD_TOO_LARGE`
- `UPLOAD_UNSUPPORTED_FORMAT`
- `UPLOAD_ARCHIVE_UNSAFE`
- `DATASET_IN_USE`
- `S57_CELL_MISMATCH`
- `S57_UPDATE_GAP`
- `S57_EDITION_MISMATCH`
- `IMPORT_JOB_CONFLICT`
- `IMPORT_FAILED`
- `GEOSERVER_PUBLISH_FAILED`
- `LAYER_NOT_AVAILABLE`
- `QUERY_FIELD_NOT_ALLOWED`
- `QUERY_LIMIT_EXCEEDED`
- `EXPORT_LIMIT_EXCEEDED`
