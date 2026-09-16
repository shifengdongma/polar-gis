# 14. S57 海图版本更新机制调研 & 航路绘制改造方案

> 调研日期：2026-08-29
> 调研方式：基于系统当前实际代码（backend / frontend）与 docs/09-system-architecture.md、docs/12-user-manual.md
> 调研结论均经过源码复核：`backend/app/services/s57.py`、`importer.py:277-316`、`backend/app/api/datasets.py:820-883`、`backend/app/services/s57_batch.py:94-116`、`frontend/src/views/MapWorkspaceView.vue:299-317/1014-1050`、`backend/app/models.py`

---

# 第一部分：S57 海图版本更新方式调研

## 一、结论先行

**当前系统是"补丁式（增量链）"模型，必须从 000 基础文件开始导入加载**：

- `.000` 被当作基础单元（base cell），`.001`–`.999` 被当作必须严格按序叠加在基础单元之上的增量更新；
- 缺少 `.000`、更新号跳号、单元名不匹配都会被拒绝（422），**`.001` 等更新文件绝不可能被当作独立完整海图导入**；
- 但实现方式不是"就地修改现有表"，而是**每次更新沿父版本链把 `.000` 起的所有文件复制到同一临时目录 → GDAL 读取 `.000` 时自动叠加全部更新 → 全量重建新表 + 新 GeoServer 图层 → 原子切换 `current_version_id`**（旧版本 RETIRED 保留供回滚）。

即：**标准 S57 补丁语义 + "链式重放、全量重建、版本并存"的实现**。操作上必须从 000 开始按序导入（补丁式）；数据上最新版本的图层确实是"完整海图"（全量重建），但不是靠单个更新文件自包含，而是靠链回放。

## 二、决定性代码证据（已逐一复核）

**证据 1 — 文件名解析与严格 +1 校验**（`backend/app/services/s57.py:12-44`）：

```python
s57_name_pattern = re.compile(r"^(?P<cell>[A-Za-z0-9_-]+)\.(?P<update>\d{3})$")
# identify_s57_file → 解析出 cell_name（如 CN000001）与 update_number（0-999）

def validate_s57_update(candidate, expected_cell_name, current_update_number):
    if candidate.cell_name != expected_cell_name.upper():
        raise AppError("S57_CELL_MISMATCH", "更新文件与当前海图单元不匹配", 422)
    expected_update = current_update_number + 1
    if candidate.update_number != expected_update:
        raise AppError("S57_UPDATE_GAP", f"期望更新号为{expected_update:03d}，实际为{candidate.update_number:03d}", 422)
```

单文件更新接口 `backend/app/api/datasets.py:820-883`（`create_s57_update`）要求数据集必须是有效 S-57 数据集且 `current_version_id` 存在（否则 `S57_DATASET_REQUIRED`），更新号必须 = 当前号 +1，新版本通过 `parent_version_id=current.id` 挂到父版本（:847）。**不存在把 .001 当独立数据集导入的路径。**

**证据 2 — 导入时沿父链回放、缺 .000 即失败**（`backend/app/services/importer.py:277-316` `_stage_s57_chain`）：

```python
while current is not None:        # 沿 parent_version_id 回溯到 .000
    ... versions.append(current)
    if current.parent_version_id is None: break
    current = db.get(DatasetVersion, current.parent_version_id)
...
for item in versions:             # 把链上每个版本源文件复制到同一临时目录
    destination = directory / asset.original_name   # CN000001.000 / .001 / .002 同目录
    shutil.copy2(source, destination)
    if destination.suffix == ".000":
        base_path = destination
if base_path is None:
    raise AppError("S57_BASE_CELL_MISSING", "S-57更新链缺少.000基础单元", 422)
```

随后 `ogr2ogr` **只指向 `.000` 文件**（importer.py:378-395，全仓唯一一处 ogr2ogr 调用）——把全链文件放入同一目录正是依赖 **GDAL S-57 驱动在读取基础单元时自动叠加同目录下 `.001`+ 更新**的标准行为。

**证据 3 — 批量导入链校验**（`backend/app/services/s57_batch.py:94-116` `validate_s57_chain`）：`0` 必须在链中（否则 `S57_BASE_MISSING`），且 `0..max` 必须连续无缺口（否则 `S57_UPDATE_GAP`）。

**证据 4 — 版本切换与旧版本处置**（importer.py:192-199）：导入成功后 `parent_version.status = RETIRED`、`dataset.current_version_id = version.id`（原子切换指针），`_switch_project_layer_versions`（:494-515）把项目图层引用改指向新版本图层。旧表/旧 GeoServer 图层不删除，仅软退役，支持回滚（`datasets.py:886-934` `rollback_dataset`）。

## 三、补充发现（与标准 S57 更新模型的差异）

1. **完全不解析 edition（版次）**：版本识别只靠文件扩展名，不读 DSID 的 EDITION/UPDN 字段。这意味着**无法处理"新一版海图"（new edition，同一单元编号再次回到 `.000`）**：
   - 单文件接口：新 `.000` 的 updateNumber=0 ≠ current+1 → 被 `S57_UPDATE_GAP` 拒绝；
   - 批量接口：`0 ≤ current_update` → 被标记 `up_to_date` 跳过（s57_batch.py:547-556）；
   - 即新版海图数据永远无法进入已有数据集，只能另建新数据集（但会遇到 `DATASET_CODE_EXISTS` 冲突）。
2. **更新文件本身不单独入库**：数据库只存每个版本"经 GDAL 叠加链后的完整结果表"，不存增量数据。
3. **全量重建而非就地打补丁**：每个版本创建全新 PostGIS 表（`ds_{short_id}_v{version_no}_{source_name}`）与全新 GeoServer 图层（名含版本号，如 `s57_cn000001_3_depare`），存储/发布资源随版本递增。
4. 单文件接口一次只能补一个（严格 current+1），批量接口才支持一次补齐多个连续更新。
5. 测试佐证：`backend/tests/test_s57.py:21-25`（跳号拒绝）、`test_s57_batch.py:388-426`（已有 .000/.001 的数据集，新批次 .000–.003 只追加 .002、.003）。

---

# 第二部分：航路绘制现状分析与改造方案

## 一、现状：前端地图组件

地图逻辑高度集中在单文件 `frontend/src/views/MapWorkspaceView.vue`（约 2362 行，无独立子组件；唯一共享组件 `WeatherChart.vue` 与地图无关）。

**OpenLayers 地图组织**（`buildMap()` :479-515）：兜底 OSM 底图 + 后端配置底图（XYZ/WMTS）+ S-57 业务图层（`TileWMS`/GWC，WMS 1.1.1）+ 两个现成矢量层：

```ts
// MapWorkspaceView.vue:299-317
const measureSource = new VectorSource()
const measureLayer = new VectorLayer({ source: measureSource, zIndex: 100, ... })  // 测量层
const aisLayer = new VectorLayer({ source: aisSource, visible: false, zIndex: 110, ... })  // AIS 层
```

**双投影**：EPSG:3857 ↔ EPSG:3413（proj4 注册于 :273-275）。`switchProjection(crs)`（:1014-1050）在 `map.setView()` 后调用 `reloadAisGeometry()`（:1037）重建矢量要素几何——**这是航路层必须复用的先例**。

**最接近的"后端经纬度→前端矢量绘制"范式是 AIS**（:2051-2082）：`api.get('/demo/ais/vessels')` → `new Feature({ geometry: new Point(fromLonLat([vessel.longitude, vessel.latitude], currentCrs.value)) })` → `aisSource.addFeature(feature)`。**航路绘制只需把 Point 换成 LineString、把单点换成坐标数组，范式完全一致。**

另外测量功能已有 `Draw` interaction + LineString/Polygon 绘制与测长（:1883-1903），但仅用于测量，非航路展示。

## 二、现状：前端数据流范式与后端盘点

- **API 模式**：`frontend/src/api/client.ts`（axios 单例、401 单飞刷新重放、仅 GET params 自动 snake_case）+ `api/projects.ts`（函数式封装，`signal?` 参数）+ `stores/projects.ts`（Pinia setup store）+ 视图内也允许直调 api。
- **命名约定**：后端 `ApiModel`（schemas.py:11-12）出参自动 camelCase、入参 `populate_by_name=True` 同时接受 camelCase/snake_case → **前端 POST body 直接写 camelCase 即可**。
- **后端 16 张表全部无 geometry 列**（已 grep 复核，唯一的 `geometry_type` 是 Layer 表上的字符串）。空间数据实际在 PostgreSQL `geo` schema（ogr2ogr 导入建表，`GEOMETRY_NAME=geom`）；空间读取先例在 `backend/app/api/layers.py`（`ST_AsGeoJSON(ST_Transform(geom,4326))`，坐标顺序 **[lon, lat]**）。
- **没有任何 route/waypoint/track 表或端点**——航路功能需从零建设。
- **坐标工具现状**：`fromLonLat/toLonLat` 单点转换现成（4326→3857/3413）；`transformLayerExtent`（mapLayerBatch.ts:143）bbox 转换现成；**无整条 LineString 坐标数组的批量转换封装**（OpenLayers 的 `geometry.transform('EPSG:4326', crs)` 可用但项目尚未使用）。

## 三、航路功能改造清单（后端发送坐标点 → 前端绘制）

### 后端（模型 → 迁移 → schema → API → 路由 → seed）

| 文件 | 增/改 | 内容 |
|---|---|---|
| `backend/app/models.py` | 追加 | `Route` 表：UUID 主键、`code` 唯一索引、`name`、`description`、`project_id` FK(projects.id, CASCADE, 索引)、`created_by` FK(users.id)、`created_at/updated_at/deleted_at` 软删；`RoutePoint` 表：`route_id` FK(CASCADE, 索引)、`seq` 整数、`lon Numeric(11,7)`、`lat Numeric(10,7)`、`(route_id, seq)` 唯一约束。**推荐纯经纬度数值存储而非 PostGIS geometry**（应用库无几何列先例、无 GeoAlchemy2 依赖、前端只需 [lon,lat] 序列、点数小；将来需空间分析再引入） |
| `backend/migrations/versions/0005_routes.py` | 新增 | `alembic revision --autogenerate -m "add routes and route points"` + `alembic upgrade head`（注意 `auto_create_schema=False`，必须走迁移） |
| `backend/app/schemas.py` | 追加 | `RoutePointOut`（lon/lat）、`RouteCreate`（points 列表，校验 ≥2 点、lon∈[-180,180]、lat∈[-90,90]）、`RouteRead`（points 按 seq 升序 + pointCount）；继承 `ApiModel` |
| `backend/app/api/routes.py` | 新增 | `GET /projects/{project_id}/routes`（分页列表，`Paginated[RouteRead]`）、`GET /routes/{route_id}`（完整点位 `[[lon,lat],...]`）、`POST /projects/{project_id}/routes`（创建，`get_current_user` 鉴权）、`DELETE /routes/{route_id}`（软删）；沿用 `AppError`/`Paginated` 惯例（参照 `projects.py`） |
| `backend/app/main.py` | 修改 | 注册 routes 路由（:109 附近） |
| `backend/app/cli.py` 或 seed 脚本 | 新增 | 给演示项目插入 2 条北极示例航路（如摩尔曼斯克→北极点、白令海峡→楚科奇海） |
| `backend/tests/test_routes.py` | 新增 | 创建/读取/删除/越界校验 |

### 前端（types → api → store → 绘制）

| 文件 | 增/改 | 内容 |
|---|---|---|
| `frontend/src/types/index.ts` | 追加 | `RoutePoint { lon; lat }`、`Route`（含 `points: RoutePoint[]`）、`RouteCreateRequest` |
| `frontend/src/api/routes.ts` | 新增 | `fetchProjectRoutes`/`fetchRouteDetail`/`createRoute`/<br />`deleteRoute`，照抄 `api/projects.ts` 函数签名风格 |
| `frontend/src/stores/routes.ts` | 新增 | setup 风格：routes 列表、activeRouteId、可见集合、`loadRoutes(projectId)`、`toggleRoute(id)` |
| `frontend/src/utils/mapRoute.ts` | 新增 | 纯函数 `buildRouteLineString(points, crs)`：`fromLonLat([lon,lat], crs)` 逐点转换 + `new LineString(coords)`；配单测 |
| `frontend/src/views/MapWorkspaceView.vue` | 修改（核心） | ① :317 后新增 `routeSource`/`routeLayer`（VectorLayer，zIndex 建议 90–105，Stroke 醒目色如 `#ff6b35` 宽 3）；② `buildMap()` 中 `map.addLayer(routeLayer)`；③ `drawRoutes(routes)`：清空 source → `Feature(new LineString(...))` + `set('routeId', ...)`；④ `switchProjection()` 中 :1037 旁新增 `reloadRouteGeometry()`（按 currentCrs 重建，或 `geometry.transform('EPSG:4326', crs)`）；⑤ 图层面板"环境叠加"下拉（:2281-2292，现只含 AIS）加"航路"入口；⑥ onMounted 加载后自动拉取绘制 |

## 四、关键风险与注意点

1. **坐标顺序**：全项目约定 **[lon, lat] 经度在前**（后端 `coordinate[0]=lon`、前端 `fromLonLat` 输入 [lon,lat]）。写反会出现 90° 级偏移，在 EPSG:3413 极地投影下尤其隐蔽。
2. **投影切换必须重建矢量几何**（最大坑）：`switchProjection` 不会自动转换 VectorLayer 要素坐标，必须仿照 `reloadAisGeometry()`（:1037）实现航路重建——现有测量层在投影切换后就存在此缺陷，航路层不能重蹈覆辙。
3. **数据格式**：建议后端直接返回 `points: [[lon,lat],...]` 数组，**不要引入 `ol/format/GeoJSON`**（项目当前未使用）；坐标一律存 4326 经纬度，不存投影后平面坐标。
4. **POST body**：axios 拦截器只转 GET params 不转 body；靠后端 `populate_by_name` 接受 camelCase，新接口 body 用 camelCase 即可；响应用 `response_model` 自动 camelCase。
5. **组件规模**：MapWorkspaceView.vue 已 2362 行，绘制逻辑建议放独立 store + 纯函数 util，地图里只挂层与切换处理。
6. **命名区分**：S-57 物标本就有"推荐航路（RECTRC）/双向航路段（TWRTPT）"物标（`s57ObjectNames.ts`），与本功能的"平台自有航路"是两码事，UI 文案需区分。
7. **性能**：航路点数小（几十~几百），VectorLayer 直接渲染无压力；未来若带 >1 万轨迹点需抽稀（`geometry.simplify` 或隔点取样）。

## 五、可直接使用的编码提示词草稿

### 提示词 1：后端（建表 + API + seed）

> 在 `F:\polar-gis\backend` 为 Polar-GIS 平台新增"航路（Route）"模块，供前端在地图上绘制航路。要求：
> 1. 在 `app/models.py` 追加两个 SQLAlchemy 模型：`Route`（UUID 主键、`code` 唯一索引、`name`、`description`、`project_id` 外键关联 `projects.id` 级联删除并建索引、`created_by` 外键关联 `users.id`、`created_at/updated_at/deleted_at` 软删，风格对齐现有模型）与 `RoutePoint`（`route_id` 外键级联删除并建索引、`seq` 整数排序、`lon Numeric(11,7)`、`lat Numeric(10,7)`，`route_id+seq` 唯一约束）。存储用纯经纬度数值，不用 PostGIS geometry 列。
> 2. 用 `alembic revision --autogenerate -m "add routes and route points"` 生成迁移并 `alembic upgrade head`。
> 3. 在 `app/schemas.py` 追加继承 `ApiModel` 的 `RoutePointOut`（lon/lat float）、`RouteCreate`（code/name/description/points，校验至少 2 个点、经纬度范围合法）、`RouteRead`（id/code/name/description/projectId/points 按 seq 升序/pointCount/createdAt/updatedAt）。
> 4. 新建 `app/api/routes.py`：`GET /projects/{project_id}/routes`（分页列表，`Paginated[RouteRead]`）、`GET /routes/{route_id}`（完整点位 `[[lon,lat],...]`）、`POST /projects/{project_id}/routes`（`get_current_user` 鉴权）、`DELETE /routes/{route_id}`（软删）。沿用 `AppError` 与现有代码惯例；在 `app/main.py` 注册路由。
> 5. 在 `app/cli.py` 增加 seed：给演示项目插入 2 条北极示例航路（摩尔曼斯克→北极点、白令海峡→楚科奇海，每条 10~30 个经纬度点，lon 在前）。
> 6. 补充 `backend/tests/test_routes.py`，运行 `pytest tests/ -v` 通过；更新 docs/09/10/11 三份文档。

### 提示词 2：前端（绘制组件 + api + store）

> 在 `F:\polar-gis\frontend` 为地图工作台新增"航路展示"能力，参照现有 AIS 矢量层实现范式（`src/views/MapWorkspaceView.vue` 的 aisSource/aisLayer/reloadAisGeometry，约 299-317、2051-2082 行）。要求：
> 1. 在 `src/types/index.ts` 追加 `RoutePoint`/`Route`/`RouteCreateRequest`（字段与后端 camelCase 响应一致，points 为 `[{lon,lat}]`）。
> 2. 新建 `src/api/routes.ts`：`fetchProjectRoutes(projectId, signal?)`、`fetchRouteDetail(routeId, signal?)`、`createRoute(projectId, payload, signal?)`、`deleteRoute(routeId)`，签名与 `src/api/projects.ts` 一致。
> 3. 新建 `src/stores/routes.ts`（Pinia setup 风格，参照 `src/stores/projects.ts`）：routes 列表、activeRouteId、可见集合、`loadRoutes(projectId)`、`toggleRoute(id)`。
> 4. 新建纯函数 `src/utils/mapRoute.ts`：`buildRouteLineString(points, crs)`，用 `fromLonLat([lon, lat], crs)` 逐点转换后 `new LineString(coords)`；配单测断言 3413 与 3857 输出坐标数量一致、顺序未被交换。
> 5. 修改 `MapWorkspaceView.vue`：(a) 新增 routeSource/routeLayer（zIndex 介于业务图层与测量层之间，Stroke `#ff6b35` 宽 3），`buildMap()` 中 addLayer；(b) 新增 `drawRoutes(routes)`：清空 source 后逐条 `Feature(new LineString(...))` 并 `set('routeId', ...)`；(c) `switchProjection()` 中 :1037 附近新增 `reloadRouteGeometry()` 按 currentCrs 重建；(d) 图层面板"环境叠加"下拉（约 :2281-2292）新增"航路"入口：列表 + 可见性开关 + 默认自动加载绘制；(e) onMounted 中 buildMap 后 `loadRoutes(projectId)` 并绘制。
> 6. 运行 `npm run typecheck` 与 `npm test` 通过。坐标严格 [lon, lat]；POST body 用 camelCase；不引入 ol/format/GeoJSON。

### 提示词 3：联调 / 坐标转换验证

> 对"后端航路点数据 → 前端地图绘制"做端到端联调验证（后端 `uvicorn app.main:app --reload --port 8000`，前端 `npm run dev`，虚拟环境用 `F:\polar-gis\.venv`）：
> 1. 用 seed 数据验证 `GET /api/v1/projects/{id}/routes` 返回 camelCase、`points` 为 `[{lon,lat}]` 升序。
> 2. 打开地图工作台确认航路线条位置正确：北极航线应贴近海图海岸线/航道，若偏到赤道或反经度说明 lon/lat 写反。
> 3. 连续切换"常规地图/北极投影"3 次以上，确认航路几何随投影正确重建、无错位残留、无控制台报错（重点检查 reloadRouteGeometry 是否在 switchProjection 中被调用）。
> 4. 用 3 组已知坐标交叉验证：北极点附近（85°N, 0°E）、跨 180° 经线（如 71°N,179°E → 70°N,179°W）、常规低纬点，分别在 3857 与 3413 下核对与海图相对位置。
> 5. 验证空列表项目、单点航路（后端应拒绝）、删除航路后图层即时消失；token 过期场景确认 401 自动刷新重放对航路接口生效。
> 6. 全部通过后更新 docs/09/10/11 三份文档，并按 CLAUDE.md 要求 git add/commit/push。

---

## 调研结论摘要

1. **S57 版本更新为"补丁式"**：必须从 `.000` 开始按序导入，更新文件不可独立使用；系统沿父版本链回放 + GDAL 叠加 + 全量重建实现，每个版本形成完整独立图层（可回滚）。
2. **航路功能需从零建设**：但 AIS 矢量层已提供完整的"后端经纬度 → 前端矢量绘制 + 投影切换重建"范式，改造量集中在 1 个后端新模块（表/迁移/API）与 1 个前端视图 + 3 个新前端文件（api/store/util），无需引入新依赖。
