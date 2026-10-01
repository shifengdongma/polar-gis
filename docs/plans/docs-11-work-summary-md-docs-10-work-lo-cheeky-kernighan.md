# 海冰冰情图层嵌入 Polar-GIS — 实施计划（任务书 48 节 + 三仓审计结论）

## Context（背景与目标）

把参考项目 `polar-gis-ice-viewer` 的**冰情数据能力**（NetCDF → FastAPI → PNG XYZ → OpenLayers TileLayer）移植进 `polar-gis` 主系统，作为**独立环境叠加模块**：冰情**绝不进入** S-57 状态机（runtimeLayers / selectedLayerIds / Bundle / mapRenderScheduler / mapTileMerger / TileRequestQueue / GWC），**不创建第二个 Map**，**不迁移**参考项目的临时 GeoPackage 底图与整套 App.vue 外壳。核心原则一句话：**移植冰情数据能力，不拼接两个 WebGIS 应用**。

**基线**：分支 `master`，HEAD `593b8da`；工作区仅有未跟踪：任务书 md、`sample-data/`（945MB，149 个 .nc）、`sample-data.7z`（后两者计划中加入 .gitignore，绝不入库）。

**真实数据已就位**（用户提供，已核验）：`F:\polar-gis\sample-data\sample-data\sic_modis-aqua_amsr2-gcom-w1_merged_nh_1000m_YYYYMMDD.nc` ×149（2022-01-01 起逐日），变量 `sic_merged`（units=`Percentage`）、Hughes 椭球极射赤面投影（EPSG:3411，网格以极点为中心对称，`GeoTransform` 左上 ≈ ±2.66e6/±2.26e6 m，~1 km 像元），**无厚度变量**（厚度缺失是任务书要求的正常状态）。参考仓库 `F:\polar-gis\polar-gis-ice-viewer` 本地存在（其 .venv 绑定他机 uv Python，不可用，仅作源码参考）。

## 一、审计结论（任务书 13 问速答）

| # | 问题 | 结论 |
|---|------|------|
| 1 | Map 在哪里创建 | `MapWorkspaceView.vue` `buildMap()` L742-802：`new OlMap({ target: mapTarget.value, layers, view })`（模块级 `let map`，非响应式；`<div ref="mapTarget" class="map-canvas">` L2649） |
| 2 | EPSG:3413 注册 | 同文件 L536-538 模块级：`proj4.defs('EPSG:3413', '+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +datum=WGS84 +units=m +no_defs')` + `register(proj4)` + `setExtent(±4194304)`；**3411 全仓库无定义**（前端需在 `mapIce.ts` 补 Hughes 定义） |
| 3 | switchProjection 生命周期 | L1301-1339：renderGeneration++ → 快照 selectedLayerIds → detach 全部 WMS → disposeAllBundles → tileQueue.abortAll + tileCache.clear → 切 currentCrs → applyBaseMapVisibility → setView(新View) → fitProjectInitialExtent → `reloadAisGeometry()` → `routeDrawing.reloadRouteGeometry()` → `syncMeasureForProjection()` → 重挂 S-57 → reconcileRenderPlan。**冰情在 `syncMeasureForProjection()` 后新增独立一步 `iceOverlay.reloadForProjection()`** |
| 4 | S-57 RuntimeLayer/Bundle/GWC 生命周期 | `attachRuntimeGroups` / `detachWmsLayer` / `disposeAllBundles` / `mapRenderScheduler.reconcile`（L1423-1499）/ `mapTileMerger`——冰情全部不触碰 |
| 5 | zIndex | 底图 0；S-57 WMS 10-40（`layerZIndex()` L815-824）；routeLayer **95**；measure **100**；AIS **110**。冰情取 **concentration 60 / thickness 62**（占用空档 41-94，海图之上、航路之下），**不修改任何现有 zIndex** |
| 6 | pointermove 消费者 | 唯一一处 `map.on('pointermove')`（L767）：写状态栏坐标 + rAF 合帧经纬度悬停提示（`flushHover` 在 `routeFlyout` 打开时隐藏）；另有 `pointerleave`→`hideHover`、`singleclick`、`moveend`、`postrender`（仅浮窗打开时） |
| 7 | 截图/打印取 canvas | `captureMap()` L2252：`mapTarget.querySelectorAll('.ol-layer canvas')` 逐层合成——**任何 `map.addLayer` 的 TileLayer 自动进截图**（冰情天然满足）；`printMap()` = `window.print()`，`.map-overlay-root/.layer-panel` 打印隐藏 |
| 8 | 环境叠加入口 | `.layer-panel-footer` 的 el-dropdown（L2633-2645）：`handleOverlayCommand('ais')` → `toggleAis()`；badge `overlay-menu-count` 现为硬编码 "1" |
| 9 | 参考如何读 NetCDF | `netCDF4.Dataset` 上下文管理；x 取 `x|lon|longitude`、y 取 `y|lat|latitude`（**要求 1-D 坐标轴**）；`variable[:]` 整读；别名表 FIELD_ALIASES；`masked→NaN` |
| 10 | 如何生成 PNG 瓦片 | `_png()`：`half=4194304`(3413)/`π·6378137`(3857)，瓦片原点左上，256 像素中心批量 pyproj 变换 → 3411 网格最近邻（np.interp 求小数索引 + rint）→ 调色板逐通道线性插值（含 alpha）→ Pillow RGBA PNG（optimize=True）；NoData 与值 0 均 alpha=0 |
| 11 | 3411 → 3413/3857 | **显式经 WGS84 中转**（3411↔4326↔显示投影），绝不把 3411 米坐标当 3413；3857 加 ±85.05112878° 纬度钳制 |
| 12 | 时间轴数据来源 | `info.dates` = 实际存在文件名 `(\d{8})\.nc$` 的集合，数组索引步进，**绝不按 date±1 计算** |
| 13 | hover 为何查原始 NetCDF | 颜色是展示映射不可逆（NoData 透明、0% 透明、alpha 叠加），必须回源查原始网格值——保留此契约 |

## 二、关键设计决策（含 Plan agent 实证验证）

1. **鉴权：ice 全部端点不设鉴权依赖**（首个无鉴权数据 API，需在 docs/09 明写理由）：OL `XYZ` 原生 `<img>` 请求无法携带 Bearer；生产地图瓦片（/geoserver 经 nginx）本就无鉴权；后端只在内网 `internal`，唯一入口是 web/nginx；任务书 §38 明确允许"与现有地图瓦片相同的只读访问边界"，且其 curl 验证示例假定免登录。保留 `ICE_ENABLED` 熔断 + 只读 + `Cache-Control: private, max-age=300`。**CORS**：XYZ 源必须 `crossOrigin:'anonymous'`（与全部现有源一致，否则 dev 跨域下截图合成失效），API 测试加 CORS 冒烟断言。
2. **Nginx `.png` 正则陷阱（必修）**：`location /api/`（前缀）会输给 `location ~* \.(png|jpg…)$`（正则）→ 瓦片 URL 被当作 SPA 静态资源。修复：`location ^~ /api/`。**验证顺序：先经 nginx 复现故障（返回 text/html），再验证修复后返回 image/png**；随后回归 登录/refresh/项目/S-57/demo。路由保留 `.png` 后缀（任务书主推方案）。
3. **后端起服务 `services/ice.py`**：`class IceService`，Settings 注入（`root/tile_cache_entries/max_zoom`）。
   - **懒工厂** `get_ice_service()`（双重检查模块全局，**不用 lru_cache、不用 Depends**——便于 `monkeypatch.setattr(ice_api, "get_ice_service", …)`，与 `test_gwc_backfill.py` 打补丁惯例一致）；**transformers 在 `__init__` 构建**（导入期绝无 PROJ/数据目录耦合 → 冰情失败≠应用失败）。
   - **线程安全（实证）**：pyproj 3.x `Transformer` 内部 thread-local（每线程独立 PROJ context），8 线程×200 变换实测一致 → **共享、不加锁**（禁止 `set_use_global_context(True)`）；netCDF4/HDF5 非线程安全 → **单个 RLock 只护 Dataset 访问与缓存变更**；numpy/PIL/pyproj 计算**一律在锁外**（修复参考实现"渲染在锁内"的性能缺陷）。数组读取后已脱离 HDF5 缓冲（实证可安全跨线程使用）。
   - **缓存**：tile 缓存 LRU（插入序 dict，命中重插，cap=`ICE_TILE_CACHE_ENTRIES`=256）；**价值网格按日期缓存**（一次 Dataset 打开读该日期全部字段，cap 2 日期 LRU，float32）；文件索引存 `(path, mtime, size)`，`info()` 时重扫 + 对 (mtime,size) 变化逐日期失效 metadata/grid/tile（原子换 dict）。
   - **归一化唯一 helper**（修复参考实现 value_at 与 _render 的单位不一致 + `np.ma.filled(np.asarray(...))` 丢 mask 的 NoData 缺陷）：`concentration`：有效域 **0≤v≤100（0 是有效值）**，127/101/255/NaN/<0/>100 → NoData；`thickness`：mask 感知 + `_FillValue`/`missing_value` 哨兵置 NaN，`cm→÷100`、`mm→÷1000`、**未知单位不猜测**（原样，注释 + 一次性日志）。hover 与瓦片共用同一网格加载路径 → 数值不可能漂移。
   - 服务直接 `raise AppError`（house convention 实证）；错误码常量 `ICE_*`。
4. **API `api/ice.py`**（`APIRouter(prefix="/ice", tags=["ice"])` → `/api/v1/ice`）：`GET /info`、`GET /value`、`GET /alignment`、`GET /{field}/{projection}/tile/{z}/{x}/{y}.png`。响应 **camelCase**（`ApiModel` + to_camel，实证遵循主仓库序列化规范）：`IceInfoRead{ dates, fields[{id,name,label,units,available,availableDates}], defaultDate(=dates[0] 最早日期), source="netcdf"(不泄露路径), sourceCrs="EPSG:3411", extent(3411 米), missingDatesAreExcluded }`；`IceValueRead{value 首字段,…}` + `response_model_exclude_unset=True` → **miss 精确返回 `{"value": null}`(200)**（锁定测试）。`value` 用 float（不学参考 `int()` 截断，如实记录偏差）。状态码表：malformed → 422（框架）；未知 field/projection/日期/z>max/x≥2^z → 404（AppError 码）；/value 的未知日期/无变量/范围外/极点钳制 → **200 null**（参考实现契约，时间轴快速拖动时不产生噪音）。`z: int = Path(ge=0)`，上限在服务内校验（`ICE_TILE_MAX_ZOOM` 可配）。`value` 增加可选 `field` 参数（默认 concentration，防未来厚度 hover 破坏性变更）。
5. **前端结构**（全 `ice-` 前缀 class）：
   - `types/index.ts` 增冰情段（camelCase，与后端序列化一致）；`api/ice.ts`（三函数，命名/风格 mirror projects.ts）；`utils/mapIce.ts` 纯函数：`EPSG:3411` proj4 注册（Hughes: `+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +a=6378273 +b=6356889.449 +units=m`，与 pyproj EPSG:3411 一致）、`createIceTileGrid(crs)`（3413: extent ±4194304, tileSize 256, maxZoom 10, origin 左上；3857: 标准 extent）、`buildIceTileUrl(field,crs,date)`、`iceFieldAvailable(info,field,date)`、`formatIceDate`、`projectIceExtent`（3411 米 → 当前 CRS）、`isIceValueValid`（**0 有效**）、`iceTimelineIndex`/`stepIceDate`（数组索引边界），以及**调色板常量**（与后端 PALETTES 逐值一致，前后端测试各自锁定同一组色值 + 注释互指）。
   - `composables/useIceOverlay.ts`（getMap/getCrs/canQueryValue 注入）：`info/loading/error/selectedDate/浓度/厚度 visible+opacity/hover/debugAlignment` 状态；`attach()` 幂等（多次调用不重复建层）；`dispose()` 彻底（removeLayer+dispose+摘监听+abort 在飞请求）；**日期切换只 `layer.setSource(new XYZ(...date))`，不重建 layer**（旧 source 自然 GC；URL 含日期防浏览器错缓存；`transition: 0`）；**`reloadForProjection(crs)` 保留 selectedDate/visible/opacity，只换 source+TileGrid+projection**；hover：**100ms debounce + AbortController + 请求代次号**，拖图/图层关/无日期/日期无该字段/离开地图/其他交互(`canQueryValue`)/组件销毁 一律停止，**客户端 extent 预筛**范围内才发请求；alignment 调试层（VectorLayer 黄点，默认关，面板"高级/调试"）。
   - 组件：`IceLayerPanel.vue`（浓度/厚度开关 + 透明度滑杆 + "当前日期无厚度变量"禁用态 + 当前日期 + 图例（渐变与后端色值一致）+ 定位冰区 + 调试开关 + 免责声明）；`IceTimeline.vue`（`info.dates` 索引驱动，prev/next 边界禁用，`n / N 个可用日期`，只显示日期不构造文件名；**让位随面板折叠**：由视图传入 left/right offset（左折叠 16 / 展开 ~300px；右折叠 16 / 展开 540px），不固定写死）；`IceValueTooltip.vue`（`海冰浓度：65% / 2022-01-01 / 经度…纬度…`，定位与 `.map-hover-coord` 同模式）。
   - **hover 优先级**：航路浮窗/测量/识别/气象/绘制编辑 → 暂停冰情查询；冰情 tooltip 显示期间隐藏经纬度提示（`flushHover` 增加条件）；不出现三浮窗同屏。鼠标位于数据范围内但值为 NoData → 冰情不显示，经纬度提示回退生效。
   - **视图集成（最小侵入）**：`switchProjection` 内加 `iceOverlay.reloadForProjection()`；现有唯一 `pointermove` 里调 `ice.handlePointerMove(event)`、`pointerleave` 调 `clearHover()`；环境叠加 dropdown 增「冰情信息」项（打开/收起 IceLayerPanel，state 文案）；mount 时 `loadInfo()+attach()`，unmount `dispose()`；`.map-status` 不计入冰情瓦片（不进 PerLayerStats/TileRequestQueue——OpenLayers 自管 XYZ）。
6. **数据与部署**：`data/ice/{.gitkeep,README.md}`（入库）；compose backend 挂载用**可覆盖变量** `- ${ICE_DATA_HOST_PATH:-../data/ice}:/data/ice:ro` + `ICE_DATA_ROOT: /data/ice`（本地 Docker 验证=`ICE_DATA_HOST_PATH=../sample-data/sample-data`，写入 deploy/.env(已忽略)，.env.example 补 `# Ice overlay (optional)` 段）；`.gitignore` 增 `sample-data/`、`sample-data.7z`、`data/ice/*.nc`；**不新增任何服务/数据库/Redis**；worker 挂载与 env 经 YAML 锚点自动获得，无害（不读冰情）。
7. **不迁移清单**：`basemap.py`/`base_map.gpkg`/`/basemap/coastline`/参考 `baseLayer`/参考 `new Map`/参考投影切换 UI/`App.vue` 外壳/`App.vue.js`+`main.js` 陈旧产物/`shapely`（仅 basemap 用）/README 硬编码路径。
8. **提交纪律**：按任务书 —— **本次完成后不自动 commit / push**（与 CLAUDE.md 的自动提交规则冲突时，以本次任务书明确要求为准），提交信息建议在最终报告给出。

## 三、文件变更清单

**新增**：`backend/app/services/ice.py`、`backend/app/api/ice.py`、`backend/tests/test_ice_service.py`、`backend/tests/test_ice_api.py`；`frontend/src/api/ice.ts`、`utils/mapIce.ts`、`utils/mapIce.test.ts`、`composables/useIceOverlay.ts`、`composables/useIceOverlay.test.ts`、`components/IceLayerPanel.vue`、`components/IceTimeline.vue`、`components/IceValueTooltip.vue`、`components/IceTimeline.test.ts`、`components/IceLayerPanel.test.ts`；`data/ice/README.md`、`data/ice/.gitkeep`。
**修改**：`backend/app/main.py`、`backend/app/core/config.py`（`ice_enabled/ice_data_root/ice_tile_cache_entries/ice_tile_max_zoom`）、`backend/app/schemas.py`（Ice* schemas）、`backend/pyproject.toml`（`netCDF4>=1.7,<2`、`numpy>=1.26,<3`、`Pillow>=10,<13`、`pyproj>=3.6,<4`）、`backend/tests/conftest.py`（`ICE_DATA_ROOT`/`ICE_ENABLED` env 前置）；`frontend/src/views/MapWorkspaceView.vue`、`frontend/src/views/MapWorkspaceView.test.ts`、`frontend/src/styles.css`、`frontend/src/types/index.ts`；`deploy/compose.yml`、`deploy/nginx/default.conf`（`^~ /api/`）、`deploy/.env.example`、`backend/.env.example`、`.gitignore`；`docs/09/10/11/12`。

## 四、分阶段实施与门禁（对齐任务书 §43）

| 阶段 | 内容 | 验证门（不过不进下一阶段） |
|---|---|---|
| **0 依赖** | pyproject + `F:\polar-gis\.venv` 安装 4 依赖 | venv `import netCDF4, numpy, PIL, pyproj` 成功；既有 pytest 全绿 |
| **1 后端** | services/ice.py、api/ice.py、schemas、config、main、两个测试文件、conftest | ruff 干净；新测试（任务书 22 项）全绿；**真实数据冒烟**：IceService 指向 sample-data → info 报 149 日期、字段 concentration（无 thickness）；3411→WGS84 转角经纬度合理性校验；tile 返回 PNG 签名 |
| **2 部署** | data/ice、compose 挂载/环境、.env(.example)、**nginx `^~ /api/`** | 先经 nginx 复现 `.png` 故障 → 修复后 `/api/v1/ice/info` JSON + tile `image/png`；`docker compose build backend web` 成功（验证 cp312 轮子，无需新 apt）；up -d 健康 |
| **3 前端底层** | types、api/ice.ts、mapIce.ts、useIceOverlay.ts（attach/dispose） | typecheck 零错误；mapIce 单测绿；既有地图上渲染出冰情瓦片（两条 TileLayer、无 CORS 报错、不上报 S-57 统计） |
| **4 图层 UI** | IceLayerPanel（开关/透明度/图例/禁用态） | 组件源码断言（色值与后端一致、`当前日期无厚度变量`、`ice-` 前缀）；手工开关/透明度 |
| **5 时间轴** | IceTimeline（索引驱动、边界、让位） | 单测边界；手工：连续切 20 次日期后仍 **1 浓度 + 1 厚度 TileLayer**、无永久内存增长、S-57 不重载 |
| **6 Hover** | debounce/abort/代次/原始值/tooltip/优先级 | 单测（防旧响应覆盖）；手工：0% 显示 0%、127/NaN 不显示、无三浮窗同屏 |
| **7 投影与生命周期** | reloadForProjection、alignment、截图/打印、面板折叠让位 | 手工：3857↔3413 保留日期/可见/透明度、图层数不变；截图含 S-57+冰情+航路；打印隐藏 UI |
| **8 测试与文档** | 全量回归（§42 矩阵）+ docs 09/10/11/12 | pytest 全绿、typecheck/test/build 全绿、Docker 健康 + curl；未执行项如实标注"未执行" |

## 五、测试要点

- **后端**（小 NetCDF 在 `tmp_path` 动态生成，绝不提交大 fixture；mask 用 `np.ma`、含 float 哨兵 9.96921e36 与 int 哨兵用例、降序轴用例）：空目录、日期识别/排序、别名（sic_merged 及备选）、跨日期字段并集、0 有效、127/NaN/>100/<0 NoData、thickness cm/mm→m、未知单位不换算、3413/3857 tile、PNG 签名、非法 field/projection/zoom/日期、value_at 原始值（float）、alignment GeoJSON、缓存稳定（同进程两次调用同字节）、CORS 冒烟、ICE_ENABLED=false→404、`/value` miss 精确 `{"value": null}` 锁定。
- **前端**（沿用项目"源码断言 + 纯函数单测"惯例，无组件挂载先例，文档如实说明）：mapIce 纯函数全覆盖（tileGrid 双投影、URL、可用性、索引步进边界、palette 色值与后端逐值锁定、extent 投影）；useIceOverlay/IceTimeline/IceLayerPanel/RouteInfo 同级源码断言（attach 幂等、dispose 移除 layer 与监听、日期切换 setSource 不重建 layer、reloadForProjection 保留状态、ice 不进 runtimeLayers/selectedLayerIds/Bundle/TileRequestQueue、单 pointermove 注册、hover 抑制条件）；MapWorkspaceView.test.ts 增补对应断言。

## 六、验证命令与手工验收

```bash
# 后端（F:\polar-gis\.venv，若缺依赖先 pip install 4 依赖）
cd F:/polar-gis/backend && F:/polar-gis/.venv/Scripts/python.exe -m pytest
# 前端
cd F:/polar-gis/frontend && npm run typecheck && npm test && npm run build
# Docker（deploy/.env 设 ICE_DATA_HOST_PATH=../sample-data/sample-data 做真实数据验证）
cd F:/polar-gis/deploy && docker compose build backend web && docker compose up -d && docker compose ps
curl -s http://localhost:8088/api/v1/ice/info   # 149 日期
curl -sI "http://localhost:8088/api/v1/ice/concentration/EPSG:3413/tile/3/3/2.png?date=20220101"  # image/png
```
浏览器手工矩阵（任务书 §42/45）：登录→工作台→双投影→S-57 单/批量/smart/standard/overview→冰情各组合（S-57+冰、冰+航路/AIS/测量/投影切换/时间轴连切/左折叠/右展开）→截图/打印；**Docker 未运行时如实标注未执行**。

## 七、文档与已知限制

- docs/09 新增"Ice Overlay 架构"节：NetCDF→IceService→PNG XYZ→TileLayer；明写与 S-57 渲染管线彻底解耦、**唯一无鉴权数据 API 的理由**、3411→WGS84→3413/3857 转换链、nginx `^~` 修复；docs/10 会话 #26 工作日志（含参考实现三处缺陷修复记录：锁内渲染、mask 丢失、单位不一致）；docs/11 总结；docs/12 用户手册增冰情使用说明（保留"非认证 ECDIS / 不作为正式导航依据"声明 + 冰情专用声明）。
- 已知限制（如实入档）：nearest-neighbour 平色（不做插值，与 hover 契约一致）；149 文件×149 日期首扫 info 较慢（数百 ms 级，缓存 per-date）；value 网格 float32 缓存 2 日期（~100MB/日期级）；厚度当前数据不可用（禁用态即正确行为，绝不造假数据）；3411(Hughes) 与 3413(WGS84) 椭球差异 ≤ 亚像元级（z10 约 3px 量级，经 WGS84 中转链规避直接误用）。
