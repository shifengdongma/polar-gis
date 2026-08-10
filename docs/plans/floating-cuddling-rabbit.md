# Plan: WMS 瓦片请求合并 — 缓解批量图层加载卡顿

## Context

批量加载 S-57 图层后（标准 per-layer 模式），每次移动地图都会为 **每个图层 × 每个可视瓦片** 产生独立 WMS 请求。100+ 图层加载后，单次平移触发 `~16 tiles × 100+ layers ≈ 1600+` 并发 `fetch()` 调用，远超浏览器 HTTP/1.1 连接池（6-10/域名），导致加载缓慢、UI 卡顿、地图空白。

**目标**：将同一组可合并的图层请求合并为一个 WMS 请求（逗号分隔 LAYERS 参数），大幅减少 HTTP 请求数，同时加入并发限制和瓦片缓存。

Bundle 模式（`createBundleTileSource()`）已通过逗号分隔 LAYERS 实现了合并，本方案将相同原理应用到标准模式。

---

## 实施方案（三个组件，按顺序实现）

### Component A: 瓦片响应缓存 (`frontend/src/utils/tileCache.ts`)

**最简单，立即见效。** 避免平移回已访问区域时重复请求相同瓦片。

- 新建 `LRUTileCache` 类：URL → Blob 的 LRU 缓存
- 利用 `Map` 的插入顺序实现 O(1) get/set/evict
- 默认上限：2048 entries / 50MB
- 在 `createRetryTileLoadFunction()` 中，fetch 前先查缓存命中直接返回 Blob
- 失效时机：地图销毁、投影切换时 `clear()`
- 常量加入 `mapLayerBatch.ts`：`TILE_CACHE_MAX_ENTRIES`、`TILE_CACHE_MAX_BYTES`

### Component B: 并发请求队列 (`frontend/src/utils/tileRequestQueue.ts`)

**独立组件，上限并发数。** 防止浏览器连接池被淹没。

- 新建 `TileRequestQueue` 类：FIFO 队列 + 最大并发数限制
- 默认 maxConcurrent=16，maxQueue=512
- 支持 `AbortSignal`：排队中的请求可被取消；进行中的请求通过 fetch signal 中断
- 在 `createRetryTileLoadFunction()` 中将 `fetch(src, ...)` 替换为 `tileRequestQueue.fetch(src, signal)`
- 与现有重试逻辑解耦：队列只做并发控制，重试由 `tryLoad()` 的 `setTimeout` 递归调用处理
- 常量加入 `mapLayerBatch.ts`：`TILE_MAX_CONCURRENT_FETCH`、`TILE_MAX_QUEUED_FETCH`

### Component C: TileWMS 源合并（`frontend/src/utils/mapTileMerger.ts`）**【核心】**

**直接减少 TileWMS 源数量 → 减少 HTTP 请求数。** 将同一组的多个图层合并到一个共享 TileWMS 源。

**合并键**: `(serviceUrl, renderTransport, styleName, objectClass)`
- `serviceUrl` — 必须指向同一 GeoServer 实例
- `renderTransport` — `wms` 和 `gwc_wms` 使用不同端点/WMS 版本，不可混用
- `styleName` — 单个 WMS 请求只能应用一套样式；不同样式的图层需分开
- `objectClass` — 决定 zIndex，同 zIndex 的图层使用同一 TileLayer 更方便

**新建模块 `mapTileMerger.ts`**：
- `groupResolvedLayers(candidates, runtimes)` → `MergeGroup[]`：将候选图层按合并键分组
- `createMergedTileSource(group, tileLoadFn)` → `TileWMS`：创建共享源，`LAYERS` 逗号拼接
- `createMergedGroupLayers(group, source, runtimes)` → `{tileLayer, layerId}[]`：为每组创建 N 个共享源的 TileLayer
- 大组拆分：>20 层/组时自动分割（URL 长度限制）

**修改 `MapWorkspaceView.vue`**：

1. **`loadResolvedLayersInBatches()`（line 1278）**：调用 `groupResolvedLayers()` 分组后按组创建共享 TileWMS 源 + N 个 TileLayer，替代逐层 `attachWmsLayer()`
2. **`attachWmsLayer()`（line 567）**：新增可选参数 `sharedSource?: TileWMS`，传入时跳过源创建，仅创建 TileLayer
3. **`detachWmsLayer()`（line 653）**：合并组内图层被移除时，若组为空则销毁共享源；否则保留（多余的 LAYERS 名被 WMS 忽略）
4. **新增状态**：`mergedGroupMembers: Map<layerId, groupId>` 追踪合并关系

**其他 `attachWmsLayer` 调用点**：
- 渲染模式切换到 standard（line 306）、初始 buildMap（line 457）、投影切换（line 793）→ 批量场景使用分组附加
- 单独 toggle（line 722）、smart 模式 standalone（line 989）→ 保持原样

**Feature Flag**：`ENABLE_TILE_MERGING`（默认 on，`VITE_ENABLE_TILE_MERGING=false` 可关闭）

---

## 影响范围

### 新建文件
| 文件 | 说明 |
|------|------|
| `frontend/src/utils/tileCache.ts` | LRU 瓦片 Blob 缓存 |
| `frontend/src/utils/tileRequestQueue.ts` | 并发限制请求队列 |
| `frontend/src/utils/mapTileMerger.ts` | 图层分组合并 + 共享源创建 |

### 修改文件
| 文件 | 修改内容 |
|------|---------|
| `frontend/src/utils/mapLayerBatch.ts` | 新增 constants + feature flag |
| `frontend/src/views/MapWorkspaceView.vue` | `attachWmsLayer` 增加 sharedSource 参数、`loadResolvedLayersInBatches` 使用分组逻辑、`detachWmsLayer` 处理合并组、`createRetryTileLoadFunction` 集成缓存+队列、新增 mergedGroups 状态、批量调用点使用分组 |

### 不修改
- `frontend/src/utils/mapRenderBundles.ts` — bundle 模式已使用逗号 LAYERS 合并，不需要改动
- 后端 — 无变更需求；逗号 LAYERS 是 GeoServer 标准 WMS 参数，已在 bundle 模式中使用

---

## 验证方法

1. **单元测试**（`vitest`）：`tileCache.test.ts`、`tileRequestQueue.test.ts`、`mapTileMerger.test.ts`
2. **端到端验证**：
   - 批量加载 100+ 图层，确认 `wmsLayers.size < 候选数`（分组生效）
   - 平移地图，DevTools Network 面板：并发请求 ≤ 16
   - 地图无空白区域，平移流畅无卡顿
   - 回到已访问区域：瓦片从缓存加载（DevTools 显示 200 OK from disk/memory 或队列直接跳过）
   - 切换投影、切换渲染模式无泄漏或重复渲染
   - `VITE_ENABLE_TILE_MERGING=false` 时行为不变（向后兼容）

---

## 实现顺序

1. **Component A** — 瓦片缓存（最简单，独立）
2. **Component B** — 并发队列（独立，可与 A 并行）
3. **Component C** — 源合并（依赖 A+B 就位，最大化效果）
