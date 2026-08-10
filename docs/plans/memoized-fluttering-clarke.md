# 批量加载海图图层渲染性能优化计划

## Context

**用户问题**：批量加载 S-57 海图图层（可达 160 层）后，浏览器地图**平移后显示空白、缩放加载缓慢卡顿**。

**根因（经三路探索 + 代码验证确认）**：

| # | 瓶颈 | 证据 | 影响 |
|---|------|------|------|
| 1 | **GWC 瓦片缓存全链路未接通** | 前端 TileWMS 用普通 WMS URL（MapWorkspaceView.vue:538），后端已算好的 `tile_service_url=/geoserver/gwc/service/wms` 从未被消费；`TILED=true` 对普通 WMS 无效；**EPSG:3413 GridSet 从未创建**（`ensure_gridset()` geoserver.py:316-343 是死代码；importer.py:170-179 硬编码 3857/4326） | 每次平移新 BBOX → 瓦片 100% MISS → GeoServer 实时渲染（PostGIS 全表+SLD 渲染）→ 空白+卡顿。**主因** |
| 2 | **前端视口裁剪失效（放大器）** | `merge_s57_layer_metadata`（importer.py:44-78）从不写 `s57.extent` → 前端 `isLayerInViewport` 对 null extent 保守放行（mapRenderScheduler.ts:139）→ 160 层全部视为"在视口内"全部请求瓦片 | 瓦片请求数从"视口内量级"膨胀到 160 层全量 |
| 3 | **Bundle 生命周期缺陷（图层泄漏）** | scheduler bundle 分支 `if (false /* TODO */)`（mapRenderScheduler.ts:404）：detach/suspend/activate 恒空；取消选中后旧 bundle 永不移除且保持可见；bundle 无预算（attachBundles=视口内全部，:401-411） | 选择变更累积可见图层 → 瓦片请求持续增长 |
| 4 | **SLD 无比例尺规则** | s57_styles.py:12-43 单 Rule 无 MinScaleDenominator；`_SCALE_RULES`（s57_layer_catalog.py:202-238）只进前端调度器 | 低缩放高密度图层（SOUNDG/DEPCNT）全密度渲染 → GeoServer CPU 高 |
| 5 | **发布 bbox 硬编码全球** | geoserver.py:96-146 bounds 硬编码 -180..180 | 北极数据渲染扫描范围过大 |

**约束**：不改变现有功能与架构；不破坏现有测试（前端 70 个断言常量：active=20/warming=10/attached=60/unbounded=10/LRU 30s/debounce 150ms/硬上限 160/batch 5@200ms；后端 125 个）；`ENABLE_RENDER_BUNDLES` 默认启用保持；resolve/render-plan API 字段向后兼容；docs/09/10/11 每次修改后同步更新。

**用户已确认**：P0+P1 完整优化；不做瓦片预热（自然填充）。

---

## P0 — GWC 缓存全链路 + Bundle 修复 + extent 元数据

### 1. GWC 全链路（主修）

**前端 `frontend/src/views/MapWorkspaceView.vue`**：

1. `attachWmsLayer`（:537-543）：cacheable 图层改用 GWC 端点并强制 WMS 1.1.1（OL 自动改用 `SRS` 参数，规避 GWC WMS-C 对 1.3.0/CRS 的处理差异）：
   ```ts
   const useGwc = ENABLE_GWC_TILES && runtime.config.renderTransport === 'gwc_wms' && !!runtime.config.tileServiceUrl
   const source = new TileWMS({
     url: browserGeoServerUrl(useGwc ? runtime.config.tileServiceUrl! : runtime.config.serviceUrl),
     params: { LAYERS: ..., TILED: true, STYLES: ..., ...(useGwc ? { VERSION: '1.1.1' } : {}) },
     ...
   })
   ```
2. 新增 Feature Flag `ENABLE_GWC_TILES = import.meta.env?.VITE_ENABLE_GWC_TILES !== 'false'`（默认启用；回退=构建时设 false，与 `ENABLE_RENDER_BUNDLES` 同风格，可放 mapRenderScheduler.ts 或 mapLayerBatch.ts）。
3. `loadSelectedDatasets`（:1112-1133）构建 `MapLayerConfig` 时透传 `renderTransport`/`tileServiceUrl`/`cacheable`；`frontend/src/types/index.ts:29-50` `MapLayerConfig` 补这 3 个可选字段（`ResolvedMapLayer` :308-312 已有）。
4. `toggleDataset` 懒加载路径（:642-653 走 `/map-datasets/{id}/layers`）对应后端端点（projects.py:183-229）同步补 `tile_service_url/render_transport/cacheable` 字段（复用 `_build_resolved_layer` 或等效逻辑）。

**后端**：

5. `backend/app/services/importer.py:170-179`：`ensure_gwc_layer` 的 gridsets 加 `"EPSG:3413"`；循环前调用一次幂等 `ensure_gridset("EPSG:3413", "EPSG:3413", [-4194304.0, -4194304.0, 4194304.0, 4194304.0])`（`_default_gridset_levels` 已生成与 OL 默认瓦片网格逐瓦对齐的 22 级，无需改）。失败仅告警不中断导入。
6. **已导入图层补配置（lifespan backfill）**：`backend/app/main.py` lifespan（:41-46）`ensure_initial_admin()` 后 spawn daemon 线程执行 `ensure_gwc_3413_backfill()`（不阻塞启动、失败仅告警、环境变量 `GWC_3413_BACKFILL=0` 禁用）：
   - `ensure_gridset("EPSG:3413", …)` 幂等 PUT
   - 查 DB 所有 `AVAILABLE` 且 `geoserver_layer_name` 非空的 S-57 图层 → `GET /rest/gwc/layers/{qualified}.json` 检查 gridSubsets 缺 3413 才 PUT（GET-then-PUT，避免每次启动 160 次 PUT）
   - worker 进程不跑 FastAPI lifespan（独立脚本），无双进程竞态；即使并发也幂等
7. 新增 `POST /api/v1/admin/gwc/backfill` 管理端点（幂等，手工重跑同一函数）。
8. **bundle 保持普通 WMS**（不改 mapRenderBundles.ts）：GWC WMS-C 不支持逗号分隔多 LAYERS 缓存，bundle 继续走 `/geoserver/polar_gis/wms` + nginx proxy_cache（1h）兜底。

### 2. Bundle 生命周期修复（治图层泄漏）

**`frontend/src/utils/mapRenderScheduler.ts`**（bundle 分支 :383-543）：

9. `RenderPlanInput` 增加可选 `attachedBundleIds?: ReadonlySet<string>`（缺省空集，不破坏现有 32 测试）。
10. 替换 `if (false /* TODO */)`（:404）为真实四操作：
    - 视口外且已挂载 → `suspendBundles.push`
    - 视口内且已挂载 → `activateBundles.push`（修复平移回来不重新显示）
    - 视口内且未挂载 → `attachBundles.push`
    - 已挂载但不在新计划（取消选中/版本变化 → bundleId 变化）→ `detachBundles.push`（修复泄漏）
11. 无需 bundle 预算上限：bucket 仅 5 类，160 层 ≤9 个 bundle 天然有界，不触碰 `SMART_MAX_*` 常量。

**`frontend/src/views/MapWorkspaceView.vue`**：

12. `reconcileRenderPlan`（:842-869）调 `buildRenderPlan` 时传 `attachedBundleIds`（来自 `getAllBundleRuntimes()`）；空选择/计划获取失败时若存在 bundle runtime 先 `disposeAllBundles(map!)` 再走 per-layer 路径（:844, :863-866）。
13. `unloadSelectedDatasets`（:1310-1322）、`unloadCurrentFilteredLayers`（:1339-1350）、`unloadLastBulkBatch`（:1352+）末尾补 `reconcileRenderPlan()`（selection 变化使 bundleCacheKey 失效 → 自动 detach 失效 bundle）。
14. `renderMode` 切到 `'standard'` 时（:1654）`disposeAllBundles(map!)`（reconcile 在 standard 直接 return，否则 bundle 残留）。
15. `replaceBundle`（mapRenderBundles.ts:187-254）本期不接入（detach→attach 语义已正确，保留为后续优化项）。

### 3. extent 元数据持久化（激活视口裁剪）

16. `backend/app/services/importer.py` `merge_s57_layer_metadata`（:44-78）：从 ogrinfo `source_layer["geometryFields"][0]["extent"]`（S-57 原生 4326）写入 `s57["extent"]`（4 浮点列表，缺省 None）。后端 projects.py:280-289 / map_render_plan.py:569-576 已读该字段，前端 `isLayerInViewport` 立即生效。已有图层缺失时仍保守放行（安全）。

### 4. P0 测试

- **后端 pytest**：`test_importer.py` 增：`merge_s57_layer_metadata` extent 存在/缺失 2 用例；importer 调用 `ensure_gridset` 一次 + `ensure_gwc_layer` 带 3 个 gridset（stub GeoServerClient）。backfill 逻辑测试（stub：缺 3413 补 PUT、已有 3413 跳过）。
- **前端 vitest**：`mapRenderScheduler.test.ts` 新增 bundle 分支 describe（此前零覆盖）：①视口内新 bundle → attach；②已挂载+视口内 → 仅 activate 不重复 attach；③已挂载+视口外 → suspend；④已挂载不在新计划 → detach；⑤缺省 `attachedBundleIds` → 行为与现状一致。常量断言不变。

---

## P1 — SLD 比例尺 + bbox 修正（治本增强）

### 5. SLD 比例尺规则

17. `backend/app/services/s57_styles.py:12-43`：`render_sld(min_scale_denominator: float | None = None, max_scale_denominator: float | None = None)`（默认 None，`test_s57.py:39` 无参调用不破坏）；有值时 Rule 内插 `<sld:MinScaleDenominator>` / `<sld:MaxScaleDenominator>`。
18. `backend/app/services/importer.py` `_apply_s57_style`（:428-460）：调 `classify_s57_layer(...)` 取 `min_scale_denominator` 传入 `render_sld`（复用现有分类输出）。
19. **已有图层样式刷新（幂等）**：`publish_style`（geoserver.py:165-186）已幂等 PUT。SLD 变化后同 style 名 GWC 缓存键不变 → 必须 truncate：`_apply_s57_style` 对内容实际变化的 style（SLD 新旧 sha256 对比，存 `s57.sldHash`）PUT 后对该 style 关联图层调 `truncate_layer_cache`（geoserver.py:345-353 死代码复活，masstruncate 幂等 404 容忍）；部署期提供一次性刷新路径（复用 `POST /admin/gwc/backfill` 同款脚本模式或独立管理端点）。nginx 1h 过期自然覆盖 proxy_cache 旧瓦片。
- 效果：SOUNDG（min 25k）/DEPCNT（500k）/助航（50k）/危险物（100k）在小比例尺不再渲染，每瓦片渲染负担大降（standard 模式全开 160 层时尤其有效）。

### 6. 发布 bbox 修正（仅新发布生效）

20. `backend/app/services/geoserver.py`：`publish_feature_type`（:80-116）/`publish_feature_types_batch`（:118-153）增加可选 `bounds: list[float] | None = None`；非 None 时用其填 `nativeBoundingBox`/`latLonBoundingBox`（校验：4 个有限浮点、min<max，非法回退全球）。
21. `backend/app/services/importer.py` 调用处（:157-164）：从 ogrinfo `geometryFields[0].extent`（4326）取 bbox 传入——发布时零 DB 扫描。
22. 已有图层不动（安全默认）。

### 7. P1 测试

- `test_s57.py` 增：`render_sld(25000.0)` 输出含 `MinScaleDenominator`；无参输出不含（向后兼容）。
- `test_importer.py` 增：`_apply_s57_style` 带 scale 调用；`publish_feature_types_batch` 传 bounds 时 payload 断言（stub 捕获）。
- 端到端：小比例尺下 SOUNDG GetMap 响应不含点要素。

---

## 实施顺序

1. **阶段 A（P0，一次提交）**：后端（gridsets+3413、backfill+管理端点、extent 元数据）→ 前端（GWC 切换+flag+字段透传、bundle 生命周期+边界清理）→ 新增测试 → 文档 09/10/11。
2. **阶段 B（P1，第二个提交）**：SLD 比例尺+sldHash/truncate → bbox 可选参数 → 测试 → 文档。
3. 次要项（P2，可选，不纳入本次主计划）：`layerStatusLabel` 退化视口检查删除、pointermove rAF 节流、fetchRenderPlan AbortController、geoserver httpx 连接池。

## 关键文件

- `frontend/src/views/MapWorkspaceView.vue`（attachWmsLayer :537、loadSelectedDatasets :1112、reconcileRenderPlan :797、executeBundlePlan :963、unload 系列 :1310+）
- `frontend/src/utils/mapRenderScheduler.ts`（bundle 分支 :383-543、RenderPlanInput）
- `frontend/src/utils/mapLayerBatch.ts`（新 flag 常量）
- `frontend/src/types/index.ts`（MapLayerConfig 可选字段）
- `backend/app/services/importer.py`（gridsets :170、merge_s57_layer_metadata :44、_apply_s57_style :428、publish bounds :157）
- `backend/app/services/geoserver.py`（ensure_gridset :316 复用、bounds 参数、truncate_layer_cache :345 复活）
- `backend/app/services/s57_styles.py`（render_sld 比例尺参数）
- `backend/app/main.py`（lifespan backfill）
- `backend/app/api/projects.py`（map-datasets 端点字段 :183-229）
- `backend/app/api/system.py` 或 projects.py（admin/gwc/backfill 端点）

## 验证

- **后端**：`cd F:/polar-gis/backend && .venv/Scripts/python -m pytest tests/ -v`（125 旧+新增全绿）、`ruff check app tests`
- **前端**：`cd F:/polar-gis/frontend && npm test`（70 旧+新增）、`npx vue-tsc --noEmit`、`npm run build`
- **端到端（docker compose 环境）**：
  1. `curl 'http://localhost:8080/geoserver/gwc/rest/gridsets/EPSG:3413.json'` → 200 且含 22 级/正确 extent
  2. 取前端网络面板某 3413 瓦片 URL，`curl -s -D-` 两次 → 第二次响应头含 `X-GWC-Cache: HIT`（首 MISS）；或 `docker exec` geoserver 容器查 GWC 缓存目录出现瓦片文件
  3. 浏览器加载 160 层 → 平移 → 图层不空白、二次平移流畅；取消勾选若干层 → 网络面板确认被取消 bundle 瓦片不再请求（泄漏修复）；切 standard 模式 → 无 bundle 残留
  4. 回退演练：`VITE_ENABLE_GWC_TILES=false` 重建前端，行为与现状一致
- **文档**：docs/09（瓦片请求三级链路数据流、GWC 3413 管理）、docs/10（会话条目：任务计划/根因/修改清单/决策）、docs/11（修改内容/效果/验证记录）同步更新并 git commit + push
