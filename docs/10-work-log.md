# 10 — 工作日志 (Work Log)

> 记录每次开发会话的任务计划、修改内容与决策过程
> 最后更新: 2026-08-10

---

## 会话 #19 — README 更新 + 汇报幻灯片制作

**日期**: 2026-08-10
**目标**: 更新 README.md 反映当前真实系统状态，并制作汇报幻灯片内容

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-10 | `README.md` | 重写 | 全面更新：补充核心功能矩阵（5大类20+子项）、技术栈版本表、API 概览（16模块~60端点）、文档索引、CRS 表、验证命令（含测试数量） |
| 2026-08-10 | `README.md` | 补充 | 追加全球底图导入、S-57 basemap API、数据清理细节 |
| 2026-08-10 | `docs/13-presentation-slides.md` | 新建 | 9 页汇报幻灯片内容：进展/展示/部署/计划 + 17 张截图采集清单 |

### 关键决策

1. **README 以功能为核心**：按"核心功能 → 技术栈 → 快速开始 → API → 部署"组织，让新读者 5 分钟内了解系统全貌
2. **幻灯片以数据支撑**：引用真实测试数量（168/77）、端点数量（~60）、数据库表数（16）、服务数（5）等量化指标
3. **下一步计划聚焦性能**：P0（首屏加速/虚拟滚动/Bundle调度）→ P1（切换响应/内存GPU）→ P2（离线缓存/HTTP3），附技术路线图时间轴

---

## 会话 #18.2 — GWC 批量加载 400 修复（图层/样式名 workspace 前缀缺失）

**日期**: 2026-08-10
**目标**: 修复"批量加载图层"后前端报 `400 Bad Request`、图层加载失败

### 现象

浏览器对 `http://localhost:8088/geoserver/gwc/service/wms` 的瓦片请求返回 400，响应体：

```
400: Unknown layer s57_c110408a_1_depare. Check the logfiles, it may not have loaded properly.
```

用正确前缀 `polar_gis:s57_c110408a_1_depare` 重试后进一步暴露：

```
400: Style 's57_depth' is invalid.
```

### 根因分析

1. **会话 #18 优化将 cacheable 图层切换到 GWC WMS facade**（`/gwc/service/wms`，commit 311eb66），批量加载（standard 模式逐层 TileWMS）随之走 GWC 端点
2. **GWC 对图层/样式名做精确匹配**：其注册表键为全限定名（如 `polar_gis:s57_c110408a_1_depare`），裸名请求直接 400；而 GeoServer 自带 WMS 通过默认命名空间解析裸名，所以普通 WMS 路径一切正常——这是 GWC 专属故障
3. **DB 存裸名**：`geoserver_layer_name = code`、`geoserver_style_name = preset.code`，workspace 单独存 `geoserver_workspace`
4. **两个 API 端点返回裸名**：`get_project_dataset_map_layers`（懒加载 toggleDataset 路径，projects.py:226）与 `_build_resolved_layer`（批量 resolve 路径，projects.py:338/362-368）；而 bundle 渲染路径 `_build_layer_render_input`（projects.py:589-600）**早已正确拼接 `workspace:` 前缀**——故智能模式 bundle 正常、批量加载（逐层路径）失败
5. 前端 `MapWorkspaceView.vue:1189` 仅透传后端字段（`geoserverLayerName ?? code`），非缺陷源

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-10 | `backend/app/api/projects.py` | 修改 | `get_project_dataset_map_layers`: `service_layer_name` / `style_name` 拼接 `workspace:` 前缀（复用 workspace 变量构建 service_url） |
| 2026-08-10 | `backend/app/api/projects.py` | 修改 | `_build_resolved_layer`: 返回的 `geoserver_layer_name` / `style_name` 拼接 `workspace:` 前缀；本地裸名仅用于 published/loadable 真值判断 |
| 2026-08-10 | `backend/tests/test_projects.py` | 修改 | 两处 `serviceLayerName` 断言更新为全限定名（`polar_gis:demo_depth` / `polar_gis:chart_cell_01_*`），先红后绿 |

### 验证

- 修复后 GWC 请求（`LAYERS=polar_gis:s57_c110408a_1_depare&STYLES=polar_gis:s57_depth`）→ **HTTP 200 PNG 瓦片** ✅
- 普通 WMS 裸名请求 → 200（不受影响）✅
- 后端全量测试：**168 passed** ✅（先改测试见红，再改代码转绿）

### 关键决策

1. **后端拼接前缀（单点修复）**：两处端点 + bundle 路径统一输出 `workspace:name` 全限定名，前端零改动；GeoServer 自带 WMS 接受全限定名，兼容所有 transport
2. 全限定名与 `s57ObjectNames` 的 `split(':').pop()` 归一化逻辑兼容，图层标题显示不受影响
3. 已发布的图层名（GWC 注册表键）即 `polar_gis:xxx` 形式，无需迁移

### 注意

- 修复需重启后端服务（dev `uvicorn --reload` 自动生效；docker 部署需 `docker compose up -d --build backend`）
## 会话 #18.1 — 最终评审修复（SLD 比例尺方向 + Bundle attach 死锁）

**日期**: 2026-08-10
**目标**: 修复整体评审发现的 2 个 Critical + 1 个 Important 缺陷：SLD 比例尺方向反转、Bundle warming 死锁（bundle 永不可见）、被 suspend 的 warming bundle 无法恢复可见

### 根因分析

1. **SLD 方向反转（Critical）**：SLD 规范中 `MinScaleDenominator=25000` 表示"SD ≥ 25000 时规则生效"（缩远方向渲染），而意图是"放大到至少 1:25000 才显示 SOUNDG"（SD ≤ 25000 渲染）。上一批把 classification 的 `minScaleDenominator` 直接作为 `min_scale_denominator` 传入 `render_sld` → 方向相反：缩远全密度渲染（CPU 问题未解决）、放大后高密度层消失（功能性回归）
2. **Bundle warming 死锁（Critical）**：OpenLayers 不可见 TileLayer 不请求瓦片（ol/renderer/Composite.js 可见性门控）。`attachBundle` 创建时 `visible: false` → 无瓦片请求 → 无 tileloadend → status 永远 'warming' → activate 守卫要求 `status === 'active'` 才 setVisible(true) → 永不放行 → bundle 永不可见
3. **被 suspend 的 warming bundle 无法恢复（Important）**：即使 attach 即显示，被 suspend（setVisible false）时仍处于 warming 的 bundle 会再次冻结，activate 守卫必须放宽

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-10 | `backend/app/services/s57_style_refresh.py` | 修改 | `sync_s57_layer_style` 以 `max_scale_denominator=min_scale` 调用 `render_sld`（附方向说明注释）；docstring 更新 |
| 2026-08-10 | `backend/app/services/importer.py` | 修改 | `_apply_s57_style` docstring 中 MinScaleDenominator → MaxScaleDenominator |
| 2026-08-10 | `backend/tests/test_s57.py` | 修改 | `test_render_sld_with_min_scale_denominator` → `test_render_sld_with_max_scale_denominator`（锁定向：含 MaxScaleDenominator、不含 MinScaleDenominator） |
| 2026-08-10 | `backend/tests/test_importer.py` | 修改 | 两处生产路径断言 MinScaleDenominator → MaxScaleDenominator（25000.0 / 12345.0） |
| 2026-08-10 | `backend/tests/test_s57_style_refresh.py` | 修改 | 新增方向锁定测试 `test_sld_emits_max_scale_denominator_not_min` |
| 2026-08-10 | `frontend/src/utils/mapRenderBundles.ts` | 修改 | `createBundleTileLayer` `visible: false` → `visible: true`（attach 仅对视口内 bundle 发生；注释说明 tileloadend 仅做状态迁移）；attachBundle/tileloadend 注释更新 |
| 2026-08-10 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | `executeBundlePlan` activate 守卫放宽：`status === 'active'` → 仅拦截 `failed` / `replacing`（修复被 suspend 的 warming bundle 无法恢复可见） |
| 2026-08-10 | `frontend/src/utils/mapRenderBundles.test.ts` | 修改 | TileLayer mock 支持 `getVisible`；新增 `createBundleTileLayer` 可见性测试 |

### 测试结果

- 后端：168 passed ✅（167 → 168，+1 方向锁定测试）
- 前端：77 passed ✅（76 → 77，+1 attach 可见性测试）
- TypeScript：vue-tsc 零错误 ✅
- ruff：触碰文件全部干净 ✅

### 关键决策

1. **SLD 方向修正导致 sldHash 变化是预期行为**：部署后需执行 `POST /api/v1/admin/styles/refresh-s57`，使旧图层重发布（SLD 内容从 MinScale 变 MaxScale）+ truncate GWC 缓存，一次幂等完成
2. **`render_sld` 函数本身不改**：min/max 参数均已支持；仅生产调用路径改用 `max_scale_denominator`

---

## 会话 #18 — 批量加载海图图层渲染性能优化（GWC 3413 链路 + Bundle 修复 + SLD 比例尺 + bbox）

**日期**: 2026-08-10
**目标**: 根治批量加载 160 层海图后平移空白、缩放卡顿问题：接通 GWC EPSG:3413 瓦片缓存全链路，修复前端视口裁剪、Bundle 生命周期、SLD 比例尺与发布 bbox 四类缺陷

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 后端：接通 GWC EPSG:3413 瓦片缓存链路（importer + lifespan backfill + admin 端点） | ✅ 完成 |
| 2 | 后端：导入时持久化 s57.extent 元数据（视口裁剪生效） | ✅ 完成 |
| 3 | 前端：cacheable 图层切换 GWC 瓦片端点 + 字段透传 + ENABLE_GWC_TILES flag | ✅ 完成 |
| 4 | 前端：Bundle 生命周期修复（detach/suspend/activate + renderMode 双向切换） | ✅ 完成 |
| 5 | 后端：SLD 比例尺规则 + sldHash/truncate 幂等刷新 | ✅ 完成 |
| 6 | 后端：发布 feature type 支持真实数据 bbox（仅新发布生效） | ✅ 完成 |
| 7 | 文档更新 + 全量验证 + 提交 | ✅ 完成 |

### 根因分析

批量加载 160 层海图后平移空白、缩放卡顿，根因 5 项：

1. **GWC 缓存全链路未接通**：前端 TileWMS 走普通 WMS（TILED 参数对非 GWC 端点无效）；GWC 只为图层启用 3857/4326 gridset，**EPSG:3413 GridSet 从未创建** → 北极投影下瓦片全部直连 WMS 渲染，无任何缓存命中
2. **前端视口裁剪失效**：`s57.extent` 元数据从未写入 → 160 层全部被视为"在视口内"，超出活动预算，调度器无法正确休眠视口外图层
3. **Bundle 生命周期缺陷**：调度器 bundle 分支 `if (false /* TODO */)` 恒空 → 已挂载 bundle 永不 detach，图层泄漏；renderMode 切换只清不补/只补不清，导致空白或残留
4. **SLD 无比例尺规则**：所有样式在所有缩放级别渲染，高密度图层（SOUNDG 等）小比例尺下也渲染
5. **发布 bbox 硬编码全球**：-180..180 使 GeoServer 查询/渲染扫描范围过大

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-09 | `backend/app/services/gwc_backfill.py` | **新建** | `ensure_gridset("EPSG:3413")` 幂等 PUT（extent [-4194304,-4194304,4194304,4194304]）+ `ensure_gwc_layer` 三 gridset（3857/4326/3413）+ `ensure_gwc_3413_backfill()` 纯函数（GET-then-PUT 幂等，`GWC_3413_BACKFILL=0` 跳过） |
| 2026-08-09 | `backend/app/services/importer.py` | 修改 | 发布流程 GWC 启用块抽为 `_enable_gwc_caching`：先 ensure_gridset(EPSG:3413) 再三层 gridset；顺带修复模块级 import 在 logger 之后的问题（E402×11） |
| 2026-08-09 | `backend/app/main.py` | 修改 | lifespan 后台线程 `_spawn_gwc_3413_backfill()`（不阻塞启动）；注册 `system.admin_router` |
| 2026-08-09 | `backend/app/api/system.py` | 修改 | 新增 `admin_router`：`POST /api/v1/admin/gwc/backfill`（require_admin，幂等） |
| 2026-08-09 | `backend/app/api/projects.py` | 修改 | 抽取 `_gwc_transport_for_layer` 共享分类；`GET /map-datasets/{id}/layers` 补 cacheable / render_transport / tile_service_url |
| 2026-08-09 | `backend/app/schemas.py` | 修改 | `MapLayerConfig` 增补 `cacheable` / `render_transport` / `tile_service_url`（可选，向后兼容） |
| 2026-08-09 | `backend/app/core/config.py` | 修改 | 新增 `gwc_3413_backfill`（环境变量 `GWC_3413_BACKFILL`，默认 true） |
| 2026-08-10 | `backend/app/services/importer.py` | 修改 | `merge_s57_layer_metadata` 写入 `s57.extent`（ogrinfo `geometryFields[0].extent`，4 数值校验，NaN/Inf/缺失 → None） |
| 2026-08-10 | `frontend/src/types/index.ts` | 修改 | `MapLayerConfig` 增补 `renderTransport` / `tileServiceUrl` / `cacheable` 三可选字段 |
| 2026-08-10 | `frontend/src/utils/mapLayerBatch.ts` | 修改 | 新增 `ENABLE_GWC_TILES` flag（`VITE_ENABLE_GWC_TILES=false` 回退普通 WMS） |
| 2026-08-10 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | `attachWmsLayer` cacheable 图层切 `/geoserver/gwc/service/wms` + `VERSION: '1.1.1'`（SRS 参数模式）；`loadSelectedDatasets` 透传三字段 |
| 2026-08-10 | `frontend/src/utils/mapRenderScheduler.ts` | 修改 | `RenderPlanInput` 增 `attachedBundleIds`；bundle 分支真实四操作：视口内未挂载 attach / 已挂载 activate / 视口外 suspend / 不在新计划 detach |
| 2026-08-10 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | reconcile 传 `attachedBundleIds`；空计划先 disposeAllBundles；unload 系列（unloadSelectedDatasets / unloadCurrentFilteredLayers / unloadLastBulkBatch）补 reconcile；renderMode watch 双向修复（切 standard 补 attach、切 smart/overview 清 per-layer 残留）；executeBundlePlan activate 守卫（仅 status='active' 才 setVisible） |
| 2026-08-10 | `backend/app/services/s57_styles.py` | 修改 | `render_sld` 支持 `min_scale_denominator` / `max_scale_denominator`（Rule 内、Symbolizer 之前；无参输出与改造前逐字节一致） |
| 2026-08-10 | `backend/app/services/s57_style_refresh.py` | **新建** | `sync_s57_layer_style`：sldHash sha256 对比，变化才 publish + truncate 缓存（`truncate_layer_cache` 复活，best-effort）；`refresh_s57_layer_styles` 批量刷新 |
| 2026-08-10 | `backend/app/api/system.py` | 修改 | 新增 `styles_admin_router`：`POST /api/v1/admin/styles/refresh-s57`（require_admin） |
| 2026-08-10 | `backend/app/services/importer.py` | 修改 | `merge_s57_layer_metadata` 持久化 `s57.minScaleDenominator`；`_apply_s57_style` 委托 `sync_s57_layer_style` |
| 2026-08-10 | `backend/app/services/geoserver.py` | 修改 | `publish_feature_type` / `publish_feature_types_batch` 支持 `bounds` 参数（`_resolve_bounds` 非法值回退全球 -180..180）；`truncate_layer_cache` 复活 |
| 2026-08-10 | `backend/app/services/importer.py` | 修改 | 新增 `_publish_spec_for_layer`：从 `s57.extent` 构建逐层发布 bounds（仅新发布生效） |

### 测试结果

- 后端：167 passed ✅（125 → 167，+42：importer 11 / gwc_backfill 5 / s57_style_refresh 4 / geoserver_publish 15 / projects 3 / test_s57 3 / 端点 1）
- 前端：76 passed ✅（70 → 76，+6：bundle 分支 5 + detach 兜底 1）
- TypeScript：vue-tsc 零错误 ✅
- ruff：本批触碰文件全部干净；全库其余 29 处为改动前已存在的历史 F401 基线（git stash 验证），未触碰

### 关键决策

1. **bundle 保持普通 WMS**：GWC WMS-C 不支持逗号分隔多图层，组合 TileWMS 继续直连普通 WMS；仅 cacheable 单图层切换 GWC 端点
2. **3413 GridSet extent [-4194304,-4194304,4194304,4194304]**：与 OpenLayers 默认 EPSG:3413 瓦片网格对齐，避免双线性重投影额外开销
3. **不做瓦片预热**：缓存自然填充（首次请求渲染 + 写缓存），避免导入期抢资源
4. **已有图层幂等补齐**：`POST /admin/gwc/backfill`（GWC gridset）与 `POST /admin/styles/refresh-s57`（SLD）两个管理员端点；GET-then-PUT / sldHash 对比保证幂等、零重复网络请求
5. **端到端验证由用户在真实 GeoServer 环境执行**：验证方法（curl GWC gridset、X-GWC-Cache 头、160 层平移验证、回退演练）写入"验证方法"而非"已验证"

### 验证方法（真实 GeoServer 环境执行）

```bash
# 1. GridSet 已创建
curl http://localhost:8080/geoserver/gwc/rest/gridsets/EPSG:3413.json
# 2. 图层已启用 3413 gridset（应含 EPSG:3413）
curl http://localhost:8080/geoserver/gwc/rest/layers/polar:{layer}.json
# 3. 瓦片响应带缓存头（X-GWC-Cache: MISS → HIT）
curl -s -o /dev/null -D - "http://localhost:8080/geoserver/gwc/service/wms?LAYERS=polar:{layer}&VERSION=1.1.1&FORMAT=image/png&SRS=EPSG:3413&WIDTH=256&HEIGHT=256&BBOX=..." | grep -i x-gwc-cache
# 4. 批量加载 160 层后平移/缩放验证（活动/休眠统计正常、无空白）
# 5. 回退演练：VITE_ENABLE_GWC_TILES=false 重建前端 → 恢复普通 WMS 行为
```

---

## 会话 #17 — 修复属性表查询失败（column_reference 大小写不匹配）

**日期**: 2026-08-03
**目标**: 修复所有图层"查看属性表"均报"属性表加载失败"的问题

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 诊断属性表查询全链路（前端→后端→SQL） | ✅ 完成 |
| 2 | 修复 column_reference 移除双引号 | ✅ 完成 |
| 3 | 添加 normalize_geo_column_names() 工具函数 | ✅ 完成 |
| 4 | 运行测试 | ✅ 完成 |

### 根因分析

- **DB 验证**: 38,987 层 `allowed_fields` 为大写（如 RCID, PRIM），但 PG 列名均为小写（rcid, prim）
- **SQL 生成**: `column_reference` 使用双引号 `f'"{field}"'` → 生成 `SELECT "RCID"` → PG 大小写敏感 → "column does not exist"
- **回归来源**: commit 441b204 中移除了 `.lower()` 但无数据迁移；旧数据有 UPPERCASE allowed_fields，新 LAUNDER=YES 列是小写
- **错误处理**: PG ProgrammingError 未被 AppError handler 捕获 → HTTP 500 → 前端回退消息"属性表加载失败"

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-03 | `backend/app/api/layers.py` | 修改 | column_reference 移除双引号（使用未加引号标识符，PG 折叠为小写）；新增 normalize_geo_column_names() |

### 测试结果

- 后端：125 passed ✅

### 关键决策

- 未加引号 SQL 标识符安全：字段名已由 field_pattern `^[A-Za-z_][A-Za-z0-9_]*$` 严格校验，无 SQL 注入风险
- 不移除双引号 + 更新 allowed_fields 的方案需要 DB migration，而当前方案纯代码层面解决，向后兼容

---

## 会话 #16 — 修复调度器未触发 + 瓦片请求泛滥 + overview死代码

**日期**: 2026-08-03
**目标**: 修复三个遗留问题：活动/休眠/等待始终为0、底图空白、后续图层加载不出

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 批量加载后调用 reconcileRenderPlan 填充调度器状态 | ✅ 完成 |
| 2 | tileLoadFunction 加 AbortController + 修正 .catch() 重试范围 | ✅ 完成 |
| 3 | SMART_MAX_ACTIVE_WMS_LAYERS 30→20 | ✅ 完成 |
| 4 | 实现 setOverviewVisible（替代空实现） | ✅ 完成 |
| 5 | 新增 SMART_MAX_UNBOUNDED_ACTIVE=10 限制无范围图层占用 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-03 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | 4处：batch后调用reconcile；tileLoadFunction加AbortController+修正重试；setOverviewVisible实现 |
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.ts` | 修改 | SMART_MAX_ACTIVE_WMS_LAYERS 30→20；新增 SMART_MAX_UNBOUNDED_ACTIVE=10 |
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.test.ts` | 修改 | 更新常量测试 |
| 2026-08-03 | `frontend/src/utils/mapRenderScheduler.ts` | 修改 | import/export SMART_MAX_UNBOUNDED_ACTIVE；buildRenderPlan中增加无范围图层计数和预算 |
| 2026-08-03 | `frontend/src/utils/mapRenderScheduler.test.ts` | (no changes) |

### 根因分析

1. **调度器未触发**：批量加载直接调用 attachWmsLayer + setVisible(true)，从未调用 reconcileRenderPlan。activeLayerIds/suspendedLayerIds/warmingLayerIds 三个 Set 仅由 executePerLayerPlan 填充。
2. **底图空白**：fetch() 无 AbortController → 平移时僵尸请求持续占用连接池；.catch() 对所有错误无条件重试 → 重试雪崩；30活动层×20瓦片=600并发请求 → 底图图片加载饿死。
3. **后续图层不加载**：(a) null extent 图层永久占用活动预算；(b) 首轮 reconcile 会将超出预算的图层全部 suspend；(c) 激活已attach图层需要第二次 reconcile 触发。

### 测试结果

- 前端：70 passed ✅
- TypeScript：vue-tsc zero errors ✅

---

## 会话 #15 — 批量加载后优化：warming队列修复 + SOUNDG移除 + UI修复

**日期**: 2026-08-03
**目标**: 修复批量加载后的三个问题：缩放后图层切换失效、数据集展开状态、SOUNDG从核心图层移除

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 后端：SOUNDG 从 CORE_CHART 移到 OPTIONAL_THEMATIC | ✅ 完成 |
| 2 | 后端：更新测试（catalog + bundle + resolve） | ✅ 完成 |
| 3 | 前端：修复 warming 队列永不排空的关键 Bug | ✅ 完成 |
| 4 | 前端：批量加载后数据集展开状态修复 | ✅ 完成 |
| 5 | 前端：辅助性能优化（API 缓存/loadProfile/Set 批量化） | ✅ 完成 |
| 6 | 前端：修复两个测试用例的过期常量值 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-03 | `backend/app/services/s57_layer_catalog.py` | 修改 | SOUNDG 从 _CORE_CHART_RULES 移到 OPTIONAL_THEMATIC |
| 2026-08-03 | `backend/tests/test_s57_layer_catalog.py` | 修改 | EXPECTED_CORE_CHART 移除 SOUNDG；EXPECTED_OPTIONAL_THEMATIC 添加 SOUNDG；更新 display_priority/category 断言 |
| 2026-08-03 | `backend/tests/test_map_render_plan.py` | 修改 | 更新 SOUNDG 的 display_category 测试参数和 categories/objects fixture |
| 2026-08-03 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | 6 处变更见下方详细说明 |
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.test.ts` | 修改 | 更新 SMART_MAX_* 常量的过期望值（20→30, 3→10, 40→60） |
| 2026-08-03 | `frontend/src/utils/mapRenderScheduler.test.ts` | 修改 | 修复 test 26 的排序断言以适配 warming=10 预算 |

### 关键 Bug 修复：warming 队列永不排空

根因：`warmingLayerIds` 仅在 `attachWmsLayer` 中添加、`detachWmsLayer` 中移除，但首块瓦片成功加载（tileloadend）后从不移除。这导致 `warmingLayerIds.size === 10` 永久保持，调度器 gate `warming.length + currentWarmingCount < SMART_MAX_WARMING_LAYERS` 永久拒绝所有后续 attach。

修复：
1. `tileloadend`/`tileloaderror` 回调中：`pendingTiles === 0` 时从 warmingLayerIds 移除
2. `reconcileRenderPlan` 开头：扫描 warming 超时（`TILE_WARMING_TIMEOUT_MS=15s`）图层并排空
3. 新增 `layerWarmingStartTime` Map 记录进入 warming 的时间

### MapWorkspaceView.vue 变更汇总

1. **warming 排空**：tileloadend/tileloaderror 中当 pendingTiles 归零时移除 warmingLayerIds 条目
2. **warming 超时**：reconcileRenderPlan 中扫描超时 warming 图层
3. **数据集展开**：批量加载后标记 `dataset.loaded = true`；toggleDataset 跳过已加载数据集的 API 重取
4. **已加载计数**：数据集摘要行显示"已加载 N 个"
5. **loadProfile 传递**：resolve 结果中的 loadProfile 写入 config.metadata.s57
6. **Set 批量化**：executePerLayerPlan 中 suspend/attach/activate 的 Set 操作收集后一次性更新
7. **Bundle API 缓存**：按 (sorted layerIds + projection) 缓存 bundle plan，避免每次 moveend 请求

### 测试结果

- 后端：125 passed ✅
- 前端：70 passed, vue-tsc clean ✅

### 关键决策

1. SOUNDG 移至 OPTIONAL_THEMATIC 后，display_category 变为 `"optional_thematic"`，display_priority 变为 `100`，recommended 变为 `False`。_SCALE_RULES 和 _OBJECT_BUCKET_OVERRIDES 保留不变。
2. warming 排空采用事件驱动（tileloadend）+ 超时兜底（15s）双保险
3. 不自动展开批量加载的数据集面板，仅标记 `loaded=true` 并显示计数，用户手动控制展开

---

## 会话 #14 — 提高批量加载图层上限至160

**日期**: 2026-08-03
**目标**: 将批量加载图层硬限制从120提高到160

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 修改前端 BULK_HARD_LIMIT 常量 (120→160) | ✅ 完成 |
| 2 | 修改后端 schema max_length (120→160) | ✅ 完成 |
| 3 | 更新前端单元测试 | ✅ 完成 |
| 4 | 验证测试通过 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.ts` | 修改 | BULK_HARD_LIMIT 120 → 160 |
| 2026-08-03 | `backend/app/schemas.py` | 修改 | MapRenderPlanRequest.layer_ids max_length 120 → 160 |
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.test.ts` | 修改 | 测试用例阈值 120/121 → 160/161 |

---

## 会话 #13 — Phase 1: 组合图层渲染通道 (Composite Layer Render Bundles)

**日期**: 2026-08-02
**目标**: 在智能模式下将 20~30 个独立 TileWMS 图层压缩为约 3~6 个语义组合 TileWMS，大幅减少 HTTP 瓦片请求数量

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 后端 Pydantic Schema (MapRenderPlanRequest/Response) | ✅ 完成 |
| 2 | 后端 API 端点 POST /map-render/plan | ✅ 完成 |
| 3 | 后端 API 集成测试 | ✅ 完成 |
| 4 | 前端 TypeScript 类型定义 | ✅ 完成 |
| 5 | 前端 Bundle 运行时 (mapRenderBundles.ts) | ✅ 完成 |
| 6 | 前端 API Client (fetchRenderPlan) | ✅ 完成 |
| 7 | 前端 Scheduler 集成 (BundleRenderPlan) | ✅ 完成 |
| 8 | MapWorkspaceView.vue Bundle 执行路径 | ✅ 完成 |
| 9 | Feature Flag (VITE_ENABLE_RENDER_BUNDLES) | ✅ 完成 |
| 10 | 前端 Bundle 单元测试 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-02 | `backend/app/schemas.py` | 修改 | 新增 MapRenderPlanRequest, BundleConfigOut, StandaloneConfigOut, RenderPlanSummaryOut, MapRenderPlanResponse 五个 Pydantic Schema |
| 2026-08-02 | `backend/app/api/projects.py` | 修改 | 新增 POST /{project_id}/map-render/plan API 端点，复用 _s57_object_class, _style_mapped_for_layer, classify_s57_layer 工具函数，调用 build_bundles() 纯函数 |
| 2026-08-02 | `backend/tests/test_projects.py` | 修改 | 新增 6 个 render plan API 集成测试 (非项目图层拒绝、打包分组、多桶分离、非空间排除、确定性 cache key、空输入) |
| 2026-08-02 | `frontend/src/types/index.ts` | 修改 | 新增 RenderBundleConfig, StandaloneLayerConfig, RenderPlanSummary, MapRenderPlanRequest, MapRenderPlanResponse, BundleViewState 类型 |
| 2026-08-02 | `frontend/src/utils/mapRenderBundles.ts` | **新建** | Bundle 运行时管理: createBundleTileSource, attachBundle, detachBundle, replaceBundle (原子替换), setBundleVisible, disposeAllBundles, findBundleByLogicalLayer |
| 2026-08-02 | `frontend/src/api/projects.ts` | 修改 | 新增 fetchRenderPlan() API client 函数 |
| 2026-08-02 | `frontend/src/utils/mapRenderScheduler.ts` | 修改 | 新增 BundleRenderPlan 接口, ENABLE_RENDER_BUNDLES Feature Flag, buildRenderPlan() 增加 bundlePlanInput 参数和 bundle-aware 执行路径 |
| 2026-08-02 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | reconcileRenderPlan() 改为 async，smart 模式自动调用 fetchRenderPlan；新增 executeBundlePlan() 和 executePerLayerPlan()；toggleLayer() 支持 Bundle 模式延迟重建；switchProjection() 增加 disposeAllBundles；unloadAllChartLayers() 增加 Bundle 清理 |
| 2026-08-02 | `frontend/src/utils/mapRenderBundles.test.ts` | **新建** | 11 个单元测试: TileWMS 创建、comma-separated LAYERS/STYLES、URL 转换、配置校验、桶分离验证 |

### 决策记录

1. **后端纯函数服务已存在**: `map_render_plan.py` 和 `test_map_render_plan.py` (32 个测试) 在本次会话前已实现，只需新增 API 端点和 Schema
2. **Feature Flag 默认启用**: `ENABLE_RENDER_BUNDLES` 默认为 `true`，设置 `VITE_ENABLE_RENDER_BUNDLES=false` 可回退到独立 WMS 模式
3. **Bundle 原子替换**: 切换 Bundle 时旧 Bundle 保持可见直到新 Bundle 首块瓦片加载成功，失败则保留旧 Bundle
4. **Standalone 图层**: opacity ≠ 1.0 或 renderStandalone=true 的图层自动从 Bundle 中提升为独立 TileWMS
5. **无数据库迁移**: 本次变更纯加法 — 新增 API 端点、前端工具模块和类型定义，不涉及数据库或 GeoServer 资源变更

### 验证结果

- Backend: 44 tests passed (32 map_render_plan + 12 projects)
- Frontend: 11 tests passed (mapRenderBundles)
- TypeScript type check: clean (no errors)
- Feature Flag: SET VITE_ENABLE_RENDER_BUNDLES=false for rollback

---

## 会话 #12 — 海图批量加载前端显示性能优化

**日期**: 2026-07-28
**目标**: 分析批量导入 S-57 海图图层后页面加载缓慢和地图卡顿的根因，在不改变现有功能和代码结构的基础上优化前端显示性能

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 调整智能调度器预算常量 (SMART_MAX_*) | ✅ 完成 |
| 2 | Set 状态改用 shallowRef 减少响应式开销 | ✅ 完成 |
| 3 | WMS 图层动态 zIndex 排序 | ✅ 完成 |
| 4 | 实现 tileLoadFunction 瓦片加载重试 | ✅ 完成 |
| 5 | nginx 启用 HTTP/2 | ✅ 完成 |
| 6 | nginx WMS 瓦片 proxy_cache | ✅ 完成 |
| 7 | 静态资源缓存头 (Cache-Control) | ✅ 完成 |
| 8 | 导入后创建 PostGIS 空间索引 + ANALYZE | ✅ 完成 |
| 9 | 标准导入自动启用 GWC 瓦片缓存 | ✅ 完成 |
| 10 | GeoServer JVM 调优 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-28 | `frontend/src/utils/mapLayerBatch.ts` | 修改 | 调度器常量调整: SMART_MAX_WARMING_LAYERS 3→10, SMART_MAX_ACTIVE_WMS_LAYERS 20→30, SMART_MAX_ATTACHED_WMS_LAYERS 40→60 |
| 2026-07-28 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | (1) 7个 Set 状态从 ref() 改为 shallowRef() 减少深层响应式追踪开销; (2) 新增 layerZIndex() 函数按 S-57 对象类分类设置图层 zIndex; (3) 新增 createRetryTileLoadFunction() 用 fetch+指数退避实现瓦片加载重试 |
| 2026-07-28 | `deploy/nginx/default.conf` | 修改 | (1) listen 增加 http2 启用 HTTP/2 多路复用; (2) 新增 proxy_cache_path + proxy_cache 指令缓存 GeoServer 瓦片; (3) 新增静态资源 Cache-Control 头 (hashed资源1y immutable, index.html no-cache) |
| 2026-07-28 | `deploy/compose.yml` | 修改 | GeoServer 添加 INITIAL_MEMORY/MAXIMUM_MEMORY/JAVA_OPTS JVM 调优环境变量 |
| 2026-07-28 | `backend/app/services/importer.py` | 修改 | (1) 导入后为每张 geo.* 表创建 GiST 空间索引并运行 ANALYZE; (2) 发布阶段自动调用 ensure_gwc_layer() 启用瓦片缓存; (3) 添加 logging 模块 |

### 问题分析与发现

通过前端、后端、部署三个维度的全面审查，确认了以下核心瓶颈:

1. **前端**: TileWMS 源未设置 tileLoadFunction 导致瓦片加载无重试; 所有图层 zIndex: 10 导致绘制顺序不稳定; ref(new Set()) 对每个元素深层追踪产生不必要的响应式开销; 暖机预算 3 层过保守
2. **基础设施**: nginx 无 HTTP/2 (浏览器 6 连接限制成为瓦片加载天花板); 无 nginx 瓦片缓存; 静态资源无缓存头
3. **后端**: 导入后无 PostGIS 空间索引 (GeoServer 顺序扫描); GWC 未自动启用; GeoServer 无 JVM 调优

### 关键决策

1. 优化原则: 不改变现有功能、代码结构和加载原理; 批量解析→候选过滤→分批附加流程不变; 三种渲染模式不变
2. 优先前端 + 基础设施改动 (直接改善瓦片加载体验)
3. Layer zIndex 基于 S-57 对象类语义分层: 填充层(10)→等深线(20)→岸线(25)→危险物(30)→水深点(35)→助航标志(40)

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

---

## 会话 #4 — 修复项目创建 422 错误，添加表单校验

**日期**: 2026-07-21
**目标**: 诊断项目管理创建项目时的 422 错误，添加客户端表单校验

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 分析 422 错误原因 | ✅ 完成 |
| 2 | 确认是否与批量导入相关 | ✅ 完成 |
| 3 | 添加前端表单校验 | ✅ 完成 |
| 4 | 提交推送 + 更新文档 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-21 | `frontend/src/views/admin/ProjectManagementView.vue` | 修改 | 添加 el-form 校验: code (正则+长度), name (必填+长度), description (长度), defaultCrs (必填); 对话框关闭时自动重置 |
| 2026-07-21 | `.gitignore` | 修改 | 添加 `北极海图/` 目录 (S-57 数据文件不应提交到仓库) |

### 问题诊断

**422 错误原因**: 项目创建表单没有任何客户端校验，用户输入不符合 `ProjectCreate` Pydantic Schema 的数据直接提交到后端。

`ProjectCreate` 验证规则：
- `code`: `^[a-z0-9][a-z0-9_-]*$`, 2-80字符 → 大写字母、中文、特殊字符均不合法
- `name`: `min_length=1`, `max_length=180` → 空值不合法
- `description`: `max_length=4000`
- `default_crs`: `^EPSG:\d+$`

**与批量导入的关系**: 无关。422 是请求验证层面的错误，批量导入在 Worker 进程中操作不同的数据库表（datasets/dataset_versions/layers/import_jobs vs projects）。

### 解决方案

在 `ProjectManagementView.vue` 中添加 Element Plus 表单校验:
- 使用 `FormInstance` + `FormRules` 在提交前验证
- 校验规则与后端 Schema 保持一致
- 校验失败时阻止请求发出，在 UI 层直接提示用户
- 对话框关闭时自动清理校验状态

---

## 会话 #5 — 批量导入性能优化 + 暂停/取消功能

**日期**: 2026-07-22
**目标**: 解决批量导入188个S-57单元耗时10小时+的性能问题，并新增暂停/取消功能

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 分析批量导入全链路数据流，定位性能瓶颈 | ✅ 完成 |
| 2 | 优化 `_import_vector_layers`: 单次ogr2ogr替代每图层子进程 | ✅ 完成 |
| 3 | 优化 GeoServer 发布: 预设 BBox 跳过全表扫描 | ✅ 完成 |
| 4 | 并行 Cell 处理 (ThreadPoolExecutor) | ✅ 完成 |
| 5 | 新增暂停/取消/恢复 API 端点 | ✅ 完成 |
| 6 | Worker 暂停/取消感知 + 防误杀 stale 检测 | ✅ 完成 |
| 7 | 前端暂停/取消按钮 | ✅ 完成 |
| 8 | 修复测试用例以适配并行处理 | ✅ 完成 |
| 9 | 更新文档 | ✅ 完成 |

### 性能瓶颈分析

**三大瓶颈**（详见分析报告）:
1. **每图层独立 ogr2ogr 子进程**: 188 cells × 40 图层 ≈ 7,520 次子进程调用，每次重新打开文件+新建PG连接 → 2-10小时
2. **每图层独立 GeoServer REST 发布**: 同数量级的 HTTP 调用，每次GeoServer全表扫描计算BBox → 4-10小时
3. **Cell 串行处理**: 无法利用多核CPU

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-22 | `backend/app/models.py` | 修改 | JobStatus 枚举新增 PAUSED = "paused" |
| 2026-07-22 | `backend/app/services/importer.py` | 重写 | `_import_vector_layers`: 临时schema单次ogr2ogr + ALTER TABLE RENAME替代每图层子进程; 新增 `_check_cancelled` 取消感知; publish阶段使用批量发布 |
| 2026-07-22 | `backend/app/services/geoserver.py` | 修改 | `publish_feature_type`: 预设 nativeBoundingBox 跳过GeoServer全表扫描; 新增 `publish_feature_types_batch` 批量发布方法 |
| 2026-07-22 | `backend/app/services/s57_batch.py` | 重写 | `process`: ThreadPoolExecutor并行Cell处理; `_process_cell_worker`: 独立Session线程安全处理; `_finalize_batch`: 独立Session隔离; 暂停/取消检测; batch_parallel_workers可配置 |
| 2026-07-22 | `backend/app/api/datasets.py` | 新增 | pause/resume/cancel 三个API端点 |
| 2026-07-22 | `backend/app/core/config.py` | 修改 | 新增 `batch_parallel_workers` 配置项 (默认8) |
| 2026-07-22 | `frontend/src/views/admin/BatchImportView.vue` | 修改 | 新增暂停/继续/取消按钮，动态显示 |
| 2026-07-22 | `backend/tests/test_s57_batch.py` | 修改 | FakeImportProcessor适配并行处理; create_batch返回session factory; batch_parallel_workers=1 |

### 关键决策

1. **临时 Schema 方案**: 用 `CREATE SCHEMA _imp_{id}` → 单次ogr2ogr → ALTER TABLE SET SCHEMA + RENAME → DROP SCHEMA 模式替代每图层子进程，单Cell的ogr2ogr调用从40次降到1次
2. **ThreadPoolExecutor 而非 ProcessPoolExecutor**: Cell处理是I/O密集型（ogr2ogr子进程+GeoServer HTTP），线程池足够且避免了跨进程session factory问题
3. **暂停语义**: 暂停时完成当前正在运行的Cell，不再启动新Cell。未处理的QUEUED items保留。恢复时将batch.status重置为QUEUED，worker重新拾取
4. **取消语义**: 取消时立即中断，所有QUEUED/RUNNING items标记为CANCELLED
5. **Session隔离**: 主线程和worker线程使用不同DB session（通过session factory），避免SQLite SERIALIZABLE隔离级别导致的数据不可见问题

---

## 会话 #6 — 项目配置"批量选取"数据集功能

**日期**: 2026-07-22
**目标**: 在项目管理→配置数据集对话框中，增设批量选取/取消数据集的功能

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 后端新增 `GET /admin/datasets/available-ids` 轻量端点 | ✅ 完成 |
| 2 | 后端 `GET /admin/projects/{id}/dataset-layers` 新增 search 参数 | ✅ 完成 |
| 3 | 前端新增搜索框 + 批量选取按钮 | ✅ 完成 |
| 4 | 测试 + 文档更新 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-22 | `backend/app/api/datasets.py` | 新增 | `GET /admin/datasets/available-ids` — 返回所有可用数据集的轻量级 ID 列表 |
| 2026-07-22 | `backend/app/api/projects.py` | 修改 | `get_project_dataset_layers` 新增 `search` 查询参数；新增 `or_` 导入 |
| 2026-07-22 | `frontend/src/views/admin/ProjectManagementView.vue` | 修改 | 新增搜索框、全选本页/取消本页/全选全部/取消全部四个批量操作按钮 |

### 关键决策
- "全选全部"通过新端点一次性获取所有匹配数据集 ID，写入 datasetDrafts Map 实现跨页跟踪
- 搜索框与后端联动，输入时自动重新加载第一页

---

## 会话 #7 — 修复图层属性加载失败 + 地图性能优化

**日期**: 2026-07-23
**目标**: 修复S-57图层属性(DSID等)查询失败问题，优化地图瓦片加载性能与状态指示灯闪烁

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 分析图层属性加载失败根因 | ✅ 完成 |
| 2 | 修复 `column_reference()` 强制小写导致SQL不匹配 | ✅ 完成 |
| 3 | ogr2ogr 添加 LAUNDER=YES + allowed_fields小写化 | ✅ 完成 |
| 4 | 图层搜索添加200ms防抖 | ✅ 完成 |
| 5 | 瓦片加载状态稳定化(300ms延迟+定时器管理) | ✅ 完成 |
| 6 | 属性表查询/要素识别添加AbortController | ✅ 完成 |
| 7 | 测试 + 文档更新 | ✅ 完成 |

### 问题诊断

**问题1 — DSID等图层属性加载失败**:
`column_reference()` 在 `backend/app/api/layers.py` 中强制小写字段名(`field.lower()`)，但GDAL ogr2ogr导入S-57数据时(LAUNDER默认=NO)保留原始大写列名("DSID", "LNAM"等)。生成的SQL `"dsid"` 与PostgreSQL实际列 `"DSID"` 不匹配，导致所有大写S-57字段查询失败。

**问题2 — 地图性能退化与状态闪烁**:
- 瓦片加载事件(`tileloadstart`/`tileloadend`)直接变更 `loadState`，无任何防抖/稳定化，每次平移/缩放导致所有可见图层的状态指示灯在黄绿间快速闪烁
- `layerSearch` 无防抖，每次按键触发 `filteredGroups` 重建
- 属性表查询和要素识别无请求取消机制，过时响应会覆盖新结果

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-23 | `backend/app/api/layers.py` | 修改 | `column_reference()` 移除 `.lower()`，保留字段名原始大小写，匹配PostgreSQL实际列名 |
| 2026-07-23 | `backend/app/services/importer.py` | 修改 | ogr2ogr命令添加 `-lco LAUNDER=YES`；`allowed_fields` 存储时小写化 |
| 2026-07-23 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | layerSearch添加200ms防抖(watch+lazyValue)；瓦片loadState添加300ms延迟+定时器清理；searchAttributeRows和identify添加AbortController取消机制 |

### 关键决策
- `column_reference()` 移除小写后新旧数据兼容：旧数据(allowed_fields大写+PostgreSQL列大写)→匹配；新数据(LAUNDER=YES+allowed_fields小写)→匹配
- 瓦片加载延迟300ms：快速加载的瓦片不触发黄色状态，仅持续加载超过300ms才显示loading
- AbortController取消前一个请求后再发新请求，避免并发响应的竞态条件

### 补充修复 (同日)

**问题发现**: 修复上线后 DSID 和 C_ASSO 图层仍然"加载失败"且属性表报错。

**根因**: S-57 的 DSID(数据集元数据) 和 C_ASSO(要素关联) 是非空间图层，`ogrinfo` 报告 `geometryType` 为 null，`ogr2ogr` 创建的表**没有 `geom` 列**。后端 SQL 硬编码 `ST_Transform(geom,4326)` 导致 "column geom does not exist"；GeoServer 发布无空间列的表后 WMS 瓦片请求失败。

**补充修改**:

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-23 | `backend/app/api/layers.py` | 修改 | 新增 `_layer_has_geometry()` 辅助函数；`search_features`/`export_features` 对非空间图层使用 `NULL AS geometry`；`identify_feature` 对非空间图层返回 400 |
| 2026-07-23 | `backend/app/services/importer.py` | 修改 | GeoServer 发布前过滤掉非空间图层(geometry_type 为 unknown/none/空)，仅发布有几何列的表 |
| 2026-07-23 | `backend/app/schemas.py` | 修改 | `MapLayerConfig` 新增 `geometry_type` 字段 |
| 2026-07-23 | `backend/app/api/projects.py` | 修改 | 返回 `MapLayerConfig` 时传递 `geometry_type` |
| 2026-07-23 | `frontend/src/types/index.ts` | 修改 | `MapLayerConfig` 新增 `geometryType` 字段 |
| 2026-07-23 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | 新增 `isNonSpatial()` 判断；非空间图层跳过 WMS 瓦片加载并显示"属性表"标签 |

---

## 会话 #8 — 建立后端 S-57 图层分类事实来源

**日期**: 2026-07-26
**目标**: 为后续导入分类元数据和图层解析 API 建立纯函数、不可变的后端统一分类目录

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 先写精确集合、分类行为、几何判断和不可变性测试 | ✅ 完成 |
| 2 | 运行目标测试，确认因分类模块缺失进入 RED | ✅ 完成 |
| 3 | 实现最小 S-57 分类目录并保持无外部依赖 | ✅ 完成 |
| 4 | 运行目标 pytest 与 ruff，确认 GREEN | ✅ 完成 |
| 5 | 更新 living docs 并自审变更范围 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-26 | `backend/tests/test_s57_layer_catalog.py` | 新建 | 精确锁定五组已知对象集合，并覆盖分类、推荐、渲染、排序、几何与不可变性 |
| 2026-07-26 | `backend/app/services/s57_layer_catalog.py` | 新建 | 提供 `S57LayerRule`、代码规范化、保守几何判断和统一分类纯函数 |
| 2026-07-26 | `docs/09-system-architecture.md` | 修改 | 记录分类服务边界、稳定档案/分类及依赖约束 |
| 2026-07-26 | `docs/10-work-log.md` | 修改 | 记录 TDD 过程、测试结果与关键决策 |
| 2026-07-26 | `docs/11-work-summary.md` | 修改 | 汇总本阶段成果与后续使用边界 |

### TDD 证据

- **RED**: `F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_s57_layer_catalog.py -v` → 收集阶段按预期失败，`ModuleNotFoundError: No module named 'app.services.s57_layer_catalog'`
- **GREEN**: 同一 pytest 命令 → `8 passed, 1 warning`
- **Lint**: `F:/polar-gis/.venv/Scripts/python.exe -m ruff check app/services/s57_layer_catalog.py tests/test_s57_layer_catalog.py` → `All checks passed!`

### 关键决策

1. 分类目录仅使用标准库，不访问数据库、Web 框架、GDAL 或 GeoServer，方便导入流程和 API 后续共同复用。
2. 已知对象始终保留其固定 `load_profile`；`recommended` 仅由核心/航行档案与 `style_mapped=True` 共同决定。
3. 未知有几何对象进入 `optional_other`，未知 `M_` 有几何对象进入 `metadata_quality`，未知无几何对象进入 `non_spatial`。
4. 几何判断只排除明确无几何值，避免将 `GeometryCollection` 等合法类型错误归为非空间。
5. 所有分类结果 `default_visible=False`，不改变现有地图懒加载行为。

### 审查修复（2026-07-26）

- **RED**: 更新测试以直接导入生产五组集合、与独立规格集合精确比较并对生产集合执行两两互斥；同时要求核心集合由完整规则表键派生。运行目标 pytest 得到 `1 failed, 7 passed`，失败点为缺少 `_CORE_CHART_RULES`。
- **GREEN**: 将核心成员与展示元数据统一到 `_CORE_CHART_RULES`，从其键派生公开 `CORE_CHART`，并删除无消费者 `_RESTRICTION_HARBOR`；目标 pytest 恢复为 `8 passed, 1 warning`。
- **Lint**: 目标 ruff 输出 `All checks passed!`。
- **测试简化**: 每组期望集合只保留一份，删除本地集合自我等值断言、重复逐成员计数及对私有规则表名称的实现耦合；最终测试仅锁定公开集合与分类行为。
- **文档维护**: 将架构目录中的固定”40个测试”改为不易过期的”按业务模块组织”。

---

## 会话 #9 — S-57 海图图层批量加载与智能筛选

**日期**: 2026-07-26
**目标**: 在保留现有数据集级懒加载机制下，实现 S-57 数据集批量解析、智能筛选、分批加载、取消和精确卸载

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 验证已完成分类目录 | ✅ 完成 |
| 2 | 导入 metadata 合并 + 非空间过滤 | ✅ 完成 |
| 3 | 项目级批量图层 resolve API | ✅ 完成 |
| 4 | 前端类型、API 客户端、批量纯逻辑 | ✅ 完成 |
| 5 | MapWorkspaceView 批量加载 UI | ✅ 完成 |
| 6 | S-57 更新链校验增强 | ✅ 完成 |
| 7 | 文档更新与最终交付 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-26 | `backend/app/services/importer.py` | 修改 | 新增 `merge_s57_layer_metadata()`；S-57 导入合并分类快照 |
| 2026-07-26 | `backend/app/schemas.py` | 修改 | 新增批量解析 Schema；`MapDatasetConfig` 增加 `dataType` |
| 2026-07-26 | `backend/app/api/projects.py` | 修改 | 新增 `POST /map-layers/resolve` 端点 |
| 2026-07-26 | `backend/app/services/s57_batch.py` | 修改 | 新增 `S57ChainValidationError`；区分 base missing vs update gap |
| 2026-07-26 | `backend/app/api/datasets.py` | 修改 | 批次详情填充 `details.missingUpdates` |
| 2026-07-26 | `backend/tests/test_importer.py` | 新建 | S-57 metadata 合并测试 (7 tests) |
| 2026-07-26 | `frontend/src/types/index.ts` | 修改 | 新增批量解析和进度类型 |
| 2026-07-26 | `frontend/src/api/projects.ts` | 新建 | API 客户端封装 |
| 2026-07-26 | `frontend/src/api/projects.test.ts` | 新建 | API 测试 (3 tests) |
| 2026-07-26 | `frontend/src/utils/mapLayerBatch.ts` | 新建 | 批量常量与纯函数 |
| 2026-07-26 | `frontend/src/utils/mapLayerBatch.test.ts` | 新建 | 批量逻辑测试 (12 tests) |
| 2026-07-26 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | 批量选择/加载/取消/卸载完整实现 |
| 2026-07-26 | `frontend/src/styles.css` | 修改 | 批量工具栏紧凑样式 |
| 2026-07-26 | `docs/*` | 修改 | 更新 02/04/05/09/10/11/12 |

### 验证结果

- **后端**: 61 tests passed, ruff clean
- **前端**: 22 tests passed, vue-tsc clean, vite build 成功
- **无数据库迁移**: 所有新增字段使用已有 JSONB 列

### 关键决策

1. 批量加载复用现有 attachWmsLayer/detachWmsLayer，不创建第二套 WMS 实现
2. 分类事实来源仅在后端维护；前端不复制业务规则
3. 旧数据无 metadata.s57 时动态分类回退，不强制迁移
4. 不可变 Set/Map 替换确保 Vue 3 响应式正确触发
5. 项目无 Playwright 基础，端到端验收留待手工阶段

---

## 会话 #10 — 一键导入全球海图底图

**日期**: 2026-07-27
**目标**: 在现有S-57批量导入功能之上，增加一键导入全球海图概览底图

### 新增文件
- `backend/app/resources/s57_basemap_profiles/global_overview_v1.json` — 18 Cell profile
- `backend/app/services/s57_basemap.py` — 预检 + 后处理服务 (~320行)
- `backend/app/api/s57_basemaps.py` — 管理员 API (profiles/preflight/import/runs)
- `backend/migrations/versions/0004_add_purpose_metadata_to_s57_batches.py` — 迁移
- `backend/tests/test_s57_basemap.py` — 19 测试
- `backend/tests/test_s57_basemap_api.py` — 7 测试
- `北极海图_文件清单.txt` — 1188 文件清单

### 修改文件
- `backend/app/models.py` — S57ImportBatch 新增 purpose + metadata_json
- `backend/app/schemas.py` — 扩展 schema
- `backend/app/core/config.py` — 新增 basemap 配置
- `backend/app/main.py` — 注册路由
- `backend/app/services/geoserver.py` — Layer Group / GWC 方法
- `backend/app/services/s57_batch.py` — basemap 后处理钩子
- `frontend/src/views/admin/BatchImportView.vue` — 底图功能区
- `frontend/src/types/index.ts` — 新类型
- `deploy/.env.example` — 配置项

### 测试结果
- 全部 87 个测试通过 (61 现有 + 26 新增)
- 预检服务 19 测试覆盖 profile 加载、DSID 提取、更新链校验、文件计数
- API 7 测试覆盖访问控制和空源预检

---

## 会话 #11 — 海图批量加载性能优化（阶段一至四）

**日期**: 2026-07-28
**目标**: 解决批量加载S-57海图后浏览器卡顿、瓦片空白、交互响应慢等问题

### 根因分析

1. **无视口裁剪** — 所有已加载图层的 TileWMS 源在每次平移/缩放时同时请求瓦片，40+ 图层产生 320-640 并发请求，超过浏览器 6 连接/源限制
2. **无比例尺过滤** — 高密度图层 (SOUNDG/LIGHTS/BOY*/BCN*) 在所有缩放级别请求瓦片，产生大量几乎透明的瓦片
3. **无并发控制** — 所有图层同时发起瓦片请求，导致队头阻塞和超时级联
4. **业务图层未使用 GWC** — 直接访问 GeoServer WMS，每次平移/缩放重新渲染
5. **GeoServer 硬编码全球范围** — `publish_feature_type()` bbox 为 (-180,-90,180,90)，北极数据扫描范围远大于实际
6. **SLD 无比例尺规则** — 10 个样式预设无 MinScaleDenominator/MaxScaleDenominator
7. **无空间索引** — `importer.py` 未创建 GIST 索引和 ANALYZE
8. **Nginx 无优化** — 无 HTTP/2、gzip、upstream keepalive、缓存头
9. **GeoServer 无 JVM 调优** — compose.yml 无 JAVA_OPTS
10. **投影切换全量重建** — `switchProjection()` 先全部销毁再全部重建

### 第一阶段 — 性能诊断（不改渲染行为）

#### 新增文件
- `frontend/src/utils/mapRenderScheduler.ts` — 纯函数渲染调度器 (~350行)
- `frontend/src/utils/mapRenderScheduler.test.ts` — 32 个单元测试

#### 修改文件
| 文件 | 变更 |
|------|------|
| `frontend/src/types/index.ts` | 新增 MapTilePerformanceStats、ChartRenderMode 类型；BulkResolvedLayer 扩展 8 个可选 GWC/scale 字段 |
| `frontend/src/utils/mapLayerBatch.ts` | 新增 SMART_* 配置常量 (10个)；新增 PerLayerStatsManager 类 |
| `frontend/src/views/MapWorkspaceView.vue` | 接入瓦片加载耗时统计 (tileloadstart/end/error)；map-status 增加性能展示+可折叠调试面板 |
| `deploy/nginx/default.conf` | 增加 perf 日志格式 ($request_time/$upstream_response_time)；gzip；upstream keepalive；缓存头穿透 |
| `frontend/src/styles.css` | 性能统计样式、图层状态文字样式、batch-mode-row |

### 第二阶段 — 视口裁剪 + 比例尺 + RenderPlan 纯函数

- 实现 `buildRenderPlan()` 核心调度算法，输出 activate/attach/suspend/detach/warming 五类操作
- `isLayerInViewport()`: extent→当前投影转换 + 20% buffer + intersects 判断；null extent 保守放行
- `isLayerInScaleRange()`: 显式 zoom/minScaleDenom → 回退 DEFAULT_SCALE_HINTS (30+ S-57 对象类)
- `sortRenderCandidates()`: 手动强制优先 → displayPriority ASC → objectClass → id
- DEFAULT_SCALE_HINTS 集中维护：SOUNDG minScale=25000，导航标志 minScale=50000，危险物 minScale=100000 等
- resolutionToScaleDenom/scaleDenomToResolution 转换函数
- 32 个单元测试覆盖：视口裁剪/比例尺过滤/warming 预算/活动预算/LRU/模式语义/边界情况

### 第三阶段 — 状态分离 + reconcileRenderPlan + 智能模式调度

- 单 `loadedLayerIds` 拆分为 7 个状态集：selectedLayerIds / attachedLayerIds / activeLayerIds / warmingLayerIds / suspendedLayerIds / manuallyForcedLayerIds / failedLayerIds
- `toggleLayer()` 控制 selectedLayerIds，scheduler 决定何时 attach/activate
- `attachWmsLayer`/`detachWmsLayer` 同步更新所有状态集
- `reconcileRenderPlan()`: moveend 150ms 防抖调用 buildRenderPlan → 执行 plan
- `runLruEviction()`: 30s 后清理非选中/非强制休眠图层（保护底图/WMTS/AIS/气象/测量/属性表）
- 批量工具栏增加模式切换、活动/休眠/等待统计、清理休眠按钮
- 图层行增加状态文字（已显示/加载中/视口外休眠/等待加载/加载失败）
- `switchProjection()` 使用 renderGeneration + reconcileRenderPlan

### 第四阶段 — 后端 GWC 传输提示 + 比例尺提示

| 文件 | 变更 |
|------|------|
| `backend/app/schemas.py` | BulkResolvedLayer 新增 render_transport/tile_service_url/grid_set/cacheable/min_scale_denominator/max_scale_denominator/render_cost |
| `backend/app/services/s57_layer_catalog.py` | S57LayerRule 新增 4 个 scale 字段；新增 `_SCALE_RULES` 字典 (30+ 对象类)；classify_s57_layer() 应用 scale hints |
| `backend/app/api/projects.py` | `_build_resolved_layer()` 计算 GWC cacheable → render_transport=gwc_wms/wms；返回 tile_service_url + scale hints |

### 部署修复

- `backend/Dockerfile` & `frontend/Dockerfile`: 配置阿里云 PyPI/npm 镜像，pip timeout 120s
- `deploy/compose.yml`: S-57 底图卷挂载从绝对路径 `/data/s57-basemaps` 改为相对路径 `../data/s57-basemaps`
- `deploy/nginx/default.conf`: HTTP/2 支持完成

### 测试结果

- 后端 87 个测试全部通过
- 前端 59 个测试全部通过 (27 已有 + 32 新增)
- TypeScript vue-tsc 零错误
- Python pytest 零错误

### 关键决策

1. 状态分离：selected ≠ attached ≠ active ≠ warming ≠ suspended，各司其职
2. 纯函数调度：buildRenderPlan 无副作用，仅依赖 extent/proj 工具
3. 比例尺规则单源：DEFAULT_SCALE_HINTS (前端) 与 _SCALE_RULES (后端) 保持同步
4. standard 模式 = 完全向后兼容，一键回退
5. LRU 保护清单：底图/WMTS/AIS/气象/测量/选择高亮/编辑图层/属性查询图层 永不驱逐
6. 新增 API 字段全部可选，旧客户端不受影响
