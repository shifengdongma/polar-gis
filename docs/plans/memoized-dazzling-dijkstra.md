# 计划：WMS 瓦片请求修复 — 消除重复渲染 + 放宽合并键 + 稳健性修复

## Context（问题与根因）

批量加载 100+ S-57 图层后，每次平移地图仍产生海量瓦片请求（用户网络日志实测：每可见瓦片 ≈ 10 个请求，其中 7 个单层 + 3 个合并，覆盖完全相同的 7 个图层），导致加载缓慢、卡顿、地图空白。上一轮"请求合并"方案（tileCache + tileRequestQueue + mapTileMerger）已实现，但合并未生效且存在重复渲染。经系统化调试确认两大根因 + 5 个附带 bug：

**根因 1（请求翻倍）：smart 模式下批量挂载与 bundle 渲染同时覆盖同一批图层**
- `loadSelectedDatasets` → `loadResolvedLayersInBatches`（MapWorkspaceView.vue:1325）把全部解析图层挂为标准 TileWMS 层（无视 renderMode / bundle 覆盖）
- 随后 `reconcileRenderPlan()`（L1342）为同样 layerId 建 bundle（1.3.0 逗号 LAYERS+STYLES 普通 WMS）
- 调度器 `mapRenderScheduler.ts:436-437` 有意跳过 bundle 覆盖图层的 per-layer 管理 → 批量挂载的层永不 detach，与 bundle 并存 → 同一图层每瓦片请求两次

**根因 2（标准模式合并退化）：合并键过窄**
- `mapTileMerger.ts` 键 = `(serviceUrl, renderTransport, styleName, objectClass)`（L22-32）→ 7 个不同 objectClass 的 S-57 图层 = 7 个单成员组 → 单成员 gwc 组仍走 GWC 1.1.1 单层请求，合并器形同虚设
- bundle 请求已证明：普通 WMS 支持逗号拼接 LAYERS + 逐层混合 STYLES（`STYLES=s57_depth,,s57_land`）

**附带 bug**（均加剧空白/卡顿）：
1. 组成员 detach 后共享源 LAYERS/STYLES 参数静态残留，已删图层继续被请求；重新单独挂载又产生重复请求族（mapTileMerger.ts:207-212 + detachWmsLayer L705-719）
2. 重试 off-by-one：实际 3 次尝试而非 `TILE_RETRY_MAX_ATTEMPTS=2`（L574/L596 的 `<=` 应为 `<`）
3. 队列溢出静默丢弃最老请求（tileRequestQueue.ts:77-80）→ 瓦片永不 resolve → 空白
4. 不可恢复 HTTP 错误 / 重试耗尽不赋值 img.src（L581-583 返回 null，L585 跳过）→ 瓦片卡 LOADING，无 tileloaderror
5. `reset()` 清零 inFlight 而请求仍在飞（L109-112）→ 卸载/投影切换后并发瞬时超限

**用户已确认的决策**：合并键放宽为跨样式/类别全量合并（多图层组强制普通 WMS，接受失去 GWC 服务端缓存）；根因 + 全部小 bug + 一致性优化一并修复。

---

## 修改方案（按实现顺序）

### 1. `frontend/src/utils/mapTileMerger.ts` — 合并键放宽

- **新键**：`MergeGroupKey = (serviceUrl, renderTransport)`，删除 `styleName`/`objectClass`；分桶序列化 `key.serviceUrl|key.renderTransport`（L92）
- **`effectiveServiceUrl` 增加 `ENABLE_GWC_TILES` 门控**（import 自 mapLayerBatch，无循环依赖），与 attachWmsLayer L622-623 行为一致
- **新增 `MergeableLayer` 接口 + `toMergeableLayer(config: MapLayerConfig)` 适配器**：`BulkResolvedLayer` 结构化兼容（types/index.ts L284-321），使批量路径（BulkResolvedLayer）与 buildMap/投影切换路径（MapLayerConfig）共用 `groupResolvedLayers`
- **组内排序**改为 `(layerZIndex(objectClass), sortOrder, id)`（GeoServer 按 LAYERS 顺序自底向上绘制，需与客户端 zIndex 堆叠一致）；`MergeGroup` 增加 `zIndex`（组内最小 zIndex），组间按 zIndex 排序
- **新增纯函数**：
  - `joinLayerParams(layerNames, styles)` → `{LAYERS: a,b,c, STYLES: s1,,s2}`（保持空位对应默认样式）
  - `globalWmsUrl(serviceUrl)` → `/geoserver/<ws>/wms` 改写为 `/geoserver/wms`（全局端点可解析限定名，防跨 workspace 400；正则不匹配则原样返回）
- **`createMergedTileSource`**：多图层组 URL = `browserGeoServerUrl(globalWmsUrl(regularServiceUrl))`；参数用 `joinLayerParams`；保留 `useGwc = !isMultiLayer && renderTransport === 'gwc_wms'`（单层 gwc 组仍走 GWC + VERSION 1.1.1；多图层强制普通 WMS，无 VERSION → 1.3.0）；`MAX_LAYERS_PER_GROUP=20` 分块不变
- 更新模块文档注释（L1-9、L80-85）

### 2. `frontend/src/utils/tileRequestQueue.ts` — bug 3、5

- **溢出改为拒绝最新请求**（预检 `queue.length >= maxQueue` → reject 最新 `QuotaExceededError`）：被拒瓦片转 ERROR → OL 下次渲染自动重取（已核实 `ol/ImageTile.js:189-207` ERROR→IDLE）；旧行为丢弃最老请求会永久搁置正在加载的瓦片
- **`reset()` 删除 `this.inFlight = 0`**：在飞请求完成时自然递减计数；原实现清零后 `tryDequeue` 会超过 maxConcurrent。`abortAll()` 保持只拒排队请求
- 更新类注释（L34-40）

### 3. `frontend/src/utils/mapRenderScheduler.ts` — 暴露 bundle 覆盖集

- `BundleRenderPlan`（L112-123）增加 `bundledLayerIds: string[]`；bundle 分支返回处（L551-558）填入已计算的 `bundledLayerIds` 集合。供 4.6 安全网使用。其余逻辑不动

### 4. `frontend/src/views/MapWorkspaceView.vue` — 去重 + 重建 + 一致性 + 修复

**4.1 bug 2+4（`createRetryTileLoadFunction` L537-605）**：import `TileState from 'ol/TileState'`
- 两处重试守卫 `attempts <= TILE_RETRY_MAX_ATTEMPTS` → `attempts < TILE_RETRY_MAX_ATTEMPTS`（L574、L596）
- HTTP 分支非可恢复/重试耗尽路径：`return null` 前执行 `tile.setState(TileState.ERROR)`（L581-583）；网络分支 catch 中补 `else if (!signal.aborted) tile.setState(TileState.ERROR)`。已核实 OL 10.6.1：ERROR 状态经 `UrlTile.handleTileChange`（ol/source/UrlTile.js:133-152）派发 source `tileloaderror`，现有三处事件绑定（单层 L659-669 / 合并组 L1411-1423 / bundle）全部生效

**4.2 合并组运行时抽取（重构 L1362-1425）**：
- `registerMergedGroup(gid, group, source)`：成员映射 + `mergedGroupRuntimes` 注册 + 三事件绑定。**事件闭包必须迭代 `grpRuntime.memberIds`**（而非捕获的局部 Set，当前 L1379 的缺陷），使成员集替换安全
- `syncMergedGroup(gid, group)`：gid 已存在时（如部分 detach 后整组重挂）更新成员集 + `source.updateParams(joinLayerParams(...))`
- `attachRuntimeGroups(runtimes, optionsFor?, visible = true)`：通用合并挂载助手——过滤 `wmsLayers`/非空间层；`!ENABLE_TILE_MERGING` 时回退逐层 attachWmsLayer；分组→复用或创建源→逐成员 attachWmsLayer（传每成员自己的 minZoom/maxZoom 与 extent，不再传组级并集缩放）

**4.3 bug 1（`detachWmsLayer` L699-748 重建）**：组成员移除后，若组非空 → `dirtyMergedGroups.add(gid)` + `queueMicrotask(flushDirtyMergedGroups)`（批量 detach 合并为一次重建）；`flushDirtyMergedGroups` 用剩余成员的 serviceLayerName/styleName 调 `grp.source.updateParams(joinLayerParams(...))`。**选 updateParams 而非 dispose+recreate 的理由**（已核实 OL 10.6.1）：`updateParams` → `setParams_` → `setKey` → `changed()`，瓦片缓存键含 sourceKey（ol/tilecoord.js:71）→ 新参数产生新缓存项并重取，避免重绑三事件、避免逐成员 `TileLayer.setSource`。已知限制：多图层组缩到单成员仍走普通 WMS URL（仅失去 GWC 优化，渲染正确）

**4.4 smart 模式去重（核心）**：
- 抽取 `fetchBundlePlanInputFor(layerIds, crs, viewExtent, zoom)`（含 L959-989 的缓存逻辑）；`reconcileRenderPlan` 内联块替换为调用它（保留 L996-998 dispose 回退）
- `loadSelectedDatasets` 在确认后、批量挂载前：smart 模式 + bundles 开启时，用**投影选择集（selected ∪ candidates）**预取 plan（与挂载后 reconcile 的缓存键一致 → 不重复请求）；计算 `bundleCoveredIds`（所有 bundle 的 layerIds 并集）；失败 → 空集走全量挂载回退（4.6 安全网兜底）
- `loadResolvedLayersInBatches(candidates, generation, bundleCoveredIds = new Set())`：
  - 预处理：被覆盖且未加载的候选只做登记（`runtime.visible=true`、加入 selectedLayerIds/lastBulkAttachedLayerIds、progress 计数，**不创建 OL 层**，不入 attachedLayerIds）
  - `toAttach = candidates.filter(c => !bundleCoveredIds.has(c.id))` 再分组挂载
  - 合并挂载传每成员自己的 `resolved.minZoom/maxZoom`（替换 L1481-1482 的组级并集）
  - 源创建+事件绑定块替换为 `registerMergedGroup` 调用
- 顺序：resolve → 阈值/确认 → 预取 plan → 分批挂载（跳过被覆盖）→ 最终 `reconcileRenderPlan()`（缓存命中 → 挂 bundle；standalone 已被合并组挂载，调度器 `attachedLayerIds` 守卫跳过）

**4.5 一致性（三处改用合并组挂载）**：
- `buildMap`（L481-488）：`attachRuntimeGroups(runtimeLayers.filter(rt => rt.visible))` + 保持原 selection 登记语义
- 模式 watcher smart→standard（L325-335）：`disposeAllBundles` + `attachRuntimeGroups(选中且未挂载的)`；standard→smart 分支不动（detachWmsLayer 已能正确重建）
- `switchProjection`（L862-871）：收集 `savedSelectedIds` 成员 → `attachRuntimeGroups(collect, rt => ({extent: transformLayerExtent(...)}), true)`

**4.6 安全网（`executeBundlePlan` L1093 前）**：对 `bundlePlan.bundledLayerIds` 中仍存在 `wmsLayers` 条目的层执行 `detachWmsLayer`——保证任何路径（plan 预取失败、bundle 建立前已挂载）"bundle 胜出"，预取排除只是优化而非唯一防线

**4.7 `layerStatusLabel`（L881-900）**：smart 模式下 `isLayerCoveredByBundle(layerId)` → 返回"已显示"（被 bundle 覆盖的层不在 attached/active 集，否则误显示"等待加载"）

### 5. 测试（vitest 3，`frontend/` 下 co-located `*.test.ts`，复用 mapRenderBundles.test.ts 的 TileWMS mock 模式）

- **新建 `src/utils/mapTileMerger.test.ts`**：computeMergeKey 跨样式/类别同键；groupResolvedLayers 3 层异样式 → 单组；组内 zIndex 排序；45 层 → 20/20/5 分块；缩放并集；组间 zIndex 排序；joinLayerParams 空位保留（`s1,,s2`）；globalWmsUrl 三种情形；createMergedTileSource 三情形（多层→全局普通 WMS 无 VERSION / 单层 gwc→tileServiceUrl+VERSION 1.1.1 / 单层普通→serviceUrl）；toMergeableLayer 字段映射
- **新建 `src/utils/tileRequestQueue.test.ts`**（`vi.stubGlobal('fetch', ...)` + 手动 resolve 的 deferred）：溢出拒绝最新、FIFO 继续；reset 后 inFlight 计数准确（maxConcurrent=2 时 C 不得提前启动）；abortAll 只拒排队；预中止 signal 立即拒
- **更新 `src/utils/mapRenderScheduler.test.ts`**：bundle 分支断言 `bundledLayerIds` = 输入 bundles 的 layerIds 并集

### 6. 文档 + git（CLAUDE.md 强制）

1. `docs/09-system-architecture.md`：新合并键语义、smart 去重流程（预取→排除→安全网）、合并组微任务合并重建、队列溢出策略
2. `docs/10-work-log.md`：追加本次任务计划、修改与决策（含 updateParams vs recreate 的取舍）
3. `docs/11-work-summary.md`：更新修改与效果
4. `git add -A && git commit && git push origin master`（提交信息如 `fix: 合并键放宽为(transport,serviceUrl) + smart 模式批量去重 + 队列/重试/瓦片错误修复`）

---

## 验证

命令：
- `cd F:/polar-gis/frontend && npm test`（新旧用例全绿）
- `npm run typecheck`；可选 `npm run build`
- 后端 + GeoServer 运行中，`npm run dev` → http://localhost:5173

手工验证（DevTools Network 过滤 `/geoserver`）：
1. 批量加载 10+ S-57 数据集（core_chart 与 all_spatial 各测一次）
2. **smart 模式**：稳定后每可见瓦片 ≈ 每 bundle 1 个请求（逗号 LAYERS 普通 WMS）+ 每 standalone 组 1 个合并请求；**断言无 bundle 覆盖 layerId 的单层 GWC 请求**；无空白瓦片
3. **切标准模式**：每瓦片 ≈ ceil(N/20) 个合并普通 WMS 请求；平移流畅，perf 面板 pending 有界
4. 标准模式 toggle 单个合并图层 off/on：组请求 URL 不再含已删图层名（重建生效）；重挂后无重复请求族
5. 加载中切换投影 3857↔3413：无卡死瓦片、无重复请求族、并发 ≤ 16
6. smart↔standard 反复切换：同帧无单层+bundle 同层双重渲染；图层面板 bundle 覆盖层显示"已显示"
7. `VITE_ENABLE_TILE_MERGING=false`：标准模式回退逐层单源（无回归）
8. `VITE_ENABLE_GWC_TILES=false`：合并组一律普通 WMS（门控生效）

## 风险与回退

- 空 STYLES 位置（`s57_depth,,s57_land`）GeoServer 视为默认样式——bundle 模式已实证，`joinLayerParams` 保留空位不滤除
- 跨 workspace：多图层组走 `/geoserver/wms` 全局端点（限定名可解析）；URL 非标准模式时回退 regularServiceUrl（当前部署单 workspace，风险低）
- plan 缓存：键 = 排序选择集|CRS，切换/投影变更即失效；批量中途 debounce reconcile 可能以部分选择集覆盖缓存 → 最终 reconcile 多一次请求，无正确性问题
- 队列溢出拒绝最新在持续超载下可能产生瓦片 churn，但 `TILE_MAX_QUEUED_FETCH=512` 远高于正常负载
- 预取增加一次 POST，随 `bulkAbortController.signal` 取消，取消后缓存键不匹配自然废弃
- 多图层组缩至单成员停留在普通 WMS（仅错过 GWC 缓存优化，渲染正确）——已在 4.3 注明
