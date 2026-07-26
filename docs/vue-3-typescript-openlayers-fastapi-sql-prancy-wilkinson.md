# S-57 海图图层批量加载与智能筛选实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留现有“数据集摘要 → 展开后读取内部图层 → 单图层按需创建 WMS → 关闭即销毁”的默认懒加载机制下，增加由用户主动触发的 S-57 数据集批量解析、智能筛选、分批加载、取消和精确卸载，并增强 S-57 更新链缺失诊断。

**Architecture:** 后端以 `s57_layer_catalog.py` 作为唯一分类事实来源：新导入图层把分类快照合并到 `layers.metadata_json.s57`，旧图层由 resolve API 动态回退分类；新增项目级 resolve API 一次完成权限、当前有效版本、ProjectLayer、可用性、样式和 profile 筛选。前端只维护类型、标签和展示顺序，批量操作仍调用现有 `attachWmsLayer()` / `detachWmsLayer()`，以 5 层一批、批间 200ms 的节奏创建 WMS 对象，不建立第二套加载实现。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy、PostgreSQL/PostGIS、GDAL/OGR、GeoServer、Vue 3、TypeScript、Element Plus、OpenLayers 10、Vitest、pytest、ruff。

## Context

当前地图工作台只在展开数据集后请求内部物理图层，并在逐个打开图层时创建 `TileWMS`。对于包含十几至数十个空间对象类的 S-57 Cell，用户需要反复展开和开关图层；同时，DSID/C_AGGR 等非空间对象、未发布图层、元数据质量层和未映射样式层不适合被无差别加载。此次变更要在不改变项目数据集级配置模型、不新增数据库表、不改变导入/回滚/查询/导出/投影语义的前提下，为用户提供受控的批量加载能力，并保证不完整更新链不会生成候选版本或发布资源。

现有关键复用点：

- `backend/app/services/s57_styles.py:85-87`：`preset_for_object_class()`，唯一的对象类样式映射事实来源。
- `backend/app/services/importer.py:247-380`：S-57 图层创建、metadata 写入和样式应用。
- `backend/app/api/projects.py:115-210`：地图摘要和单数据集内部图层接口；已有 published 项目、ProjectLayer、当前版本和 available 图层查询基础。
- `frontend/src/views/MapWorkspaceView.vue:300-347`：`attachWmsLayer()` / `detachWmsLayer()` 和瓦片状态监听。
- `frontend/src/views/MapWorkspaceView.vue:349-391`：数据集懒加载、单图层开关和投影切换。
- `frontend/src/views/MapWorkspaceView.vue:475-557`：属性查询和 Identify 的 AbortController。
- `backend/app/services/s57_batch.py:44-77,386-568`：批量文件分组、更新链校验和候选版本创建。

## Global Constraints

- 保留 `GET /projects/{projectId}/map-config` 的数据集摘要语义和 `GET /projects/{projectId}/map-datasets/{datasetId}/layers` 的懒加载语义。
- 新功能只能由用户主动触发；不得在项目打开时自动批量实例化 WMS。
- 不删除、不改名现有 API；新增字段必须是向后兼容的加法变更。
- 不新增数据库表、列或 Alembic 迁移；新增分类快照写入 `Layer.metadata_json["s57"]`。
- 后端是分类事实来源；前端不得复制对象类分类集合或样式映射集合。
- API 字段使用 camelCase；Python、数据库字段和内部函数使用 snake_case。
- 所有 API 错误使用现有 `AppError` 统一结构，并携带现有 requestId。
- `DSID` 和 `C_AGGR` 永远不可渲染；其他对象按几何有效性和前缀回退，不得因未知代码失败。
- 批量加载必须调用现有 WMS attach/detach 逻辑；不得出现独立的第二套 `TileWMS` 创建流程。
- 批量常量固定为：`BULK_ATTACH_BATCH_SIZE = 5`、`BULK_ATTACH_INTERVAL_MS = 200`、`BULK_CONFIRM_THRESHOLD = 40`、`BULK_HARD_LIMIT = 120`。
- 不等待所有瓦片加载完成才启动下一批；只控制 WMS 图层对象创建节奏。
- 不提交真实 ENC/S-57 文件、解压结果、凭据、`.env`、本地路径或调试输出。
- Python 依赖和虚拟环境只能位于 `F:/polar-gis/.venv`；Node 依赖只能位于 `F:/polar-gis/frontend/node_modules`。
- 用户本次明确要求更新 `docs/02`、`docs/04`、`docs/05`，该直接要求优先于 CLAUDE.md 中对 01–08 的一般冻结约定；不修改 `docs/03`、`docs/06`、`docs/07`、`docs/08`。
- 每次代码更新必须同步更新 `docs/09-system-architecture.md`、`docs/10-work-log.md`、`docs/11-work-summary.md`，随后提交并推送 `origin master`。
- 每个提交消息末尾包含：`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

---

## 实际影响文件清单

### 新增文件

- `backend/app/services/s57_layer_catalog.py` — S-57 对象分类、几何有效性、中文名称、优先级和 profile 规则。
- `backend/tests/test_s57_layer_catalog.py` — 分类集合完整性、回退、排序和不可变性测试。
- `backend/tests/test_importer.py` — S-57 导入 metadata 合并和 featureCount/styleMapped 测试。
- `frontend/src/api/projects.ts` — 项目地图图层 GET 与 resolve API 客户端。
- `frontend/src/api/projects.test.ts` — URL、payload 和 AbortSignal 测试。
- `frontend/src/utils/mapLayerBatch.ts` — 批量候选排序/去重、范围转换和批次等待纯函数。
- `frontend/src/utils/mapLayerBatch.test.ts` — 阈值、排序、去重、取消和 extent 转换测试。
- `frontend/src/views/MapWorkspaceView.test.ts` — 数据集选择、批量加载/取消/卸载、WMS 复用和投影重建组件测试。

### 修改文件

- `backend/app/services/importer.py`
- `backend/app/schemas.py`
- `backend/app/api/projects.py`
- `backend/app/services/s57_batch.py`
- `backend/app/api/datasets.py`
- `backend/tests/test_projects.py`
- `backend/tests/test_s57_batch.py`
- `frontend/src/types/index.ts`
- `frontend/src/views/MapWorkspaceView.vue`
- `frontend/src/styles.css`
- `docs/02-system-design.md`
- `docs/04-api-design.md`
- `docs/05-ui-ux-design.md`
- `docs/09-system-architecture.md`
- `docs/10-work-log.md`
- `docs/11-work-summary.md`
- `docs/12-user-manual.md`

### 明确不修改

- `backend/app/models.py`
- `backend/migrations/**`
- 现有导入、回滚、查询、导出、样式和项目数据集配置的数据模型。
- `docs/01-requirements.md`、`docs/03-data-design.md`、`docs/06-development-plan.md`、`docs/07-testing.md`、`docs/08-deployment.md`。

---

### Task 1: 建立后端 S-57 分类事实来源

**Files:**
- Create: `backend/app/services/s57_layer_catalog.py`
- Create: `backend/tests/test_s57_layer_catalog.py`
- Modify: `docs/09-system-architecture.md`
- Modify: `docs/10-work-log.md`
- Modify: `docs/11-work-summary.md`

**Interfaces:**
- Produces: `S57LayerRule`、`classify_s57_layer(code, geometry_type, style_mapped)`、`has_valid_geometry(geometry_type)`、稳定排序键。
- Consumes: 无数据库、FastAPI、GDAL 或 GeoServer 依赖；分类模块必须保持纯函数。

- [ ] **Step 1: 写分类集合和主分类唯一性的失败测试**

在 `backend/tests/test_s57_layer_catalog.py` 中精确声明用户给定集合并验证：

```python
CORE_CHART = {
    "COALNE", "LNDARE", "DEPARE", "DEPCNT", "SOUNDG", "SEAARE",
    "ICEARE", "OBSTRN", "WRECKS", "UWTROC", "CTNARE", "UNSARE",
}
NAVIGATION_RECOMMENDED = {
    "LIGHTS", "FOGSIG", "BOYCAR", "BOYINB", "BOYISD", "BOYSAW",
    "BOYSPP", "BCNISD", "BCNSPP", "TOPMAR", "RTPBCN", "RDOSTA",
    "RDOCAL", "RETRFL", "RCRTCL", "RCTLPT", "TSSBND", "TSSLPT",
    "TSEZNE", "TSSRON", "RESARE", "DMPGRD", "HRBARE", "SLCONS",
}
OPTIONAL_THEMATIC = {
    "ADMARE", "BUAARE", "BUISGL", "CANALS", "CBLSUB", "CONZNE",
    "COSARE", "CURENT", "EXEZNE", "FNCLNE", "FSHZNE", "LAKARE",
    "LNDELV", "LNDMRK", "LNDRGN", "LOCMAG", "MAGVAR", "MARCUL",
    "OFSPLF", "OSPARE", "PILPNT", "PIPSOL", "RIVERS", "SBDARE",
    "STSLNE", "TESARE",
}
METADATA_QUALITY = {"M_COVR", "M_CSCL", "M_NPUB", "M_NSYS", "M_QUAL"}
NON_SPATIAL = {"DSID", "C_AGGR"}
```

测试必须断言：集合互不相交；每个已知对象只属于一个主分类；核心和航行推荐集合与规格完全相等，而不是“至少包含”。

- [ ] **Step 2: 写规则行为的失败测试**

覆盖以下精确行为：

```python
assert classify_s57_layer("depare", "Multi Polygon", True).code == "DEPARE"
assert classify_s57_layer("DEPARE", "Multi Polygon", True).display_priority == 10
assert classify_s57_layer("COALNE", "Line String", True).display_priority == 20
assert classify_s57_layer("SOUNDG", "Point", True).display_priority == 30
assert classify_s57_layer("WRECKS", "Point", True).display_priority == 40
assert classify_s57_layer("LIGHTS", "Point", True).display_priority == 50
assert classify_s57_layer("TSSBND", "Line String", True).display_priority == 60
assert classify_s57_layer("RESARE", "Multi Polygon", True).display_priority == 70
assert classify_s57_layer("ADMARE", "Multi Polygon", True).display_priority == 100
assert classify_s57_layer("M_QUAL", "Multi Polygon", True).display_priority == 200
assert classify_s57_layer("DSID", None, False).display_priority == 900
```

同时验证：

- `DSID`、`C_AGGR` 即使传入有效几何也 `renderable=False`。
- metadata_quality 默认 `recommended=False`。
- 已知核心/航行对象只有 `style_mapped=True` 时才 `recommended=True`。
- 未映射核心/航行层仍保留其 `load_profile`，但不进入自动推荐加载。
- 未知有几何对象进入 `optional_other`，优先级 100，可手动/all_spatial 加载。
- 未知无几何对象进入 `non_spatial`，优先级 900。
- 未知 `M_` 有几何对象进入 `metadata_quality`。
- 未知 `C_` 且无几何对象进入 `non_spatial`。
- `GeometryCollection` 是有效几何，不得沿用现有错误的非空间判断。
- 输出排序按 `(display_priority, code)` 稳定。
- `S57LayerRule` 为 `@dataclass(frozen=True, slots=True)`，修改字段会抛 `FrozenInstanceError`。

- [ ] **Step 3: 运行测试确认 RED**

```bash
cd F:/polar-gis/backend
F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_s57_layer_catalog.py -v
```

Expected: 因 `s57_layer_catalog` 尚不存在而失败。

- [ ] **Step 4: 实现不可变分类目录**

`S57LayerRule` 使用以下字段和语义：

```python
@dataclass(frozen=True, slots=True)
class S57LayerRule:
    code: str
    object_name_zh: str
    display_category: str
    load_profile: str
    display_priority: int
    recommended: bool
    renderable: bool
    default_visible: bool
```

实现要求：

- 所有输入代码 `strip().upper()`；支持 `workspace:CODE` 取末段。
- 为规格中每个已知代码提供非空中文名称；可复用 `frontend/src/utils/s57ObjectNames.ts` 已有标签，但最终权威映射保存在后端目录中。
- `display_category` 使用稳定值：`bathymetry`、`land_coast`、`depth`、`hazard`、`navigation_aid`、`routing`、`restriction_harbor`、`optional_thematic`、`metadata_quality`、`non_spatial`、`optional_other`。
- `load_profile` 精确使用：`core_chart`、`navigation_recommended`、`optional_thematic`、`metadata_quality`、`non_spatial`、`optional_other`。
- `default_visible=False` 对所有规则成立，保证分类元数据不改变现有默认懒加载行为。
- `recommended` 只表示适合核心/推荐自动模式，必须同时满足类别属于核心或航行推荐且 `style_mapped=True`。
- 几何无效集合只包含空值、`unknown`、`none`、`无`、`无几何` 等明确无几何值。

- [ ] **Step 5: 运行分类测试和 lint 确认 GREEN**

```bash
cd F:/polar-gis/backend
F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_s57_layer_catalog.py -v
F:/polar-gis/.venv/Scripts/python.exe -m ruff check app/services/s57_layer_catalog.py tests/test_s57_layer_catalog.py
```

Expected: 全部通过。

- [ ] **Step 6: 更新 living docs、提交并推送**

在 09 记录分类服务边界，在 10 记录测试/决策，在 11 记录阶段成果；随后：

```bash
git add backend/app/services/s57_layer_catalog.py backend/tests/test_s57_layer_catalog.py docs/09-system-architecture.md docs/10-work-log.md docs/11-work-summary.md
git commit -m "feat: 新增S-57图层统一分类目录" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push origin master
```

---

### Task 2: 在 S-57 导入期合并分类 metadata

**Files:**
- Modify: `backend/app/services/importer.py:247-380`
- Create: `backend/tests/test_importer.py`
- Modify: `docs/09-system-architecture.md`
- Modify: `docs/10-work-log.md`
- Modify: `docs/11-work-summary.md`

**Interfaces:**
- Consumes: `classify_s57_layer()`、`has_valid_geometry()`、现有 `preset_for_object_class()`。
- Produces: 新导入图层的 `metadata_json["s57"]` 快照；旧顶层样式字段保持兼容。

- [ ] **Step 1: 写 metadata 合并失败测试**

为纯 helper `merge_s57_layer_metadata()` 编写测试，输入现有 metadata、GDAL layer inspection、geometry type 和 style mapped 状态，断言：

```python
result = merge_s57_layer_metadata(
    {"sourceLayer": "DEPARE", "legacy": "keep", "s57": {"custom": "keep"}},
    source_layer={"name": "DEPARE", "featureCount": 923},
    geometry_type="Multi Polygon",
    style_mapped=True,
)
assert result["legacy"] == "keep"
assert result["s57"]["custom"] == "keep"
assert result["s57"]["objectClass"] == "DEPARE"
assert result["s57"]["objectNameZh"] == "水深区域"
assert result["s57"]["displayCategory"] == "bathymetry"
assert result["s57"]["loadProfile"] == "core_chart"
assert result["s57"]["displayPriority"] == 10
assert result["s57"]["recommended"] is True
assert result["s57"]["renderable"] is True
assert result["s57"]["styleMapped"] is True
assert result["s57"]["featureCount"] == 923
```

再覆盖 featureCount 缺失/非法时为 `None`，以及非 S-57 普通矢量导入不写 `metadata.s57`。

- [ ] **Step 2: 写 importer 集成失败测试**

通过 monkeypatch 模拟 ogrinfo、ogr2ogr 和 GeoServer，验证：

- `_import_vector_layers()` 对 S-57 使用 `preset_for_object_class(source_name)` 判断 styleMapped。
- metadata 原字段和嵌套原字段都保留，不整体覆盖。
- `_apply_s57_style()` 映射成功后继续保留顶层 `recommendedStyleCode`、`recommendedStyleId`、`s57StyleStatus=mapped`。
- 未映射空间层写 `s57StyleStatus=unmapped`，嵌套 `styleMapped=false`，但仍 `renderable=true`。
- DSID/C_AGGR 写 `renderable=false`，且不会调用 GeoServer feature type 发布。
- 现有导入结果、Layer status 和版本激活流程不变。

- [ ] **Step 3: 运行测试确认 RED**

```bash
cd F:/polar-gis/backend
F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_importer.py -v
```

Expected: helper 和新 metadata 尚不存在。

- [ ] **Step 4: 最小实现 metadata 合并**

在 importer 中：

- 仅当 `dataset.data_type == DatasetType.S57.value` 时调用分类 helper。
- 从 `source_layer["name"]` 获取对象类；不要使用生成后的数据库 Layer code 作为首选对象类。
- 从 `source_layer.get("featureCount")` 读取要素数；不可转换时写 `None`。
- 先复制 `existing = dict(metadata_json or {})`，再复制 `s57 = dict(existing.get("s57") or {})`，最后只更新规定字段。
- `_apply_s57_style()` 更新顶层兼容字段时，同时浅合并 `metadata.s57`，不得丢失 featureCount、分类和自定义字段。
- 用 `has_valid_geometry()` 替换 importer 当前重复的字符串非空间判断，避免生成第四套规则。

- [ ] **Step 5: 运行定向测试、原 S-57 测试和 lint**

```bash
cd F:/polar-gis/backend
F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_importer.py tests/test_s57.py -v
F:/polar-gis/.venv/Scripts/python.exe -m ruff check app/services/importer.py tests/test_importer.py
```

Expected: 全部通过；不需要数据库迁移。

- [ ] **Step 6: 更新 living docs、提交并推送**

```bash
git add backend/app/services/importer.py backend/tests/test_importer.py docs/09-system-architecture.md docs/10-work-log.md docs/11-work-summary.md
git commit -m "feat: 写入S-57图层分类元数据" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push origin master
```

---

### Task 3: 新增项目级批量图层 resolve API

**Files:**
- Modify: `backend/app/schemas.py:122-155`
- Modify: `backend/app/api/projects.py:115-210`
- Modify: `backend/tests/test_projects.py`
- Modify: `docs/04-api-design.md`
- Modify: `docs/09-system-architecture.md`
- Modify: `docs/10-work-log.md`
- Modify: `docs/11-work-summary.md`

**Interfaces:**
- Produces: `POST /api/v1/projects/{projectId}/map-layers/resolve`。
- Produces schemas: `BulkMapLayerResolveRequest`、`BulkResolvedLayer`、`BulkResolvedDataset`、`BulkLayerResolveSummary`、`BulkMapLayerResolveResponse`。
- Consumes: `classify_s57_layer()`、`preset_for_object_class()`、现有 project published 访问边界和 ProjectLayer 配置。

- [ ] **Step 1: 写 schema 和错误码失败测试**

测试以下精确错误：

- 未登录：401。
- 项目不存在/未发布：现有 `PROJECT_NOT_FOUND`。
- datasetIds 为空：现有 `VALIDATION_ERROR`。
- datasetIds 超过 100：`BULK_LAYER_DATASET_LIMIT_EXCEEDED`。
- profile 不在 `core_chart`、`navigation_recommended`、`all_spatial`：`INVALID_LAYER_PROFILE`。
- 任一 datasetId 不是当前项目已关联的 S-57 数据集：`PROJECT_DATASET_NOT_FOUND`，details 返回缺失 datasetIds。
- 已关联但没有可加载图层：`NO_LOADABLE_LAYERS`，details 包含 summary。

为确保指定错误码可控，`BulkMapLayerResolveRequest.profile` 使用字符串字段并在 endpoint/service 中显式校验；datasetIds 只在 schema 中校验最少 1 项，100 项上限由 endpoint 显式抛 `AppError`。

- [ ] **Step 2: 写权限、版本、状态和去重失败测试**

构造同一项目内多个 S-57 数据集，包含：当前 valid 版本、历史版本、available/disabled/publish_failed/processing 图层、软删除图层、未配置数据集和重复 ProjectLayer 查询结果。断言：

- 只读取 `Dataset.current_version_id` 指向且 `DatasetVersion.status == valid` 的版本。
- 只把 `ProjectLayer` 当前关联的数据集视为可解析数据集。
- 响应 arrays 只包含 `Layer.status == available` 且未软删除的记录；其他状态只增加 `unavailableSkippedCount`。
- 同一 Layer ID 只返回一次。
- 不返回本地 source_table、storage_key、GeoServer 管理凭据或内部路径。
- 普通已登录用户继续访问 published 项目；不扩展项目成员 ACL。

- [ ] **Step 3: 写 profile、回退和统计失败测试**

固定候选语义：

- `core_chart`：仅核心对象进入 profile 候选。
- `navigation_recommended`：核心 + 航行推荐对象进入 profile 候选。
- `all_spatial`：所有有有效几何且 renderable 的核心、航行推荐、optional_thematic、optional_other 对象进入 profile 候选；未映射样式允许 loadable。
- metadata_quality 和 non_spatial 参与跳过统计；`includeMetadata=false` 时 metadata_quality 不进入 `datasets[].layers`，non_spatial 在任何情况下都不进入可加载图层数组，只增加 `nonSpatialSkippedCount`。
- `includeMetadata=true` 会在任一 profile 的业务候选之后追加 available、renderable 的 metadata_quality 图层；non_spatial 永远不可加载、永远不返回给 attach 队列。
- 核心/推荐 profile 中 `styleMapped=false` 的空间候选可返回诊断项，但必须 `loadable=false`、`skipReason="unmapped_style"`；all_spatial 中同一层 `loadable=true`。
- available 空间层缺少 GeoServer workspace/layer name 时 `loadable=false`、`skipReason="unpublished"`。

summary 精确包含：

```python
class BulkLayerResolveSummary(ApiModel):
    dataset_count: int
    candidate_count: int
    loadable_count: int
    metadata_skipped_count: int
    non_spatial_skipped_count: int
    unavailable_skipped_count: int
    unmapped_style_count: int
```

`candidateCount` 定义为：选中 profile 的业务对象 + metadata/non-spatial 跳过诊断 + 同范围 unavailable 记录的去重总数；profile 外的 optional 类别不计入核心/推荐 candidateCount。

- [ ] **Step 4: 写响应字段和稳定排序失败测试**

`BulkResolvedLayer` 至少断言以下 camelCase 字段：

```json
{
  "id": "uuid",
  "code": "database-layer-code",
  "objectClass": "DEPARE",
  "objectNameZh": "水深区域",
  "name": "DEPARE",
  "geometryType": "Multi Polygon",
  "geoserverWorkspace": "polar_gis",
  "geoserverLayerName": "dataset_v1_depare",
  "serviceUrl": "/geoserver/polar_gis/wms",
  "styleName": "s57_depth",
  "opacity": 1.0,
  "minZoom": null,
  "maxZoom": null,
  "extent": [-10.0, 60.0, 10.0, 75.0],
  "featureCount": 923,
  "displayCategory": "bathymetry",
  "loadProfile": "core_chart",
  "displayPriority": 10,
  "recommended": true,
  "renderable": true,
  "loadable": true,
  "styleMapped": true,
  "skipReason": null,
  "queryable": true,
  "exportable": true,
  "groupName": "电子海图",
  "sortOrder": 0
}
```

排序规则：数据集按项目 sortOrder、datasetCode、datasetId；每个数据集内图层严格按 displayPriority、objectClass、Layer ID。重复请求结果顺序完全一致。

- [ ] **Step 5: 运行 API 测试确认 RED**

```bash
cd F:/polar-gis/backend
F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_projects.py -v
```

Expected: 新 schema/路由不存在或断言失败。

- [ ] **Step 6: 实现共享查询和旧数据动态回退**

实现小范围 helper，避免改变旧 GET 语义：

```python
def s57_object_class(layer: Layer) -> str:
    # metadata.s57.objectClass -> metadata.sourceLayer -> layer.name -> layer.code


def style_mapped_for_layer(layer: Layer) -> bool:
    # metadata.s57.styleMapped -> s57StyleStatus -> preset_for_object_class(object_class)


def project_dataset_layer_links(
    db: Session,
    project_id: UUID,
    dataset_ids: Collection[UUID],
    *,
    include_unavailable: bool,
) -> list[ProjectLayer]:
    ...
```

实现要求：

- resolve 查询包含 ProjectLayer、Layer、DatasetVersion、Dataset、Style，避免逐层 N+1。
- 先验证所有 requested datasetIds 属于当前 published 项目且 data_type 为 S-57，再分类。
- old metadata 没有 `s57` 时只在响应中动态调用分类函数，不写回数据库。
- styleName 优先使用 ProjectLayer 指定样式，否则使用 metadata 中 recommendedStyleCode；不改变旧 GET 的 styleName 语义。
- extent 仅从可信 `metadata.s57.extent` 返回，并定义为 EPSG:4326；无可信范围返回 null。
- featureCount 缺失返回 null。
- `MapDatasetConfig` 向后兼容地新增 `dataType`，供前端只对 S-57 数据集启用批量复选框。
- 现有单数据集 GET 继续返回全部当前 available 图层，不应用 profile 过滤；可向后兼容地补充 minZoom/maxZoom/extent，但不得删改旧字段。

- [ ] **Step 7: 运行定向测试、OpenAPI 和 lint**

```bash
cd F:/polar-gis/backend
F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_projects.py tests/test_s57_layer_catalog.py -v
F:/polar-gis/.venv/Scripts/python.exe -m ruff check app/api/projects.py app/schemas.py tests/test_projects.py
F:/polar-gis/.venv/Scripts/python.exe -c "from app.main import app; paths=app.openapi()['paths']; assert '/api/v1/projects/{project_id}/map-layers/resolve' in paths"
```

Expected: 全部通过，OpenAPI 包含新 POST。

- [ ] **Step 8: 更新 API/living docs、提交并推送**

```bash
git add backend/app/schemas.py backend/app/api/projects.py backend/tests/test_projects.py docs/04-api-design.md docs/09-system-architecture.md docs/10-work-log.md docs/11-work-summary.md
git commit -m "feat: 新增项目S-57图层批量解析接口" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push origin master
```

---

### Task 4: 增加前端类型、API 客户端和批量纯逻辑

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/projects.ts`
- Create: `frontend/src/api/projects.test.ts`
- Create: `frontend/src/utils/mapLayerBatch.ts`
- Create: `frontend/src/utils/mapLayerBatch.test.ts`
- Modify: `docs/09-system-architecture.md`
- Modify: `docs/10-work-log.md`
- Modify: `docs/11-work-summary.md`

**Interfaces:**
- Produces: `S57LoadProfile`、`BulkMapLayerResolveRequest`、`BulkMapLayerResolveResponse`、`BulkResolvedLayer`、`BulkLayerProgress`。
- Produces: `resolveProjectMapLayers(projectId, payload, signal?)`、`getProjectDatasetMapLayers(projectId, datasetId, signal?)`。
- Produces pure helpers: 去重/排序、硬上限判断、extent 转换、批间等待。

- [ ] **Step 1: 写 API 客户端失败测试**

Mock `api.post` / `api.get`，断言：

```ts
await resolveProjectMapLayers('p1', {
  datasetIds: ['d1', 'd2'],
  profile: 'navigation_recommended',
  includeMetadata: false,
}, signal)
```

调用：

```ts
api.post('/projects/p1/map-layers/resolve', payload, { signal })
```

同时验证单数据集 GET 仍调用 `/projects/p1/map-datasets/d1/layers`，且两个方法都复用 `frontend/src/api/client.ts`，不自行处理 token、刷新、错误或 request ID。

- [ ] **Step 2: 写批量纯逻辑失败测试**

`mapLayerBatch.test.ts` 覆盖：

- 按 displayPriority、objectClass、id 稳定排序。
- 重复 layer ID 只保留一次。
- 已在 `loadedLayerIds` 中的项计入 skipped，不重新 attach。
- `loadable=false` 和 non_spatial 永远不进入 attach 候选。
- 候选 40 个不确认，41 个需要确认；120 个允许，121 个阻止。
- AbortSignal 或 generation 改变后 `waitForBulkInterval()` 立即停止后续批次。
- EPSG:4326 extent 转换到当前投影；null/非法 extent 不传给 TileLayer。

- [ ] **Step 3: 运行前端测试确认 RED**

```bash
cd F:/polar-gis/frontend
npm test -- src/api/projects.test.ts src/utils/mapLayerBatch.test.ts
```

Expected: 新文件和类型不存在。

- [ ] **Step 4: 定义精确类型和常量**

类型至少包含：

```ts
export type S57LoadProfile = 'core_chart' | 'navigation_recommended' | 'all_spatial'

export interface BulkMapLayerResolveRequest {
  datasetIds: string[]
  profile: S57LoadProfile
  includeMetadata?: boolean
}

export interface BulkLayerProgress {
  total: number
  processed: number
  succeeded: number
  failed: number
  skipped: number
  attachedLayerIds: string[]
  errors: Array<{ layerId: string; layerName: string; message: string }>
}
```

`BulkResolvedLayer` 与后端字段逐一对应；`MapDatasetConfig` 增加 `dataType`；`MapLayerConfig` 以可选字段增加 `minZoom`、`maxZoom`、`extent`、`objectClass`、`objectNameZh`，不破坏现有调用。

常量名和数值必须与规格完全一致：

```ts
export const BULK_ATTACH_BATCH_SIZE = 5
export const BULK_ATTACH_INTERVAL_MS = 200
export const BULK_CONFIRM_THRESHOLD = 40
export const BULK_HARD_LIMIT = 120
```

- [ ] **Step 5: 实现 API 客户端和纯 helper**

`projects.ts` 只负责类型化请求并返回 `response.data`。`mapLayerBatch.ts` 不 import Vue 或 OpenLayers Map；可 import `transformExtent` 完成范围转换，但不得创建 TileWMS。

- [ ] **Step 6: 运行测试、typecheck 和 build**

```bash
cd F:/polar-gis/frontend
npm test -- src/api/projects.test.ts src/utils/mapLayerBatch.test.ts
npm run typecheck
npm run build
```

Expected: 全部通过。

- [ ] **Step 7: 更新 living docs、提交并推送**

```bash
git add frontend/src/types/index.ts frontend/src/api/projects.ts frontend/src/api/projects.test.ts frontend/src/utils/mapLayerBatch.ts frontend/src/utils/mapLayerBatch.test.ts docs/09-system-architecture.md docs/10-work-log.md docs/11-work-summary.md
git commit -m "feat: 增加前端S-57批量加载契约" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push origin master
```

---

### Task 5: 在地图工作台实现批量选择、加载、取消和卸载

**Files:**
- Modify: `frontend/src/views/MapWorkspaceView.vue:1-775`
- Modify: `frontend/src/styles.css:336-424`
- Create: `frontend/src/views/MapWorkspaceView.test.ts`
- Modify: `docs/05-ui-ux-design.md`
- Modify: `docs/09-system-architecture.md`
- Modify: `docs/10-work-log.md`
- Modify: `docs/11-work-summary.md`
- Modify: `docs/12-user-manual.md`

**Interfaces:**
- Consumes: Task 4 API 和 helper。
- Must preserve/reuse: `attachWmsLayer()`、`detachWmsLayer()`、瓦片 loadstart/loadend/loaderror、300ms loading 延迟、`wmsLayers` Map、属性/Identify AbortController、投影切换流程。
- Produces view methods: `loadSelectedDatasets(profile)`、`loadResolvedLayersInBatches(layers)`、`cancelBulkLoad()`、`unloadSelectedDatasets()`、`unloadAllChartLayers()`。

- [ ] **Step 1: 写组件失败测试：选择与 API 请求**

使用 Vitest、`@vue/test-utils` 和 OpenLayers module mocks，覆盖：

- 不展开数据集也能勾选 S-57 数据集。
- 非 S-57 数据集复选框禁用或不显示。
- “全选当前结果”只选择 `filteredGroups` 当前搜索命中的数据集。
- “清空选择”只清 Set，不卸载图层。
- 选择状态与图层 visible 状态互不影响。
- 加载推荐模式发送一个 resolve POST，payload 的 datasetIds/profile/includeMetadata 正确。

- [ ] **Step 2: 写组件失败测试：批次和失败隔离**

覆盖：

- 已加载 Layer ID 计 skipped，不调用 attach。
- `loadable=false` 和 non_spatial 不调用 attach。
- 每批最多创建 5 个 WMS，批次间使用 200ms fake timers。
- 一个 attach 抛错后，后续图层继续执行；进度记录 succeeded/failed/skipped。
- 41 个候选调用 `ElMessageBox.confirm`；121 个候选直接阻止且不调用 attach。
- cancel 后不再创建剩余图层；已创建图层保留，并可通过“卸载本次加载”清理。

- [ ] **Step 3: 写组件失败测试：卸载、投影和非业务图层保护**

覆盖：

- `unloadSelectedDatasets()` 只 detach 所选数据集关联的已加载图层。
- “卸载当前搜索结果图层”只处理当前过滤结果。
- `unloadAllChartLayers()` 只遍历业务 `runtimeLayers/wmsLayers`，不移除底图、AIS、气象、测量或高亮层。
- 切换 EPSG:3857/EPSG:3413 只重建 `loadedLayerIds` 中的图层，不 resolve 未加载数据集，不改变 `selectedDatasetIds`。
- 批量 resolve 得到的部分图层合并到 `dataset.layers` 时不得把 `dataset.loaded=true`；之后用户展开仍调用原 GET，合并完整目录并复用同 ID RuntimeLayer。

- [ ] **Step 4: 运行组件测试确认 RED**

```bash
cd F:/polar-gis/frontend
npm test -- src/views/MapWorkspaceView.test.ts
```

Expected: 新 UI、状态和方法尚不存在。

- [ ] **Step 5: 增加精确批量状态**

在 `MapWorkspaceView.vue` 中增加规格要求状态：

```ts
const selectedDatasetIds = ref(new Set<string>())
const loadedLayerIds = ref(new Set<string>())
const loadingLayerIds = ref(new Set<string>())
const failedLayerIds = ref(new Map<string, string>())
const bulkProgress = ref<BulkLayerProgress | null>(null)
const bulkCancelled = ref(false)
const bulkGeneration = ref(0)
```

要求：

- 每次增删 Set/Map 后替换为新实例，不能依赖数组引用或原地 mutation 触发 UI。
- 另存当前 resolve `AbortController` 和 `lastBulkAttachedLayerIds`，支持取消和“卸载本次加载”。
- RuntimeLayer 增加 datasetId 和事件清理信息，但不复制 TileWMS 配置逻辑。

- [ ] **Step 6: 小范围强化单图层 attach/detach，作为唯一 WMS 生命周期入口**

调整现有函数，而不是新增第二套实现：

- `attachWmsLayer(runtime)` 返回 attached/already-loaded/non-spatial 结果，批量和单图层都调用它。
- 创建 TileLayer 时应用：

```ts
new TileLayer({
  source,
  opacity: runtime.opacity,
  zIndex: 10,
  extent: transformedExtent || undefined,
  minZoom: runtime.config.minZoom ?? undefined,
  maxZoom: runtime.config.maxZoom ?? undefined,
})
```

- extent 按 API 契约从 EPSG:4326 转到 `currentCrs`。
- 使用 `ol/Observable` 的 `unByKey` 或等价稳定引用，detach 时显式解除 TileWMS 事件监听。
- 保留 300ms loading 延迟；只在 pendingTiles 从 0→1 时启动 timer，避免连续 start 无限后移。
- 新加载周期开始时允许旧 error 恢复；tileloaderror 更新 failedLayerIds，但不影响其他层。
- detach 清理：地图对象、event listeners、timer、TileLayer.dispose、wmsLayers、loading/failed 状态。
- 如果被卸载图层正显示属性表或执行 Identify，abort 对应请求并清空关联 UI 状态。
- 单图层 toggle、批量加载、批量卸载、投影重建全部走这两个函数。

- [ ] **Step 7: 实现 resolve 合并与分批创建**

`loadSelectedDatasets(profile)` 顺序：

1. 校验至少一个 selected S-57 dataset。
2. `bulkGeneration += 1`，新建 AbortController，重置本次进度。
3. 调用 `resolveProjectMapLayers()`。
4. 将 response datasets/layers 按 ID 合并到 RuntimeDataset/RuntimeLayer；复用已有对象，不重复 push。
5. 过滤 `loadable=false`、已 loaded、重复 ID；按 displayPriority、objectClass、id 排序。
6. 候选 >120：提示缩小选择范围并终止。
7. 候选 >40：显示确认；取消确认不创建图层。
8. 调用 `loadResolvedLayersInBatches()`。

`loadResolvedLayersInBatches()`：

- 每次取 5 项；同批逐项 try/catch 调用 `attachWmsLayer()`。
- 每批完成创建后等待 200ms，再检查 generation/cancelled。
- 不等待 tileloadend 才启动下一批；“成功”表示 WMS 对象成功创建，后续 tile error 可把该 ID 标记为失败。
- 单层失败只记录错误并继续。
- 进度结束后显示成功、失败、跳过数量；错误列表可展开。

`cancelBulkLoad()`：

- abort 尚未完成的 resolve 请求。
- 增加 generation/设置 cancelled，使后续批次停止。
- 不卸载已创建图层；提供“卸载本次加载”按钮精确清理 `lastBulkAttachedLayerIds`。

- [ ] **Step 8: 实现批量卸载与投影重建**

- `unloadSelectedDatasets()`：根据 RuntimeDataset.layers 找到 selected dataset 的业务图层并调用 detach。
- 当前搜索结果卸载：使用 filteredGroups 的 dataset IDs。
- `unloadAllChartLayers()`：仅遍历 runtimeLayers；不操作 baseMaps、aisLayer、measureLayer、weather 和其他 overlay。
- projection switch：保存当前 loadedLayerIds；以“保留逻辑 loaded 状态”模式 detach 旧投影对象；切 View 和底图；只 reattach 保存的 ID；selectedDatasetIds 不变，未加载层不创建。

- [ ] **Step 9: 增加紧凑 UI，不破坏 250–270px 面板**

在搜索框下、图层树上增加：

- 数据集行独立 checkbox。
- “全选当前结果”“清空选择”。
- 批量加载 dropdown：核心、推荐、全部可显示。
- 批量卸载 dropdown：所选数据集、当前搜索结果、全部海图图层。
- 运行时进度条、成功/失败/跳过数字、取消按钮、失败详情、卸载本次加载。

约束：

- 使用 Element Plus `small`/紧凑组件。
- 不增加全宽顶部栏或第二侧栏。
- `.layer-panel` 继续保持默认 270px、窄屏 250px。
- checkbox 不替代现有单图层显隐开关。
- 状态不能只靠颜色表达；需文字/数字。

- [ ] **Step 10: 运行前端定向和全量验证**

```bash
cd F:/polar-gis/frontend
npm test -- src/api/projects.test.ts src/utils/mapLayerBatch.test.ts src/views/MapWorkspaceView.test.ts
npm test
npm run typecheck
npm run build
```

Expected: 全部通过；生产构建成功。

- [ ] **Step 11: 更新 UI/living/user docs、提交并推送**

```bash
git add frontend/src/views/MapWorkspaceView.vue frontend/src/views/MapWorkspaceView.test.ts frontend/src/styles.css docs/05-ui-ux-design.md docs/09-system-architecture.md docs/10-work-log.md docs/11-work-summary.md docs/12-user-manual.md
git commit -m "feat: 实现S-57海图图层批量加载与卸载" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push origin master
```

---

### Task 6: 增强 S-57 更新链缺失详情

**Files:**
- Modify: `backend/app/services/s57_batch.py:44-77,386-500`
- Modify: `backend/app/schemas.py:291-307`
- Modify: `backend/app/api/datasets.py:206-223`
- Modify: `backend/tests/test_s57_batch.py`
- Modify: `docs/04-api-design.md`
- Modify: `docs/09-system-architecture.md`
- Modify: `docs/10-work-log.md`
- Modify: `docs/11-work-summary.md`
- Modify: `docs/12-user-manual.md`

**Interfaces:**
- Produces: 结构化链分析异常/结果和批次 item `details.missingUpdates`。
- No database changes: details 由受控 error code/message 生成，不写新列。

- [ ] **Step 1: 写 DK20925C 失败测试**

使用脱敏文件名 fixture 和 FakeImportProcessor：

```python
files = ["DK20925C.000", "DK20925C.002", "DK20925C.003", "DK20925C.004"]
```

断言：

- item.status=failed。
- errorCode=`S57_UPDATE_GAP`。
- 批次详情 API 返回 `details.missingUpdates == [1]`。
- 没有创建该 Dataset、DatasetVersion、ImportJob。
- FakeImportProcessor 没有调用，因此不会发布任何 GeoServer 资源。

- [ ] **Step 2: 写 NO2A0404 失败测试**

输入：

```python
files = ["NO2A0404.007", "NO2A0404.009"]
```

断言：

- errorCode=`S57_BASE_MISSING`（兼容旧历史源缺失场景仍可使用 `S57_HISTORICAL_SOURCE_MISSING`）。
- `details.missingUpdates == [0, 1, 2, 3, 4, 5, 6, 8]`。
- errorMessage 明确包含基础文件缺失和更新链不连续。
- `.007`/`.009` 不创建独立数据集、版本、ImportJob 或发布调用。

- [ ] **Step 3: 写合法链回归测试**

覆盖：

- 新链 `.000,.001,.002` 继续通过。
- 已有数据集追加连续 `.002,.003` 继续通过。
- 已有当前 update=1，上传 `.003` 返回 `S57_UPDATE_GAP` 和 `[2]`。
- 非 gap 错误的 details 不含 missingUpdates 或返回空数组。

- [ ] **Step 4: 运行更新链测试确认 RED**

```bash
cd F:/polar-gis/backend
F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_s57_batch.py -v
```

Expected: 当前 NO2A0404 只报告缺 `.000`，且 response 没有 details。

- [ ] **Step 5: 实现一次性完整缺口分析**

新增结构化错误：

```python
class S57ChainValidationError(ValueError):
    def __init__(self, code: str, message: str, missing_updates: list[int]) -> None:
        super().__init__(message)
        self.code = code
        self.missing_updates = tuple(missing_updates)
```

新链先计算 `0..max(chain)` 的完整 missing 列表，再决定：

- 缺 0：`S57_BASE_MISSING`，message 同时列出全部缺口。
- 不缺 0 但有缺口：`S57_UPDATE_GAP`。
- 无缺口：返回连续更新号。

已有数据集追加只计算 `current_update + 1 .. highest_uploaded`，不改变历史源恢复语义。

由于数据库没有 details 列：

- `S57ImportBatchItemRead` 增加 `details: dict[str, Any] = Field(default_factory=dict)`。
- `_fail_item` 继续保存稳定 errorCode 和可读 errorMessage。
- 在 `s57_batch.py` 提供 `s57_error_details(error_code, error_message)`，只对已知链错误用正则提取 message 中的 `.NNN`，生成 `{"missingUpdates": [...]}`。
- `get_s57_import_batch()` 构造 response 时显式填充 details。
- formatter 和 parser 放在同一模块并由测试锁定，避免文案漂移。

- [ ] **Step 6: 运行定向测试和 lint**

```bash
cd F:/polar-gis/backend
F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_s57_batch.py tests/test_s57.py -v
F:/polar-gis/.venv/Scripts/python.exe -m ruff check app/services/s57_batch.py app/api/datasets.py app/schemas.py tests/test_s57_batch.py
```

Expected: 全部通过；连续合法链行为不变。

- [ ] **Step 7: 更新 API/living/user docs、提交并推送**

```bash
git add backend/app/services/s57_batch.py backend/app/schemas.py backend/app/api/datasets.py backend/tests/test_s57_batch.py docs/04-api-design.md docs/09-system-architecture.md docs/10-work-log.md docs/11-work-summary.md docs/12-user-manual.md
git commit -m "fix: 完善S-57更新链缺失诊断" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push origin master
```

---

### Task 7: 完成设计文档、全量验证和交付检查

**Files:**
- Modify: `docs/02-system-design.md`
- Modify: `docs/04-api-design.md`
- Modify: `docs/05-ui-ux-design.md`
- Modify: `docs/09-system-architecture.md`
- Modify: `docs/10-work-log.md`
- Modify: `docs/11-work-summary.md`
- Modify: `docs/12-user-manual.md`

**Interfaces:**
- Produces: 最终文档和可复现验证证据。
- Consumes: Task 1–6 完整实现。

- [ ] **Step 1: 完成所有要求文档**

文档必须明确：

- “批量加载”是创建/显示 WMS 图层，不是重新导入 S-57 文件。
- `core_chart`、`navigation_recommended`（核心 + 航行推荐）、`all_spatial` 的差异。
- metadata_quality 默认排除，includeMetadata=true 时可附加到任一 profile；non_spatial 永远不创建 WMS。
- 未映射样式不进入核心/推荐自动加载，但可进入 all_spatial。
- 41 层起确认、120 层硬上限、每批 5 层、批间 200ms。
- 取消只停止尚未创建的图层；已创建图层可用“卸载本次加载”清理。
- 三种卸载范围及其不影响底图/AIS/气象/测量的边界。
- DK20925C 和 NO2A0404 的 missingUpdates/errorCode 行为。
- 系统不是经认证 ECDIS，当前未配置完整 S-52 表达规则。
- 不需要数据库迁移；旧 metadata 通过读取期动态分类兼容。

- [ ] **Step 2: 运行后端全量验证**

```bash
cd F:/polar-gis/backend
F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/ -v
F:/polar-gis/.venv/Scripts/python.exe -m ruff check app tests
```

Expected: 全部 pytest 通过，ruff 无错误。若已有基线失败，记录原始输出，不得宣称通过。

- [ ] **Step 3: 运行前端全量验证**

```bash
cd F:/polar-gis/frontend
npm test
npm run typecheck
npm run build
```

Expected: Vitest、vue-tsc、Vite build 全部通过。仓库没有 Playwright 基础，因此按用户条件不新增 Playwright；在最终报告中列为“不适用，而非遗漏”。

- [ ] **Step 4: 运行部署配置检查**

```bash
docker compose -f F:/polar-gis/deploy/compose.yml config
```

若 Docker 可用，再执行：

```bash
docker compose -f F:/polar-gis/deploy/compose.yml build backend worker web
```

Expected: compose 配置有效；构建成功或如实记录环境阻塞。

- [ ] **Step 5: 运行真实应用端到端验收**

启动现有 5 服务后，以普通用户完成：

1. 打开地图工作台，确认首屏仍只请求 map-config 和默认数据集所需目录。
2. 不展开数据集，搜索并选择 3 个 S-57 数据集。
3. 加载推荐海图层，观察一次 resolve POST、进度、成功/失败/跳过数。
4. 确认 WMS 对象按 5 层一批创建，批次间约 200ms，未等待所有瓦片完成。
5. 制造一个无效 WMS layer，确认其他层继续。
6. 取消中途加载，确认剩余层不再创建；使用“卸载本次加载”。
7. 卸载所选数据集，确认底图、AIS、气象、测量仍正常。
8. 切换 EPSG:3857 ↔ EPSG:3413，只重建已加载层，选择状态保持。
9. 在图层范围外观察无无意义瓦片请求；minZoom/maxZoom 生效。
10. 上传脱敏 DK20925C/NO2A0404 文件名 fixture，确认错误和 missingUpdates；不使用真实 ENC 内容。

- [ ] **Step 6: 检查 diff、临时文件、真实 ENC 和凭据**

```bash
git diff --check
git status --short
git diff -- backend/app/models.py backend/migrations
```

Expected:

- 无空白错误、调试日志、临时文件、真实 `.000/.001/...` ENC、ZIP、凭据或 `.env`。
- `backend/app/models.py` 和 `backend/migrations` 无变化。
- 所有新响应示例为 camelCase。
- 分类清单只存在后端一份；前端没有复制业务规则。

- [ ] **Step 7: 请求代码审查并修复确认的问题**

对当前 diff 执行项目代码审查，重点验证：权限边界、旧 API 语义、状态统计、WMS 清理、投影竞态、Set/Map 响应式、更新链不创建候选版本。修复后重新运行受影响测试和全量验证。

- [ ] **Step 8: 最终文档提交并推送**

```bash
git add docs/02-system-design.md docs/04-api-design.md docs/05-ui-ux-design.md docs/09-system-architecture.md docs/10-work-log.md docs/11-work-summary.md docs/12-user-manual.md
git commit -m "docs: 完善S-57批量图层功能文档" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push origin master
```

若代码审查修复同时改动产品代码，必须把相应 09/10/11 更新与代码一起提交并推送，不得只提交文档。

---

## 最终手工验收矩阵

| 场景 | 预期 |
|---|---|
| 不展开数据集直接选择 | 可选择，不请求内部 GET |
| 全选当前搜索结果 | 只选择过滤后的 S-57 数据集 |
| 清空选择 | 不卸载任何已加载图层 |
| 核心模式 | 仅 mapped 核心层可加载 |
| 推荐模式 | mapped 核心 + mapped 航行推荐层 |
| 全部模式 | 全部 renderable 空间层，含 unmapped optional_other |
| includeMetadata=false | metadata_quality 跳过并计数 |
| DSID/C_AGGR | 始终 loadable=false，不调用 attach |
| 单层失败 | 记录失败，后续继续 |
| 41 个候选 | 二次确认 |
| 121 个候选 | 阻止执行 |
| 取消 | 停止后续创建，已创建层保留 |
| 卸载本次加载 | 只卸载本次新建层 |
| 卸载所选数据集 | 只卸载所选数据集的业务 WMS |
| 卸载全部海图层 | 底图/AIS/气象/测量不受影响 |
| 投影切换 | 只重建 loadedLayerIds，不改变选择 |
| DK20925C 缺 .001 | S57_UPDATE_GAP + [1]，无候选版本/发布 |
| NO2A0404 .007/.009 | S57_BASE_MISSING + [0..6,8]，无独立数据集/发布 |
| 合法连续链 | 行为与当前版本一致 |

## 数据库迁移结论

不需要数据库迁移。新增分类信息进入已有 `layers.metadata_json`；旧数据不回填，resolve API 动态分类。新增 API 字段、批次 details 和前端状态均不要求表结构变化。

## 回滚方式

1. 暂停正在进行的前端批量加载和 S-57 导入批次。
2. 按 Task 7 → Task 1 的逆序 `git revert` 对应提交，并逐次 `git push origin master`。
3. 同时重新部署 backend、worker 和 web，避免前后端契约版本不一致。
4. 重跑原后端全量测试、前端全量测试和现有单图层懒加载手工流程。
5. 已写入的 `metadata.s57` 是向后兼容的额外 JSON；旧代码会忽略，无需清库或执行 downgrade。
6. 新 API 不创建额外 GeoServer 资源；批量加载只创建浏览器内 OpenLayers 对象，因此无需 GeoServer 资源回滚。
7. 若验收创建了测试数据集/项目，使用现有管理 API 清理，不直接操作数据库。

## 最终交付报告模板

完成后必须逐项报告并引用实际代码位置：

1. 修改文件列表与新增文件列表。
2. 数据库迁移：明确“无需迁移”及旧数据回退方式。
3. 新增 API：路径、请求、响应、错误码、权限和排序。
4. 前端交互：选择、三种 profile、进度、取消、卸载和硬上限。
5. S-57 分类：唯一事实来源、已知集合、未知回退、styleMapped 规则。
6. 更新链：DK20925C、NO2A0404 和合法连续链结果。
7. 自动化测试：逐条命令、通过数量；失败/跳过必须如实说明。
8. 未完成项和限制：Playwright 不适用、非认证 ECDIS、S-52 不完整、真实环境验证状态。
9. 手工验收步骤和实际观察结果。
10. 回滚提交顺序和数据兼容性。
