# S-57 海图图层批量加载前端显示性能优化计划

## Context

当前项目在批量导入 S-57 海图图层后，页面出现**加载缓慢**和**地图拖拽/缩放卡顿**问题。经对前端 `MapWorkspaceView.vue`、`mapLayerBatch.ts`、`mapRenderScheduler.ts`、后端 `importer.py`、`geoserver.py`、部署 `compose.yml` 和 `nginx/default.conf` 的全面审查，确认了以下核心瓶颈：

- **前端侧**：瓦片加载无重试机制、所有图层相同 zIndex 导致绘制闪烁、响应式 Set 频繁触发全量追踪、暖机预算过于保守(3层)、调度器每次 moveend 全量 O(n) 视口检查、tileLoadFunction 定义但从未接入
- **基础设施侧**：nginx 无 HTTP/2（浏览器每源 6 连接限制成为瓦片加载天花板）、无 nginx 瓦片缓存、静态资源无缓存头
- **后端/GeoServer 侧**：导入后无 PostGIS 空间索引、无 GWC 自动配置、GeoServer 无 JVM 调优

优化原则：**不改变现有功能、代码结构和加载原理**。批量解析→候选过滤→分批附加流程不变。三种渲染模式(standard/smart/overview)不变。

---

## 高优先级（直接影响前端瓦片加载和交互流畅度）

### 1. 实现 tileLoadFunction 瓦片重试

**文件**: `frontend/src/views/MapWorkspaceView.vue` (第444-449行)

**问题**: `TILE_RETRY_MAX_ATTEMPTS` 和 `TILE_RETRY_BASE_DELAY_MS` 已在 `mapLayerBatch.ts` 定义，但 `TileWMS` 创建时从未设置 `tileLoadFunction`，瓦片加载失败无任何重试。

**方案**: 在 `attachWmsLayer` 中新增 `createRetryTileLoadFunction` 工厂函数，用 `fetch` + 指数退避 (300ms→600ms) 替代默认的 Image 加载，对 429/502/503/504 及网络错误重试最多 2 次。利用已有的 `perfStats.recordRetry()` 记录重试次数。

**不改动**: `TileWMS` 源的其他参数 (url, params, crossOrigin, transition) 不变。

---

### 2. WMS 图层动态 zIndex 排序

**文件**: `frontend/src/views/MapWorkspaceView.vue` (第477行)

**问题**: 所有图层 `zIndex: 10`，智能调度器动态附加/分离导致绘制顺序不确定，产生视觉闪烁。

**方案**: 新增 `layerZIndex(objectClass)` 工具函数，基于 S-57 对象类语义分层：
- 填充层 (DEPARE/LNDARE/ICEARE/SEAARE) → zIndex 10
- 等深线 (DEPCNT) → zIndex 20  
- 岸线/航道 (COALNE/NAVLNE/FAIRWY) → zIndex 25
- 危险物 (WRECKS/OBSTRN/UWTROC) → zIndex 30
- 水深点 (SOUNDG) → zIndex 35
- 助航标志 (LIGHTS/BOY*/BCN*) → zIndex 40
- 默认 → 15

在 `TileLayer` 创建处将 `zIndex: 10` 替换为 `zIndex: layerZIndex(runtime.config.objectClass)`。

---

### 3. 提高智能调度器预算常量

**文件**: `frontend/src/utils/mapLayerBatch.ts` (第21-27行)

**问题**: 暖机预算 3 层过保守，批量加载 50+ 图层时后续图层被阻塞等待超时(15s)。

**方案**: 调整常量值（不改逻辑）：
- `SMART_MAX_WARMING_LAYERS`: 3 → **10**
- `SMART_MAX_ACTIVE_WMS_LAYERS`: 20 → **30**
- `SMART_MAX_ATTACHED_WMS_LAYERS`: 40 → **60**

---

### 4. Set 状态改用 shallowRef 减少响应式开销

**文件**: `frontend/src/views/MapWorkspaceView.vue` (第150-164行)

**问题**: 7个 `ref(new Set<string>())` 对 Set 内每个元素做深层追踪，但模板只关心 `.size` 和 `.has()` 成员检查，深层追踪产生不必要开销。

**方案**: 将 `ref()` 改为 `shallowRef()`：
```typescript
import { shallowRef } from 'vue'
const selectedLayerIds = shallowRef(new Set<string>())
const attachedLayerIds = shallowRef(new Set<string>())
const activeLayerIds = shallowRef(new Set<string>())
const warmingLayerIds = shallowRef(new Set<string>())
const suspendedLayerIds = shallowRef(new Set<string>())
const manuallyForcedLayerIds = shallowRef(new Set<string>())
const loadingLayerIds = shallowRef(new Set<string>())
```

每次用新 Set 替换 `.value` 即可触发更新（现有代码已采用此模式，无需改动 Set 操作逻辑）。

---

### 5. nginx 启用 HTTP/2

**文件**: `deploy/nginx/default.conf` (第13-14行)

**问题**: `listen 80` 无 `http2`，浏览器对同源 HTTP/1.1 限制 6 并发连接，20+ 瓦片并发请求被串行化。

**方案**: 修改 `listen` 指令添加 `http2`：
```nginx
listen 80 http2;
```
nginx 1.27-alpine 支持 plaintext h2c。

**备选**: 如环境不支持 h2c，可添加自签名证书并 `listen 443 ssl http2` + 80 端口重定向。

---

### 6. nginx WMS 瓦片 proxy_cache

**文件**: `deploy/nginx/default.conf` (第47-64行)

**问题**: `/geoserver/` 块无任何缓存，相同瓦片穿透到 GeoServer 重复渲染。

**方案**: 在 server 块外新增 `proxy_cache_path`，在 `/geoserver/` location 内启用缓存：
```nginx
proxy_cache_path /var/cache/nginx/geoserver levels=1:2 keys_zone=geoserver_cache:10m max_size=10g inactive=24h;

# 在 location /geoserver/ 内：
proxy_cache geoserver_cache;
proxy_cache_key "$scheme$request_method$host$request_uri";
proxy_cache_valid 200 302 1h;
proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
proxy_cache_background_update on;
proxy_cache_lock on;
proxy_cache_lock_timeout 5s;
# 跳过 GetCapabilities（不缓存动态元数据）
set $skip_cache 0;
if ($args ~* "REQUEST=GetCapabilities") { set $skip_cache 1; }
proxy_cache_bypass $skip_cache;
proxy_no_cache $skip_cache;
```

---

### 7. 静态资源缓存头

**文件**: `deploy/nginx/default.conf` (第66-68行)

**问题**: 无 `Cache-Control`/`Expires`，每次页面加载都重新验证 JS/CSS 资源。

**方案**: 新增 location 块区分带哈希资源与 index.html：
```nginx
location ~* \.(?:js|css|svg|woff2?)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}
location / {
    try_files $uri $uri/ /index.html;
    add_header Cache-Control "no-cache, must-revalidate";
}
```

---

## 中等优先级（后端/GeoServer 侧，直接减少瓦片响应时间）

### 8. 导入后创建 PostGIS 空间索引 + ANALYZE

**文件**: `backend/app/services/importer.py` (第394-395行附近)

**问题**: `ogr2ogr` 导入后不创建 GiST 空间索引也不运行 ANALYZE，GeoServer WMS 渲染对每张表顺序扫描。

**方案**: 在 `_import_vector_layers` 方法中，`db.add(layer)` 之后添加：
```python
db.execute(text(
    f'CREATE INDEX IF NOT EXISTS idx_{safe_name}_geom '
    f'ON geo."{table_name}" USING GIST (geom)'
))
db.execute(text(f'ANALYZE geo."{table_name}"'))
```

---

### 9. 标准导入自动启用 GWC 瓦片缓存

**文件**: `backend/app/services/importer.py` (第148-165行附近)

**问题**: `GeoServerClient.ensure_gwc_layer()` 已完整实现但从未在 `importer.py` 中调用。标准导入的图层无 GWC 缓存。

**方案**: 在 `process()` 方法的 GeoServer 发布成功后，对 S-57 空间图层调用：
```python
try:
    self.geoserver.ensure_gwc_layer(
        layer.geoserver_layer_name or layer.code,
        gridsets=["EPSG:3857", "EPSG:4326"],
        mime_formats=["image/png"],
    )
except Exception:
    logger.warning("无法为图层 %s 启用 GWC", layer.code)
```

---

### 10. GeoServer JVM 调优

**文件**: `deploy/compose.yml` (第20-35行)

**问题**: GeoServer 服务无任何 JVM 参数，默认堆极小，瓦片渲染频繁 GC 停顿。

**方案**: 添加 environment 变量：
```yaml
INITIAL_MEMORY: "2G"
MAXIMUM_MEMORY: "4G"
JAVA_OPTS: "-server -XX:+UseG1GC -XX:+UseStringDeduplication
  -XX:MaxGCPauseMillis=200 -XX:+ParallelRefProcEnabled
  -DGEOSERVER_CSRF_DISABLED=true"
```

---

## 低优先级（增量改进）

### 11. EPSG:3413 GWC GridSet 创建

**文件**: `backend/app/services/geoserver.py` (第316-343行已存在 `ensure_gridset` 方法)

**方案**: 在 GeoServer 启动初始化脚本中调用 `ensure_gridset("EPSG:3413", ...)` 为北极投影启用瓦片缓存。

### 12. GeoServer httpx 客户端连接池

**文件**: `backend/app/services/geoserver.py` (第18-43行)

**方案**: 将 `httpx.request()` 替换为共享的 `httpx.Client` 实例，复用 TCP 连接。

### 13. SLD 样式 MinScaleDenominator

**文件**: `backend/app/services/s57_styles.py` (第32-42行)

**方案**: 在 `render_sld()` 中根据对象类添加 `MinScaleDenominator`，与前端 `DEFAULT_SCALE_HINTS` 保持同步。

---

## 执行顺序

| 步骤 | 改动 | 影响区域 | 预估工作量 |
|------|------|----------|-----------|
| 1 | 暖机/激活/附加预算常量调整 | 仅前端 | 极小（3行） |
| 2 | Set 状态 shallowRef | 仅前端 | 小（7处 import 改动） |
| 3 | WMS 图层动态 zIndex | 仅前端 | 小（~25行） |
| 4 | tileLoadFunction 重试 | 仅前端 | 中（~40行） |
| 5 | nginx HTTP/2 | 基础设施 | 小（1行配置） |
| 6 | nginx proxy_cache | 基础设施 | 小（~20行配置） |
| 7 | 静态资源缓存头 | 基础设施 | 极小（~10行配置） |
| 8 | PostGIS 空间索引 | 仅后端 | 小（~5行） |
| 9 | GWC 自动启用 | 仅后端 | 小（~10行） |
| 10 | GeoServer JVM 参数 | 基础设施 | 极小（compose.yml） |
| 11 | EPSG:3413 GWC GridSet | 仅后端 | 极小 |
| 12 | GeoServer 连接池 | 仅后端 | 小 |
| 13 | SLD MinScaleDenominator | 仅后端 | 中 |

---

## 关键文件清单

| 文件 | 改动类型 |
|------|----------|
| `frontend/src/views/MapWorkspaceView.vue` | tileLoadFunction 重试、zIndex 管理、shallowRef、自适应预算 |
| `frontend/src/utils/mapLayerBatch.ts` | 调度器常量调整 |
| `deploy/nginx/default.conf` | HTTP/2、proxy_cache、静态资源缓存头 |
| `deploy/compose.yml` | GeoServer JVM 环境变量 |
| `backend/app/services/importer.py` | PostGIS 空间索引、GWC 自动启用 |
| `backend/app/services/geoserver.py` | 连接池（低优） |
| `backend/app/services/s57_styles.py` | SLD 缩放规则（低优） |

---

## 验证方案

1. **瓦片重试验证**: 在浏览器 DevTools Network 面板中模拟 GeoServer 返回 503 错误，确认瓦片自动重试
2. **zIndex 验证**: 批量加载 30+ 图层后拖拽地图，确认不再出现图层闪烁
3. **HTTP/2 验证**: DevTools Protocol 列确认请求使用 h2 协议
4. **proxy_cache 验证**: 第二次访问相同区域时瓦片请求返回 X-Cache: HIT 头
5. **空间索引验证**: `\di geo.*` 确认 GiST 索引存在，`EXPLAIN ANALYZE` 确认 Index Scan
6. **端到端验证**: 批量导入 50 个 S-57 图层后，在 smart 模式下拖拽/缩放地图，确认无卡顿、瓦片加载正常
7. **回归验证**: 确认三种渲染模式(standard/smart/overview)切换正常、批量加载确认对话框正常、图层选中/取消正常
