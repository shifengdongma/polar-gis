# 11 — 工作总结 (Work Summary)

> 记录每次开发会话的修改内容、实现效果与达成目标
> 最后更新: 2026-10-10

---

## 会话 #27 — 海冰密集度术语修正 + 参考工程目录清理（2026-10-10）

### 修改了什么

- **术语修正「海冰浓度 → 海冰密集度」(34 处)**:后端 `services/ice.py`(FIELD_LABELS + 注释)、`tests/test_ice_service.py`、`tests/test_ice_api.py`;前端 `utils/mapIce.ts`(ICE_FIELD_LABELS)、`utils/mapIce.test.ts`、`composables/useIceOverlay.ts`、`components/IceLayerPanel.vue`(开关名/图例标题/状态文案「当前日期无浓度数据」→「当前日期无密集度数据」)、`components/IceLayerPanel.test.ts`、`types/index.ts`;存活文档 `docs/09/10/11/12` 与 `data/ice/README.md` —— 界面、`/info` 接口 label、hover 浮窗标题全部使用正确译法;英文标识层(字段 id/URL 路径/变量别名)与接口契约零改动
- **删除参考工程目录 `polar-gis-ice-viewer/`**(267 MB;源码级比对确认其能力已全量移植、主系统实现为修复版超集;`main.py`/`basemap.py`/`App.vue` 属任务书明确不迁移的原型脚手架);`.gitignore` 同步移除对应规则
- **docs 10/11 增加会话 #27 记录**;`docs/plans/` 两份计划期文档原文保留(其中 24 处旧术语属冻结历史产物,不做改写)

### 达到的效果

- **术语正确统一**:面板开关、图例标题「海冰密集度（%）」、无数据状态「当前日期无密集度数据」、hover 浮窗「海冰密集度：65%」、`/info` label 与 14 个代码/文档文件全部一致(sea ice concentration 标准译法)
- **项目结构回归标准**:参考工程(独立 git 仓库 + 他机不可用 venv)从项目树移除;其代码从未进入主仓库提交,参考内容仍保留在其独立 GitHub 仓库,可完全恢复
- **零功能影响**:删除仅涉及未被引用的参考目录;后端 214 / 前端 353 测试全部通过,与改动前基线一致

### 验证结果

- 后端 `pytest` **214 passed**(零回归);ruff 触碰文件全净
- 前端 `npm run typecheck` 零错误;`npm test` **353 passed**(20 文件);`npm run build` 成功(既有 chunk 体积警告)
- 全仓库核查:`浓度` 仅存在于 `docs/plans/`(冻结文档,24 处);主仓库本就不含该目录(`git log --all` 为空)
- 提交并推送 `master`;推送后复核远程树无 ice-viewer 任何文件
- 浏览器人工验收项(建议):面板/图例/浮窗直接目视新术语

---

## 会话 #26.1 — 冰情瓦片加载性能修复（2026-10-01）

### 修改了什么

- **`backend/app/services/ice.py`**：`_grid` 改为**按日期单飞装载**（per-date 装载锁 + 双检；并发冷请求只装载一次网格）；新增 `warm_default_grid()`，`info()` 后台守护线程预热默认日期网格
- **`frontend/src/composables/useIceOverlay.ts`**：冰情瓦片改用**自定义 `tileLoadFunction`**，复用与海图相同的 `TileRequestQueue`/`LRUTileCache` 实例（缓存优先 → 限流 fetch → blob）；新增**代次中止**（日期/投影/开关切换即 `abortStaleTileLoads()`）+ 瓦片被 OL 释放（ol10 的 `TileState.EMPTY`）即中止 + 指数退避重试；`dispose()` 同步中止
- **`frontend/src/views/MapWorkspaceView.vue`**：冰情块移位置以注入共享 `tileCache`/`tileRequestQueue`（TDZ 修正）
- 测试：后端 +4（并发单飞×2 / 预热幂等 / info 触发预热）、前端断言更新（+4）；docs 09/10/11 同步

### 达到的效果（修复前后实测对比，经 nginx 真实数据）

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 冷日期 8 张并发瓦片（点开"海冰密集度"的量级） | 每张 6.2–6.8s，**总 7.1s**（8 份重复网格装载互相挤占） | **总 3.06s**，每张延迟一致、无饥饿 |
| `/info` 预热后全新冷瓦片 | ~2.3s | **0.13–0.39s** |
| 时间轴切日期 | 旧请求滞留占用连接/后端线程 → "无法重新加载" | 切日期即**中止上一代全部在飞请求**，新瓦片立即进入限流队列 |
| 请求堆积 | 整视口瓦片无限并发发射，海图/底图被挤占（空白卡顿） | 全局并发上限（与海图共享队列）+ 共享 LRU 缓存，回 pan/开关切换零请求 |

### 验证结果

- 后端 `pytest` **214 passed**（210→214）；ruff 干净
- 前端 `typecheck` 零错误；`npm test` **353 passed**（349→353）；`build` 成功；部署 bundle 已验证包含新加载器
- Docker 重建成功、全栈健康；修复前后对照数据见上表
- 已知特性：容器重启后首次 `/info` 在 Windows bind-mount 上约 12s（此后 0.1s；不影响地图，预热保证首次点击瓦片仍快）
- 浏览器 UI 层观感仍属人工验收项（未执行浏览器自动化）；按任务书仍未 commit/push

---

## 会话 #26 — 海冰冰情图层完整嵌入（2026-10-01）

### 修改了什么

- **后端新增** `app/services/ice.py`（IceService：NetCDF 冰场读取 + PNG XYZ 渲染）、`app/api/ice.py`（`/api/v1/ice`：info/value/alignment/tile）、`tests/test_ice_service.py`（31 用例）、`tests/test_ice_api.py`（11 用例）；**修改** `main.py`（注册路由）、`core/config.py`（`ice_enabled/ice_data_root/ice_tile_cache_entries/ice_tile_max_zoom`）、`schemas.py`（Ice* 响应模型）、`pyproject.toml`（+netCDF4/numpy/Pillow/pyproj）、`tests/conftest.py`（ICE_* 前置）
- **前端新增** `api/ice.ts`、`utils/mapIce.ts`（+22 用例）、`composables/useIceOverlay.ts`（+13 用例）、`components/IceLayerPanel.vue`（+6）、`IceTimeline.vue`（+6）、`IceValueTooltip.vue`（+5）；**修改** `MapWorkspaceView.vue`（视图集成）、`types/index.ts`、`styles.css`（ice- 前缀样式与打印规则）、`MapWorkspaceView.test.ts`（+5 集成用例）
- **部署**：`data/ice/`（README+.gitkeep）；`compose.yml` 只读挂载 `${ICE_DATA_HOST_PATH:-../data/ice}:/data/ice:ro` + `ICE_ENABLED/ICE_DATA_ROOT`；**nginx `location ^~ /api/`**（修 .png 正则拦截）；两个 `.env.example`；`.gitignore`（`sample-data/`、`sample-data.7z`、`data/ice/*.nc` 不入库）
- **文档**：docs 09（新增 §5.14 Ice Overlay 架构 + 文件清单校正）/ 10（会话 #26）/ 11（本节）/ 12（用户手册冰情章节）

### 达到的效果

- **冰情独立叠加层**：海冰密集度 / 海冰厚度两个独立 XYZ TileLayer（zIndex 60/62，海图之上、航路/测量/AIS 之下）直接叠加到**现有**地图工作台——S-57 的 runtimeLayers/Bundle/调度器/TileRequestQueue/GWC 全部未触碰；卸载全部海图、smart↔standard 切换不影响冰情
- **真实数据全链路可用**：149 个真实 NetCDF 文件（2022-01-01…05-31，EPSG:3411 1km 网格）经 nginx 实测 `/info` 149 日期、瓦片 `200 image/png`；时间轴只展示实际存在的日期（数据中 20220131/20220201 缺文件 → 时间轴自然缺两位，绝不补齐）
- **hover 原始值**：100ms debounce + AbortController + 代次号（旧响应绝不覆盖新位置）；值来自后端原始网格（0 显示为 0%，127/NaN 不显示浮窗）；与坐标提示/航路浮窗互斥不叠加
- **双投影正确**：3411 → WGS84 → 3413/3857 显式中转（绝不把 3411 米坐标当 3413）；3857 极点区域透明/拒绝；投影切换保留日期/可见性/透明度，只换 XYZ 源——切 20 次日期后地图上仍只有 1 密集度 + 1 厚度 TileLayer（只换源不重建层）
- **厚度缺失即正确状态**：本数据集无厚度变量 → 面板显示「当前日期无厚度变量」并禁用开关，零假数据
- **修掉参考实现 3 处真实缺陷 + 2 处工程缺陷**：锁内渲染（→ 锁外）、`np.ma.filled(np.asarray())` 丢掩码（→ 显式 getmaskarray+哨兵）、value/render 单位口径分裂（→ 单一归一化）；FIFO 缓存（→ LRU）、静态文件索引（→ info 重扫 + (mtime,size) 失效）
- **印证任务书预判的 nginx 陷阱**：`location /api/` 会输给 `.png` 正则 location（实测旧配置返回 SPA index 的 text/html）；`^~ /api/` 修复后瓦片正确进入 backend，非 API 静态图仍走原 location

### 验证结果

- 后端 `pytest`：**210 passed**（168 基线 + 42 新增）；ruff 触碰文件全净（全库历史 lint 基线未触碰）
- 前端：`npm run typecheck` 零错误；`npm test` **349 passed**（20 文件，291 → 349）；`npm run build` 成功
- Docker：`build backend web` 成功（cp312 轮子无需新 apt）；`up -d` 5 服务健康；经 nginx curl 实测 info/瓦片/value/健康检查全通过
- **未执行（如实标注）**：浏览器 UI 层手工验收（瓦片在页面渲染、开关/透明度/时间轴拖动/hover 浮窗/截图/打印的人工操作确认）

### 已知限制

- 最近邻平色渲染（不做插值，与 hover 逐点口径一致）；首扫 149 文件 info ≈ 0.9s（per-date 缓存，之后增量刷新）
- 价值网格按日期缓存 2 份（float32，量级约 100MB/日期），tile 缓存 256 项 LRU
- 厚度当前数据不可用（禁用态即正确行为）；3411(Hughes) 与 3413(WGS84) 椭球差异经 WGS84 中转链处理，无直接混用
- 冰情路由无鉴权（与地图瓦片同边界，理由见 docs/09 §5.14）；如需收紧需改用 tileLoadFunction 携带凭据（任务书 §38 备选方案）
- **按任务书要求本次未 commit / push**

---

## 会话 #25 — 航路随时点选 + 两侧窗口折叠保障完整地图大屏（2026-10-01）

### 修改了什么

- **修改** `frontend/src/composables/useRouteDrawing.ts`：
  - 删除 `RouteDrawingOptions.isSelectionEnabled`（接口成员 + `pickRouteAtPixel` 内的二次检查）——航路点选不再有任何选择门控
  - 新增可选选项 `getFitPadding?: () => [上, 右, 下, 左]`；`fitRoute` 改用 `options.getFitPadding?.() ?? ROUTE_FIT_PADDING`
  - `ROUTE_FIT_PADDING` 注释改为「两面板均打开时的默认回退」（不再是与抽屉宽度的硬编码耦合）
- **修改** `frontend/src/views/MapWorkspaceView.vue`：
  - `singleclick` 的 `else if (routePanelVisible.value)` → `else`（命中守卫仅剩既有互斥：`interactionMode/measureMode` 与识别/气象优先级）
  - `syncRouteFlyout()` 关闭条件去掉 `!routePanelVisible.value`；`routePanelVisible` 保留在浮窗对账 watcher 中，语义变为「折叠/展开时重算锚点让位（540↔16）」
  - 注入 `getFitPadding: () => [90, routePanelVisible ? 550 : 40, 90, layerPanelCollapsed ? 40 : 420]`
  - 状态栏提示 `v-if` 改为「有可见航路即显示」；工具栏 🧭 tooltip 改为「打开面板绘制/管理航路，地图上随时可点选航路查看详情」
- **修改** 测试：`MapWorkspaceView.test.ts`（重写「面板关闭不可选线」旧语义用例 → 4 条新语义断言）、`RoutePlannerPanel.test.ts`（+1 抽屉关闭按钮守卫）；**新建** `composables/useRouteDrawing.test.ts`（3 用例源码断言）
- **修改** docs 09 / 10 / 11 / 12

### 达到的效果

- **航路随时可点选**：右侧航路面板关闭/折叠后，点击地图上的航路同样能选中并弹出航线信息浮窗；折叠抽屉不再打断查看——已打开的浮窗**保持显示**，仅重新夹取位置（展开抽屉时让位 540px，折叠后 16px）
- **折叠即完整大屏**：左侧图层面板（标题栏按钮）与右侧航路抽屉（× / 工具栏 🧭）折叠后地图完整无遮挡；「定位整条航路」的让位随折叠状态自适应——两侧折叠后占满全屏（原硬编码 550/420 会让航路挤成窄带）
- **可发现性修复**：状态栏「点击地图上的航路可查看详情」提示改为有可见航路即显示——原实现只在面板打开时显示，而面板打开时该提示恰好被 520px 抽屉覆盖，实际几乎不可见
- **零侵入**：Store 与 localStorage payload 版本未改；后端、S-57/海图加载与渲染、AIS、测量、要素识别、气象、截图与投影切换全部未触碰；折叠抽屉仍会结束绘制/编辑（既有行为保留）

### 验证结果

- `npm run typecheck`（vue-tsc -b）：零错误
- `npm test`（vitest run）：15 个文件 **291** 个测试全部通过（284 → 291，净增 7）
- `npm run build`：成功（`MapWorkspaceView` chunk 体积警告为既有问题）
- TDD：6 条新断言先实测 RED（恰为预期失败、均因功能缺失），实现后 GREEN
- **浏览器手工验收项（需可运行的前后端环境，本次未执行）**：抽屉关闭时点选航路、浮窗折叠后保持与重夹取、全屏定位、互斥回归、投影切换重锚定、截图不含浮层

### 已知限制

- 面板打开时状态栏位于 520px 抽屉之下（既有布局），该提示在抽屉打开期间不可见——此时用户本就处于航路面板中，影响可忽略
- 点选优先级不变：测量/要素识别/气象进行中时点击属于当前交互，不触发航路点选（既有互斥语义，界面文案已说明）
- 浮窗/坐标系精度等既有精度声明（近似地表距离、非实际可航里程）不受本次改动影响

---

## 会话 #24 — 测量投影修复 + 航段计算 + 航线浮窗 + 坐标悬停提示（2026-09-25）

### 修改了什么

- **新建** `frontend/src/utils/mapMeasure.ts`：
  - `sphericalRingArea()`——Van Oosterom–Strackee 球面三角形立体角 + 0 号顶点扇形三角化，边按大圆、半径取 `ol/sphere` 的 `DEFAULT_RADIUS`，取环两侧较小侧；**与经度回绕无关、对环绕极点的环同样成立**
  - `projectedToLonLatSafe()`——有限性 → 投影范围（3857 因 `canWrapX()` 为 true 只校验纬度带）→ 纬度范围 → 经度收拢
  - `measureGeometryToDraft()` / `buildMeasureGeometry()`——投影几何 ↔ WGS84 真值（多边形统一去掉/补回闭合点）
  - `formatMeasureResult()` / `hoverDecimalsForGroundResolution()` / `HOVER_MIN_GROUND_RESOLUTION_METERS`
- **修改** `frontend/src/utils/mapRoute.ts`：`METERS_PER_NAUTICAL_MILE` / `formatDistance`(km+NM,短距离兼显 m) / `formatArea`(m²/km²,永不换算海里) / `formatBearing` / `formatLonLat`(显式标注经纬度顺序与方位) / `initialBearing`(初始真方位,[0,360)) / `routeSegments`(航段唯一口径) / `calculateRouteLength` **重写为分段和** / `shiftCoordinateIntoWorldCopy` / `routePointIndexById` / `unwrapLongitudeSequence`；`RouteStyleContext` 增加**可选**高亮 getter + 段/点高亮样式
- **修改** `frontend/src/views/MapWorkspaceView.vue`：
  - 测量:`measureMode`(激活态唯一真值) + `measureDraft`(WGS84 真值);`setMeasureDraft()` 只由真值生成文本;`rebuildMeasureGeometry()` 仅在投影切换时重建;**drawend 里不清 source**(OL 是先派发事件再 addFeature)
  - `syncMeasureForProjection()` 接入 `switchProjection()`(与 AIS/航路同范式);互斥缺口修复(两个 toggle 补 `stopMeasureInteraction()`、`activateMeasure` 关识别/气象/浮窗);测量按钮加激活态
  - 浮层:`.map-overlay-root` 容器 + `RouteInfoFlyout` + `postrender` 重锚定(仅锚点移动时写 ref)+ 生命周期对账 watch
  - 悬停提示:复用 `pointermove` + `requestAnimationFrame` 合帧;`getPointResolution` 地面分辨率门槛;拖动/离开/触控/浮窗打开/销毁时隐藏
  - 可发现性:工具栏 tooltip 与状态栏提示「点击地图上的航路可查看详情」
- **新建** `frontend/src/components/RouteInfoFlyout.vue`：航路名 / 总长(km+NM) / 航路点数 / 起终点坐标 / 可滚动航点表(经度、纬度分列) / 航段块(段号·起终航点·段距离·累计距离·**初始真方位**) / 定位整条航路 / 定位所选航点 / 关闭 / 大圆分段与免责说明。**只读**：无任何写接口，不进入绘制编辑态
- **修改** `frontend/src/components/RoutePlannerPanel.vue`：点表新增「入站航段」「累计」两列(起点显示「—」)、行点击与 `#` 按钮定位航点(排除输入框/按钮)、单位与免责说明、抽屉 440→520px
- **修改** `frontend/src/composables/useRouteDrawing.ts`：`pickRouteAtPixel`(顶点先于航段的视空间命中细节 + 3857 世界副本对齐)、`highlightSegment`、`locateRoutePoint`、`getRouteExtent`、`ROUTE_FIT_PADDING`
- **新建** `frontend/src/types/routePlanning.ts`：任务 D 只读规划结果契约草案(纯类型,零运行时/零 API/零演示数值)
- **修改** `frontend/src/types/index.ts`：`RoutePointRoleRow` + `RoutePointRow` 增加 `inboundLegText` / `cumulativeDistanceText`
- **修改** `frontend/src/styles.css`：浮层、浮窗、坐标提示、航段列与说明样式;指针事件与打印规则
- **修改** 测试:`mapMeasure.test.ts`(新,23)、`MapWorkspaceView.test.ts`(新,18)、`RouteInfoFlyout.test.ts`(新,10)、`mapRoute.test.ts`(+30)、`RoutePlannerPanel.test.ts`(+6)

### 达到的效果

- **修掉一个真实的静默失效**:测量后点「要素识别」原本毫无反应(残余测量 Draw 让 `singleclick` 守卫永久提前 return),现为双向互斥且测量按钮有激活态、可见可退出
- **投影切换不再产生错值**:测量结果由 WGS84 真值生成,**两种投影下文本逐字符相同**(实测 `2642.27 km（1426.71 NM）`);显示几何按新投影重建,绘制中切换会明确提示重新测量
- **面积在极区终于正确**:环绕极点的环原本恒为 0(80°N 环真值 3,874,523 km²),跨 180° 的环原本偏大 17 倍,现分别给出正确值并与解析闭式吻合到 0.001%
- **一处定义、多处引用**:`routeSegments` 同时供给面板两列与地图浮窗,`calculateRouteLength` 是其逐位求和,「分段之和 ≡ 总长」由构造成立
- **地图上可直接读航路**:点选航线弹出浮窗,含总长(km+NM)、航点表、点中航段时的段距离/累计/初始真方位;高亮走样式层,不新增图层与交互,隐藏航路天然不可命中
- **对齐了「专业读图」习惯**:视口足够细时才出现的悬停经纬度提示(明确标注经纬度顺序与方位),门槛按地面分辨率而非 zoom,小数位不细于 1 像素
- **零侵入**:Store 与 localStorage payload 版本未改;后端、S-57、WMS/GWC/Bundle/TileCache、AIS、要素识别、气象、截图、海图批量加载与投影切换全部未触碰

### 验证结果

- `npm run typecheck`（vue-tsc -b）：零错误
- `npm test`（vitest run）：14 个文件 **284** 个测试全部通过（197 → 284，新增 87）
- `npm run build`：成功（`MapWorkspaceView` chunk 体积警告为既有问题）
- **浏览器手工验收项（需可运行的前后端环境，本次未执行）**：
  1. 悬停门槛上下(3857 约 z6@72°N / z8@0°；3413 约 z6 起)、小数位随分辨率变化、拖动与离开隐藏、滚轮后自校正、触控设备不显示
  2. 浮窗:单条/多条/隐藏航路、点航段 vs 点顶点 vs 点空白(只关浮窗不改选中)、边缘翻转、1280×720 下不与 520px 抽屉重叠、定位操作不进入绘制/编辑、投影切换后重锚定且高亮存活、改名/拖拽/删除/隐藏后刷新或关闭
  3. 测量投影切换(进行中 / 完成后两种)、跨 180° 与极点多边形面积
  4. 回归:海图批量加载与卸载、smart/standard、AIS、要素识别、气象、航路 localStorage 恢复、截图(浮层不得进入截图)、平移缩放
- **无法验证的场景**（依赖运行中的后端/GeoServer，不写「全部通过」）：要素识别与气象的端到端接口、真实 S-57 海图渲染与 RenderPlan/bundle 路径、GWC 瓦片缓存、底图/WMTS capabilities、项目切换 API、真实瓦片上的截图合成

### 已知限制

- 面积语义变更:大范围高纬多边形相对旧 `ol/sphere.getArea` 变化 ≤1.76%(小多边形 0.000%),属**刻意的更正**(实现 OL 自称的大圆边语义,与 `getLength` 一致),已在文档与界面文案中说明
- 球面模型本身比 WGS84 椭球测地线偏短 0.28%–0.42%:界面按「近似地表距离」表述,不宣称航海认证精度
- 浮层不进入截图/打印(`@media print` 隐藏)——与既有 `.map-status` 行为一致
- 任务 D 仅有类型草案与接入说明,**当前无任何页面消费**,不含假数据

---
## 会话 #23 — 航路方向标记（2026-09-21）

### 修改了什么

- **修改** `frontend/src/utils/mapRoute.ts`：
  - 新增 `RoutePointRole` 类型 + `routePointRole(points, index)`（**按 seq 判定**：seq 最小者 = 起点、最大者 = 终点、其余 = 途经点）+ `routePointRoleLabel()`（起点 / 终点 / 途经）
  - 新增 `createRoutePointStyles()` 标记工厂：每个航路点一个 `Point` 几何 + 圆形标记；起点绿 `#2e9e4f`（r=7）、终点红 `#e5484d`（r=7）、途经灰 `#8a94a6`（r=4.5）；`CircleStyle` 按角色缓存跨帧复用
  - `createRouteStyle()` 接入方向标记：**起点 / 终点始终显示**，途经点仅选中且非编辑时显示
- **修改** `frontend/src/components/RoutePlannerPanel.vue`：点表新增「说明」列（逐行标出起点 / 途经 / 终点，列标题悬停提示方向规则）；详情区底部新增起点 / 终点图例与「按途经点先后顺序，由起点驶向终点」说明
- **修改** `frontend/src/types/index.ts`：新增 `RoutePointRole` / `RoutePointRow`（点表派生行，不入 Store）
- **修改** `frontend/src/styles.css`：角色标签与图例样式（色值与地图标记逐字一致）
- **修改** 测试：`mapRoute.test.ts`（+16 用例）、`RoutePlannerPanel.test.ts`（+4 用例源码断言，含色值一致性守护）
- **修改** docs 09 / 10 / 11 / 12

### 达到的效果

- **方向一目了然**：地图上绿色圆点 = 起点、红色圆点 = 终点，方向端更大更醒目且**始终显示**（缩远、未选中、编辑中均可见），途经点选中时以小灰点叠加
- **顺序即方向**：方向完全由途经点先后顺序（`seq`）推导，无独立「方向」设置项；面板点表「说明」列与地图标记同源同口径，不会出现标注与图形相反的情况
- **零侵入**：Store 与 localStorage 持久化格式未改动（未新增字段、未升版本号），**旧草稿刷新后自动获得方向标记**；后端 / S-57 / WMS / GWC / Bundle / TileCache / 调度器 / 测量 / AIS 全部未触碰
- **颜色不漂移**：地图标记色与面板 CSS 色值由源码断言绑定，重构时若只改一处会立即测试失败

### 验证结果

- `npm run typecheck`（vue-tsc -b）：零错误
- `npm test`（vitest run）：11 个文件 **197** 个测试全部通过（177 → 197，新增 20）
- `npm run build`：成功（MapWorkspaceView chunk 体积警告为既有问题）
- 浏览器手工确认项（建议）：绘制/批量坐标/拖拽后起点终点标记位置正确、颜色可辨；切换投影后标记仍贴附首末点；编辑拖拽时方向标记不丢失

---

## 会话 #22 — 航路面板交互修复（2026-09-16）

### 修改了什么

- **修改** `frontend/src/components/RoutePlannerPanel.vue`：
  - el-drawer 增加 **`modal-penetrable`**（与 `:modal="false"` 配套）——抽屉 overlay 获得 `is-penetrable` 类后不再拦截指针事件，只有抽屉面板本身可交互
  - 点表列标题标注真实合法范围：`经度(-180~180)` / `纬度(-90~90)`
- **新建** `frontend/src/components/RoutePlannerPanel.test.ts`：源码断言守护关键属性组合（防重构回退）
- **修改** docs 09/10/11/12（会话 #22 记录）

### 达到的效果

- **地图绘制恢复可用**：面板打开状态下可在地图上连续单击加顶点、双击完成绘制
- **拖拽编辑恢复可用**：可拖动选中航路的节点，松开后坐标表双向同步
- **地图平移/缩放恢复正常**：面板打开时地图可正常拖动与缩放，关闭面板后交互自动回到 idle
- **经纬度范围一目了然**：经度 ±180、纬度 ±90 均为真实地理范围，列标题已标明，消除误解

### 验证结果

- `npm run typecheck` 零错误；`npm test` 177 测试全绿（11 文件，新增回归测试 2 用例）；`npm run build` 成功
- 根因由 EP 2.11.5 源码（overlay.mjs mask=false 分支 + el-drawer.css `is-penetrable` 规则）验证，非猜测

---

## 会话 #21 — 前端航路规划模拟（2026-09-16）

### 修改了什么

- **新建** `frontend/src/utils/mapRoute.ts` + `mapRoute.test.ts`（54 用例）：纯 GIS 逻辑模块——坐标校验（空值/非数字/NaN/Infinity/越界）、批量坐标文本解析（逐行错误提示）、点位归一化、跨 180° 经线连续化（仅渲染层）、WGS84⇄投影双向转换、LineString 构建、球面长度、routeId 稳定颜色池、航路样式工厂（普通/选中/编辑三态 + 外描边 + 节点标记）、Feature 构建、extent 平移
- **新建** `frontend/src/stores/routes.ts` + `routes.test.ts`（22 用例）：Pinia Setup Store 持有 WGS84 航路真值；revision 单调计数通知地图同步；localStorage 按 projectId 隔离（`polar-gis:route-drafts:${projectId}:v1`）且全容错解析（损坏 JSON/旧结构/非法坐标一律降级不崩溃）；全部 13 个变更动作统一 touch() 持久化
- **新建** `frontend/src/composables/useRouteDrawing.ts`：1 个 VectorLayer（zIndex 95）+ N 个 LineString Feature；Draw 自由绘制（草图独立 Collection + overlay 抬升）；Modify 拖拽编辑（Collection 限定 activeRoute + 拖拽期间 reconcile 短路）；点击命中测试选中；投影切换全量重建；fitRoute 定位；dispose 清理
- **新建** `frontend/src/components/RoutePlannerPanel.vue`：非模态 440px 抽屉（`:modal="false"`，打开时可同时绘制）——新建/删除/显隐/定位列表、点表编辑（el-input-number 即时校验回退）、添加/删除点、地图绘制/撤销点/取消绘制、拖拽编辑/结束编辑、批量坐标输入（逐行错误提示）、航路长度显示、模拟免责声明
- **修改** `frontend/src/types/index.ts`：追加 RoutePoint / RouteDraft / RouteInteractionMode
- **修改** `frontend/src/views/MapWorkspaceView.vue`（16 处最小侵入）：Compass 工具栏按钮 + RoutePlannerPanel 挂载；routeLayer 加入地图；switchProjection 追加 reloadRouteGeometry；singleclick 增加航路/测量互斥守卫与航路命中选中；activateMeasure / 识别 / 气象入口归零航路交互；onMounted 恢复本地草稿；onBeforeUnmount dispose
- **修改** `frontend/src/styles.css`：航路面板样式块 + print 隐藏
- **修改** `docs/09-system-architecture.md`（§5.11 + 目录树 + 文件清单）、`docs/10-work-log.md`、`docs/11-work-summary.md`、`docs/12-user-manual.md`（§4.3.7）

### 达到的效果

- **经纬度绘制**：表格 / 批量粘贴两种方式输入坐标，修改后地图线路立即更新，非法输入明确提示且不写入 Store
- **自由绘制**：地图连续点击 + 双击完成；撤销点 / 取消绘制；drawend 自动 toLonLat 转 WGS84 落库
- **拖拽编辑**：Modify 只作用于当前选中航路；modifyend 双向同步——地图拖拽 → 经纬度表立即变化，刷新页面后修改仍在
- **多航线显示**：单层 N Feature，支持任意多条同显；单条显隐（style function 返回空值）；选中高亮（4.5px + 节点标记）；编辑中虚线区分；routeId 稳定配色
- **缩放/平移**：VectorLayer + View resolution 自然跟随，无 zoom/moveend 重建，0 次 API / GeoServer 请求
- **投影切换**：EPSG:3857 ⇄ EPSG:3413 任意次循环，全部航路从 WGS84 全量重建，位置正确、无残留、无累积误差；跨 180° 经线航路正确渲染
- **本地保存**：按项目隔离持久化，页面刷新自动恢复；损坏数据容错不阻断地图加载
- **对原系统零影响**：S-57 / WMS / GWC / Bundle / TileCache / 调度器 / 测量 / AIS / 截图全部保持原行为；航路层与海图卸载、批量加载、smart↔standard 切换完全解耦

### 验证结果

- 自动验证：`npm run typecheck` 零错误；`npm test` 175 测试全绿（10 文件）；`npm run build` 成功
- 手工验收场景（任务书 1-12）待浏览器验证：经纬度创建、自由绘制、表格修改、拖拽修改+刷新恢复、多航路显隐、缩放 5+5、拖动、投影切换 3 循环、测量兼容、AIS 共存、批量加载/卸载、smart/standard 切换

---

## 会话 #20 — WMS 请求合并修复：去重 + 合并键放宽 + 稳健性修复（2026-08-13）

### 修改了什么

- **修改** `frontend/src/utils/mapTileMerger.ts`：
  - 合并键放宽为 `(serviceUrl, renderTransport)` —— 跨样式/类别全量合并（原键含 styleName/objectClass 导致 S-57 图层几乎一图层一组）
  - 新增 `MergeableLayer` 接口 + `toMergeableLayer()` 适配器（MapLayerConfig 路径复用分组）
  - 新增 `joinLayerParams()`（逐层 STYLES 位置对齐，空位=默认样式）、`globalWmsUrl()`（跨 workspace 全局端点）
  - `effectiveServiceUrl()` 增加 `ENABLE_GWC_TILES` 门控；组内按 (zIndex, sortOrder, id) 排序（GeoServer 自底向上绘制顺序）
  - 多图层组强制普通 WMS 全局端点；单层 GWC 组保留 GWC + VERSION 1.1.1
- **修改** `frontend/src/utils/tileRequestQueue.ts`：队列溢出拒绝最新请求（旧：丢弃最老 → 瓦片永久空白）；`reset()` 不再清零 inFlight（旧：并发瞬时超限）
- **修改** `frontend/src/utils/mapRenderScheduler.ts`：`BundleRenderPlan` 暴露 `bundledLayerIds` 覆盖集
- **修改** `frontend/src/views/MapWorkspaceView.vue`：
  - **smart 模式去重（核心）**：批量加载预取 bundle plan（投影选择集缓存键，与 reconcile 一致）→ bundle 覆盖图层仅登记不建 OL 层 → 挂载后 reconcile 挂 bundle；`executeBundlePlan` 安全网 detach 残留 per-layer（"bundle 胜出"）
  - **合并组生命周期重构**：`registerMergedGroup`/`syncMergedGroup`/`attachRuntimeGroups`/`flushDirtyMergedGroups`；事件闭包迭代 memberIds（支持成员集动态替换）
  - **detach 重建**：组成员移除后微任务合并 `updateParams(LAYERS/STYLES)`——已删图层名不再被请求
  - **重试修复**：重试守卫改为 `attempts < TILE_RETRY_MAX_ATTEMPTS`（严格 2 次尝试）；不可恢复 HTTP / 重试耗尽 / 队列溢出统一 `tile.setState(TileState.ERROR)`（旧：瓦片卡 LOADING 无错误回调）
  - **一致性**：buildMap / 模式切换 smart→standard / switchProjection 全部改用合并组挂载
  - `layerStatusLabel`：bundle 覆盖层显示"已显示"
- **新建** `mapTileMerger.test.ts`（17 用例）、`tileRequestQueue.test.ts`（5 用例）；**更新** `mapRenderScheduler.test.ts`（bundledLayerIds 断言）

### 达到的效果

- **消除请求翻倍**：smart 模式批量加载后，bundle 覆盖图层不再产生单层 GWC 请求——每瓦片从"7 单层 + 3 合并"降为"3 合并"（bundle 数），消除约 70% 冗余请求
- **标准模式合并真正生效**：7 个异样式/类别图层从 7 个单层 GWC 请求合并为 1 个普通 WMS 请求/瓦片（20 层/组分块）；100+ 图层时请求数降一个数量级
- **空白/卡顿治理**：队列溢出不再静默丢弃（ERROR → 下次渲染重取）；错误瓦片不再卡 LOADING（tileloaderror 正常派发）；重试次数精确可控；并发计数在投影切换/卸载后不再瞬时超限
- **一致性**：模式切换/投影切换/初始加载均走合并组，无路径遗漏
- **测试保障**：99 前端测试全绿（+22 新增），vue-tsc 零错误，vite build 成功
- **向后兼容**：`VITE_ENABLE_TILE_MERGING=false` 回退逐层；`VITE_ENABLE_GWC_TILES=false` 时合并组一律普通 WMS

---

## 会话 #19 — WMS 瓦片请求合并（2026-08-10）

### 修改了什么

- **新建** `frontend/src/utils/tileCache.ts`：LRU 瓦片 Blob 缓存（Map 插入顺序 O(1)，2048 entries / 50MB）
- **新建** `frontend/src/utils/tileRequestQueue.ts`：FIFO 并发请求队列（max 16 in-flight，512 queue，支持 AbortSignal）
- **新建** `frontend/src/utils/mapTileMerger.ts`：图层分组合并逻辑（按 serviceUrl/renderTransport/styleName/objectClass 分组，每组共享一个 TileWMS 源，>20 层自动分割）
- **修改** `frontend/src/utils/mapLayerBatch.ts`：新增 7 个 constants + `ENABLE_TILE_MERGING` feature flag
- **修改** `frontend/src/views/MapWorkspaceView.vue`：
  - `createRetryTileLoadFunction`：查缓存 → 走队列 → cache miss 时队列返回 Response → 缓存 Blob
  - `attachWmsLayer`：新增 `sharedSource?` 参数
  - `detachWmsLayer`：处理合并组成员（最后成员离开时销毁共享源）
  - `loadResolvedLayersInBatches`：预分组 → 预创建共享源 → 组级 tile 事件 → 批量附加
  - `onBeforeUnmount` / `switchProjection`：清缓存 + 清队列

### 达到的效果

- **请求数大幅减少**：同一合并组的图层共享一个 TileWMS 源（逗号分隔 LAYERS），HTTP 请求数从 `N层 × 16瓦片` 降为 `G组 × 16瓦片`（G << N）
- **并发可控**：TileRequestQueue 上限 16 并发 fetch()，不再淹没浏览器连接池
- **瓦片缓存**：平移回已访问区域直接命中内存缓存，零网络请求
- **零回归**：77 前端测试全通过，vue-tsc 零错误，vite build 成功
- **向后兼容**：`VITE_ENABLE_TILE_MERGING=false` 完全回退原逐层行为

---

## 补充修复 — GWC 批量加载 400（会话 #18.2，2026-08-10）

### 修改了什么

- `backend/app/api/projects.py` 两处 API 响应构建器（`get_project_dataset_map_layers` 懒加载路径、`_build_resolved_layer` 批量 resolve 路径）将图层名/样式名输出为 **workspace 全限定名**（`polar_gis:s57_c110408a_1_depare` / `polar_gis:s57_depth`）
- `backend/tests/test_projects.py` 对应断言同步更新

### 达到的效果

- **修复**：批量加载图层不再 400，GWC facade 瓦片请求（`LAYERS/STYLES` 带前缀）返回 200 PNG；GWC 缓存链路（会话 #18 的 cacheable 图层 GWC 化）真正可用
- **统一契约**：逐层路径与 bundle 路径（`_build_layer_render_input` 原本已正确）输出一致的 `workspace:name` 全限定名
- **零回归**：普通 WMS 接受全限定名（默认命名空间解析裸名同样兼容）；168 后端测试通过
- 前端无需改动（仅透传后端字段），`s57ObjectNames` 标题归一化兼容前缀

### 遗留注意

- 需重启后端服务使修复生效；此前已发布图层的 GWC 注册表键本就为全限定名，无需迁移
---

## 会话 #18.1 — 最终评审修复（SLD 比例尺方向 + Bundle attach 死锁）

**日期**: 2026-08-10
**状态**: ✅ 完成

### 问题背景

整体评审发现 2 个 Critical + 1 个 Important 缺陷：

1. **SLD 比例尺方向反转（Critical）**：`sync_s57_layer_style` 把 classification 的 `minScaleDenominator` 作为 SLD `MinScaleDenominator` 输出。SLD 规范中 `MinScaleDenominator=25000` 表示"SD ≥ 25000 时渲染"（缩远方向），与"放大到至少 1:25000 才显示 SOUNDG"（SD ≤ 25000 渲染）相反 → 缩远全密度渲染、放大后高密度层消失
2. **Bundle warming 死锁（Critical）**：OpenLayers 不可见 TileLayer 不请求瓦片；`attachBundle` 创建时 `visible: false` → 无 tileloadend → status 永远 'warming' → activate 守卫要求 'active' 才放行 → bundle 永不可见
3. **被 suspend 的 warming bundle 无法恢复可见（Important）**：warming 中 setVisible(false) 会再次冻结瓦片加载

### 修改内容

| 文件 | 修改说明 |
|------|----------|
| `backend/app/services/s57_style_refresh.py` | `sync_s57_layer_style` 改为 `render_sld(max_scale_denominator=min_scale)`——分类的 minScaleDenominator 是"允许渲染的最大 SD"，SLD 方向正确对应 MaxScaleDenominator |
| `backend/app/services/importer.py` | docstring 同步（MinScaleDenominator → MaxScaleDenominator） |
| `frontend/src/utils/mapRenderBundles.ts` | `createBundleTileLayer` `visible: true`（attach 仅对视口内 bundle 发生，无空白风险）；tileloadend 仅做状态迁移 |
| `frontend/src/views/MapWorkspaceView.vue` | activate 守卫放宽：仅拦截 `failed` / `replacing`，warming/active 均放行 setVisible(true) |
| 测试 | test_s57 / test_importer / test_s57_style_refresh（方向断言更新 + 方向锁定测试）；mapRenderBundles.test.ts（attach 可见性测试） |

### 实现效果

1. **SLD 方向正确**：SOUNDG 等高密度图层仅在大比例尺（SD ≤ 25000）渲染，小比例尺自动跳过；放大后不再消失
2. **Bundle 死锁解除**：attach 即可见 → 瓦片立即加载 → warming→active 状态正常迁移，bundle 不再永久不可见
3. **suspend 恢复修复**：被 suspend 的 warming bundle 重新进入视口时恢复可见并继续加载

### 验证结果

- 后端：168 tests passed ✅
- 前端：77 tests passed ✅
- vue-tsc：零错误 ✅
- ruff：触碰文件全部干净 ✅

### 部署注意事项

- SLD 内容从 MinScale 变 MaxScale → **sldHash 变化**（预期）→ 部署后执行 `POST /api/v1/admin/styles/refresh-s57` 让旧图层重发布 + truncate GWC 缓存（幂等，仅 hash 变化的图层触发）

---

**日期**: 2026-08-10
**状态**: ✅ 完成（代码 + 测试；真实 GeoServer 环境端到端验证由用户执行）

### 问题背景

批量加载 160 层海图后，平移地图出现大范围空白、缩放明显卡顿。

### 根因

1. **GWC 缓存全链路未接通**：前端 TileWMS 走普通 WMS（TILED 参数对非 GWC 端点无效）；GWC 只为图层启用 3857/4326 gridset，EPSG:3413 GridSet 从未创建 → 北极投影下瓦片全部直连 WMS 渲染
2. **前端视口裁剪失效**：`s57.extent` 元数据从未写入 → 160 层全部视为"在视口内"，超出活动预算，调度器无法休眠视口外图层
3. **Bundle 生命周期缺陷**：调度器 bundle 分支恒空 TODO → 已挂载 bundle 永不 detach，图层泄漏；renderMode 切换只清不补/只补不清
4. **SLD 无比例尺规则**：所有样式在所有缩放级别渲染
5. **发布 bbox 硬编码全球**：-180..180 使 GeoServer 查询/渲染扫描范围过大

### 修改内容

#### 后端

| 文件 | 修改说明 |
|------|----------|
| `backend/app/services/gwc_backfill.py` | **新建**：`ensure_gridset("EPSG:3413")`（extent [-4194304,-4194304,4194304,4194304]，与 OL 默认瓦片网格对齐）+ `ensure_gwc_layer` 三 gridset（3857/4326/3413）+ `ensure_gwc_3413_backfill()` 幂等纯函数（GET-then-PUT，单层失败仅告警） |
| `backend/app/services/importer.py` | GWC 启用块抽为 `_enable_gwc_caching`（先建 3413 GridSet 再三层 gridset）；`merge_s57_layer_metadata` 写入 `s57.extent` 与 `s57.minScaleDenominator`；`_apply_s57_style` 委托 `sync_s57_layer_style`；`_publish_spec_for_layer` 从 s57.extent 构建逐层发布 bounds |
| `backend/app/services/s57_style_refresh.py` | **新建**：`sync_s57_layer_style`（sldHash sha256 对比，变化才 publish + truncate，幂等零冗余请求）；`refresh_s57_layer_styles` 批量刷新 |
| `backend/app/services/s57_styles.py` | `render_sld` 支持 `min/max_scale_denominator`（Rule 内 Symbolizer 之前；无参输出逐字节兼容） |
| `backend/app/services/geoserver.py` | `publish_feature_type(s)` 支持 `bounds` 参数（`_resolve_bounds` 非法回退全球，发布永不失败）；`truncate_layer_cache` 复活（masstruncate 404 容忍） |
| `backend/app/api/system.py` | 新增 `POST /api/v1/admin/gwc/backfill` 与 `POST /api/v1/admin/styles/refresh-s57` 两个管理员端点（require_admin，幂等） |
| `backend/app/api/projects.py` | 抽取 `_gwc_transport_for_layer` 共享分类；`GET /map-datasets/{id}/layers` 补 cacheable / render_transport / tile_service_url |
| `backend/app/schemas.py` | `MapLayerConfig` 增补 `cacheable` / `render_transport` / `tile_service_url` |
| `backend/app/core/config.py` | 新增 `gwc_3413_backfill`（`GWC_3413_BACKFILL=0` 禁用后台 backfill） |
| `backend/app/main.py` | lifespan 后台线程执行 backfill（不阻塞启动）；注册两个 admin router |

#### 前端

| 文件 | 修改说明 |
|------|----------|
| `frontend/src/views/MapWorkspaceView.vue` | `attachWmsLayer` cacheable 图层切 `/geoserver/gwc/service/wms` + `VERSION: '1.1.1'`（SRS 参数模式）；透传三字段；renderMode watch 双向修复（切 standard 补 attach、切 smart/overview 清残留）；unload 系列补 reconcile；executeBundlePlan activate 守卫 |
| `frontend/src/utils/mapRenderScheduler.ts` | `RenderPlanInput` 增 `attachedBundleIds`；bundle 分支真实四操作（attach/activate/suspend/detach），修复图层泄漏 |
| `frontend/src/types/index.ts` | `MapLayerConfig` 增补 `renderTransport` / `tileServiceUrl` / `cacheable` |
| `frontend/src/utils/mapLayerBatch.ts` | 新增 `ENABLE_GWC_TILES` flag（`VITE_ENABLE_GWC_TILES=false` 回退普通 WMS） |

#### 测试

| 文件 | 修改说明 |
|------|----------|
| 后端 `tests/`（6 个文件 +2 新建） | gwc_backfill 6 用例、merge_s57_layer_metadata 2 用例、GWC 启用 2 用例、map-datasets 端点用例、render_sld 3 用例、样式幂等刷新 10 用例、发布 bbox 18 用例 |
| 前端 `mapRenderScheduler.test.ts` | bundle 分支 5 用例 + detach 兜底 1 用例 |

### 实现效果

1. **GWC 3413 链路全接通**：cacheable 图层瓦片请求走 `/geoserver/gwc/service/wms`（WMS 1.1.1 + SRS），EPSG:3413 GridSet 与 OL 默认瓦片网格对齐 → 平移/缩放重复区域直接命中缓存，不再每次直连 WMS 渲染
2. **视口裁剪真正生效**：`s57.extent` 落库 → 调度器正确休眠视口外图层；发布使用真实数据 bbox，GeoServer 扫描范围大幅缩小
3. **Bundle 生命周期完整**：detach/suspend/activate 真实执行，图层泄漏修复；renderMode 三种模式切换无空白、无残留
4. **SLD 比例尺规则**：高密度图层（SOUNDG 等）仅在大比例尺渲染，小比例尺自动跳过
5. **幂等运维补齐**：已有 160 层可通过 `POST /admin/gwc/backfill` 与 `POST /admin/styles/refresh-s57` 一键补齐，无需重导入
6. **可回退**：`VITE_ENABLE_GWC_TILES=false` 一键回退普通 WMS 行为；`ENABLE_RENDER_BUNDLES` 机制不受影响

### 验证结果

- 后端：167 tests passed ✅（125 → 167，+42）
- 前端：76 tests passed ✅（70 → 76，+6）
- vue-tsc：零错误 ✅
- ruff：本批触碰文件全部干净 ✅（全库 29 处历史 F401 基线未触碰）
- 端到端（curl GWC gridset / X-GWC-Cache 头 / 160 层平移验证 / 回退演练）：**验证方法已写入工作日志，由用户在真实 GeoServer 环境执行**

---

## 会话 #17 — 修复属性表查询失败

**日期**: 2026-08-03
**状态**: ✅ 完成

### 问题背景

所有图层的"查看属性表"功能均报"属性表加载失败"。

### 根因

- DB验证：38,987层的 `allowed_fields` 存储为大写（RCID, PRIM），但 PG 列名为小写（rcid, prim）
- `column_reference(field)` 使用双引号生成 `SELECT "RCID"` → PG 大小写敏感 → "column does not exist"
- 回归来源：commit 441b204 移除 `.lower()` 但无数据迁移
- PG ProgrammingError 未被 AppError handler 捕获 → HTTP 500 → 前端回退消息

### 修改内容

| 文件 | 修改说明 |
|------|----------|
| `backend/app/api/layers.py` | column_reference 移除双引号（使用未加引号标识符，PG 折叠为小写）；新增 normalize_geo_column_names() 工具函数 |

### 实现效果

- 属性表查询恢复正常（已验证：2 items, fields: RCID/PRIM/GRUP/OBJL/...）
- 未加引号 SQL 标识符安全：字段名已由 field_pattern 严格校验，无 SQL 注入风险

### 验证结果

- 后端：125 tests passed ✅
- 端到端：属性表查询成功返回数据 ✅

---

## 会话 #16 — 修复调度器未触发 + 瓦片请求泛滥 + overview死代码

**日期**: 2026-08-03
**状态**: ✅ 完成

### 问题背景

上次修复 warming 排空后仍存在三个问题：
1. 状态面板始终显示"活动0 休眠0 等待0"，智能/标准模式切换无区别
2. 平移地图时底图瓦片大面积空白
3. 批量加载的后面图层移动到相应位置也加载不出来

### 根因

1. **调度器未触发**：批量加载完成后 `reconcileRenderPlan()` 从未被调用。`activeLayerIds`/`suspendedLayerIds`/`warmingLayerIds` 三个 Set 仅由 `executePerLayerPlan` 填充，而 executePerLayerPlan 仅由 reconcile 调用。
2. **连接池饥饿**：`fetch()` 定制 tileLoadFunction 无 AbortController → 平移时僵尸请求堆积；`.catch()` 对所有错误无条件重试 → 雪崩；30层×20瓦片=600并发 → 底图图片加载饿死。
3. **无范围图层永久占预算**：null extent 图层被保守视为"always in viewport"，永久占用30个活动槽位，后续图层永远得不到激活。

### 修改内容

| 文件 | 修改说明 |
|------|----------|
| `frontend/src/views/MapWorkspaceView.vue` | 批量加载完成调用 reconcileRenderPlan()；tileLoadFunction 添加 AbortController + .catch() 仅重试 TypeError 网络错误；setOverviewVisible 从空实现改为实际切换 WMTS 可见性 |
| `frontend/src/utils/mapLayerBatch.ts` | SMART_MAX_ACTIVE_WMS_LAYERS 30→20；新增 SMART_MAX_UNBOUNDED_ACTIVE=10 |
| `frontend/src/utils/mapRenderScheduler.ts` | import/export SMART_MAX_UNBOUNDED_ACTIVE；buildRenderPlan 中增加无范围图层计数和二级预算限制 |
| `frontend/src/utils/mapLayerBatch.test.ts` | 更新常量测试值 |

### 实现效果

1. 批量加载完成后立即看到"活动 N 休眠 M 等待 0"正确统计
2. 视口内图层自动激活，视口外自动休眠
3. 智能/标准模式有明显区别：标准=全开，智能=视口裁剪
4. 无范围图层最多占用10个活动槽，其余按优先级排序
5. 平移时旧瓦片 fetch 立即取消，不堆积僵尸请求
6. 仅网络错误重试（429/502/503/504），404/500 不重试
7. setOverviewVisible 实际切换全球海图概览 WMTS

### 验证结果

- 前端：70 tests passed ✅
- vue-tsc：零错误 ✅

---

## 会话 #15 — 批量加载后优化：warming队列修复 + SOUNDG移除 + UI修复

**日期**: 2026-08-03
**状态**: ✅ 完成

### 问题背景

用户反馈三个问题：
1. 加载100+图层后缩放平移时图层内容切换缓慢甚至失效
2. 批量加载完成后左侧数据集按钮全部关闭，无法看到加载了哪些图层
3. "水深点"(SOUNDG) 在批量"核心图层"加载中不应作为核心指标

### 修改内容

#### 后端

| 文件 | 修改说明 |
|------|----------|
| `backend/app/services/s57_layer_catalog.py` | SOUNDG 从 _CORE_CHART_RULES 移除，添加到 OPTIONAL_THEMATIC；CORE_CHART 自动缩减为 11 个对象类 |
| `backend/tests/test_s57_layer_catalog.py` | EXPECTED_CORE_CHART 移除 SOUNDG；EXPECTED_OPTIONAL_THEMATIC 添加 SOUNDG；更新 display_priority(30→100) 和 display_category(depth→optional_thematic) 断言 |
| `backend/tests/test_map_render_plan.py` | 更新 test_depth_soundg 的 display_category 参数；更新 categories/objects fixture 以匹配新分类 |

#### 前端

| 文件 | 修改说明 |
|------|----------|
| `frontend/src/views/MapWorkspaceView.vue` | 🔴 warming 排空(tileloadend/tileloaderror) + 超时排空(reconcile开场)；数据集加载状态标记；toggleDataset 防重复请求；已加载计数显示；loadProfile 传递；Set 批量更新；Bundle API 缓存 |
| `frontend/src/utils/mapLayerBatch.test.ts` | 修正 SMART_MAX_* 常量测试值（过期 Phase2 值 → 当前值） |
| `frontend/src/utils/mapRenderScheduler.test.ts` | 修复 test26 排序断言以适配 warming=10 |

### 实现效果

1. **warming 队列修复（关键）**：图层首块瓦片加载后自动从 warming 队列移除，后续图层可以正常进入 warming，缩放平移后新图层正常加载
2. **数据集面板**：批量加载后数据集显示"已加载 N 个"，点击展开直接显示图层无需重新请求
3. **SOUNDG 移除**：批量"核心图层"不再加载水深点，SOUNDG 仍可手动单独加载
4. **性能优化**：Bundle API 缓存减少 moveend HTTP 请求；Set 批量更新降低 reactive 开销

### 验证结果

- 后端：125 tests passed ✅
- 前端：70 tests passed ✅
- vue-tsc：零错误 ✅

---

## 会话 #14 — 提高批量加载图层上限至160

**日期**: 2026-08-03
**状态**: ✅ 完成

### 修改内容

| 文件 | 修改说明 |
|------|----------|
| `frontend/src/utils/mapLayerBatch.ts` | `BULK_HARD_LIMIT` 常量从 120 提高到 160 |
| `backend/app/schemas.py` | `MapRenderPlanRequest.layer_ids` 的 `max_length` 从 120 提高到 160 |
| `frontend/src/utils/mapLayerBatch.test.ts` | 测试用例中的阈值从 120/121 更新为 160/161 |

### 实现效果

- 批量加载图层硬限制从 120 提高到 160，允许用户一次性加载更多图层
- 前后端限制保持一致，避免前端通过而后端拒绝的不一致情况
- 确认阈值 (40) 和分批大小 (5) 保持不变

---

## 会话 #13 — Phase 1: 组合图层渲染通道

**日期**: 2026-08-02
**状态**: ✅ 完成

### 问题背景

Polar-GIS 智能模式为每个 S-57 逻辑图层创建独立 OpenLayers TileWMS，30 个活动图层产生 30 × N 个瓦片 HTTP 请求，每个请求触发 GeoServer 渲染任务和 PostGIS 空间查询。首屏瓦片请求过多导致加载缓慢和地图拖拽卡顿。

### 解决方案

建立逻辑图层/渲染图层两层模型：保留逻辑图层的查询、导出、图例、透明度功能不变，在智能模式下将 20~30 个逻辑图层按语义桶（area_fill, line_structure, hazard_detail, navigation_aid, optional_other）压缩为约 3~6 个组合 TileWMS。

### 修改内容

#### 后端 (3 文件)

| 文件 | 变更 |
|------|------|
| `backend/app/schemas.py` | 新增 MapRenderPlanRequest/Response, BundleConfigOut, StandaloneConfigOut, RenderPlanSummaryOut Schema |
| `backend/app/api/projects.py` | 新增 POST /api/v1/projects/{id}/map-render/plan 端点，复用现有 resolve 端点的分类工具函数，调用已有 build_bundles() 纯函数 |
| `backend/tests/test_projects.py` | 新增 6 个 API 集成测试覆盖打包分组、权限拒绝、非空间排除、确定性、空输入 |

#### 前端 (6 文件)

| 文件 | 变更 |
|------|------|
| `frontend/src/types/index.ts` | 新增 RenderBundleConfig, StandaloneLayerConfig, MapRenderPlanResponse 等 6 个类型 |
| `frontend/src/utils/mapRenderBundles.ts` | **新建** Bundle 运行时: 多图层 TileWMS 创建、原子替换、生命周期管理 |
| `frontend/src/utils/mapRenderScheduler.ts` | 新增 BundleRenderPlan 接口、ENABLE_RENDER_BUNDLES Feature Flag、bundle-aware 调度路径 |
| `frontend/src/api/projects.ts` | 新增 fetchRenderPlan() API client |
| `frontend/src/views/MapWorkspaceView.vue` | reconcileRenderPlan() 异步获取渲染计划，新增 executeBundlePlan() 执行路径，toggleLayer/switchProjection/unloadAllChartLayers 增加 Bundle 生命周期管理 |
| `frontend/src/utils/mapRenderBundles.test.ts` | **新建** 11 个 Bundle 单元测试 |

### 实现效果

- 智能模式 Bundle 数量: 30 逻辑图层 → 3~6 组合 TileWMS（预估减少 60-80% 瓦片请求）
- standard 模式: 完全不受影响（bundlePlan 为 undefined）
- overview 模式: 不受影响（仅使用全球概览 WMTS）
- 属性查询: 不受影响（继续使用 PostGIS 直查）
- Feature Flag: `VITE_ENABLE_RENDER_BUNDLES=false` 即可回滚
- 测试覆盖: 后端 44 tests passed + 前端 11 tests passed + TypeScript 类型检查通过

### 已知限制

1. 动态组合 WMS 通过逗号分隔 LAYERS/STYLES 实现，GeoServer 需支持此特性
2. Bundle 内部图层无法单独设置透明度（自动提升为 Standalone）
3. 图层关闭/开启需触发 Bundle 重建（200ms 防抖），非即时响应
4. 稳定组合 Layer Group 策略（Phase 1.2）待后续实现

---

## 会话 #12 — 海图批量加载前端显示性能优化

**日期**: 2026-07-28
**状态**: ✅ 完成

### 问题背景

批量导入一定数量的 S-57 海图图层后，页面出现加载缓慢和地图拖拽/缩放卡顿问题。经全面审查确认前端、基础设施、后端三方面共 10 个核心瓶颈。

### 修改内容

#### 前端优化 (4 项)

| 文件 | 变更 |
|------|------|
| `frontend/src/utils/mapLayerBatch.ts` | 调度器常量调整: SMART_MAX_WARMING_LAYERS 3→10, SMART_MAX_ACTIVE_WMS_LAYERS 20→30, SMART_MAX_ATTACHED_WMS_LAYERS 40→60 |
| `frontend/src/views/MapWorkspaceView.vue` | Set 状态 shallowRef: 7个 ref(new Set()) 改为 shallowRef(new Set()) 减少深层响应式追踪 |
| `frontend/src/views/MapWorkspaceView.vue` | 动态 zIndex: 新增 layerZIndex() 按 S-57 对象类分层 (填充层10→等深线20→岸线25→危险物30→水深点35→助航标志40) |
| `frontend/src/views/MapWorkspaceView.vue` | 瓦片重试: 新增 createRetryTileLoadFunction() 用 fetch+指数退避对 429/502/503/504 及网络错误重试最多 2 次 |

#### 基础设施优化 (4 项)

| 文件 | 变更 |
|------|------|
| `deploy/nginx/default.conf` | HTTP/2: listen 80 http2 突破浏览器 6 连接限制 |
| `deploy/nginx/default.conf` | WMS 瓦片缓存: proxy_cache_path + proxy_cache 指令缓存 GeoServer 响应 1h |
| `deploy/nginx/default.conf` | 静态资源缓存: hashed 资源 Cache-Control: public, immutable (1year) |
| `deploy/compose.yml` | GeoServer JVM: INITIAL_MEMORY=2G MAXIMUM_MEMORY=4G + G1GC 参数 |

#### 后端优化 (2 项)

| 文件 | 变更 |
|------|------|
| `backend/app/services/importer.py` | PostGIS 空间索引: 导入后为每张 geo.* 表 CREATE INDEX USING GIST (geom) + ANALYZE |
| `backend/app/services/importer.py` | GWC 自动启用: 发布后调用 ensure_gwc_layer() 为 S-57 空间图层开启瓦片缓存 |

### 实现效果

- **瓦片重试**: 瞬态网络错误/GeoServer 503 自动恢复，不再出现永久空白瓦片
- **HTTP/2**: 单连接多路复用突破 HTTP/1.1 每源 6 连接限制，20+ 瓦片并发请求不再串行化
- **nginx proxy_cache**: 缓存命中时 0ms 延迟，大幅减少 GeoServer 渲染负载
- **空间索引**: GiST 索引使 GeoServer WMS 查询从 Seq Scan → Index Scan，大表瓦片渲染时间降低数个数量级
- **GWC 自动启用**: 新导入图层自动获得瓦片级缓存，无需手动配置
- **JVM 调优**: 足够的堆空间 + G1GC 减少 GC 停顿，WMS 响应更可预测

### 待完成

- EPSG:3413 GWC GridSet 创建
- GeoServer httpx 客户端连接池
- SLD 样式 MaxScaleDenominator
- 性能测试场景 A-D 验收

## 会话 #1 — 项目初始化与环境配置

**日期**: 2026-07-20
**状态**: ✅ 完成

### 修改内容

#### 新建文件

| 文件 | 说明 |
|------|------|
| `CLAUDE.md` | 项目规范文档: 虚拟环境路径约束、文档维护规则、Git 工作流 |
| `docs/09-system-architecture.md` | 系统架构文档: 完整前后端代码结构、API路由、数据模型、部署架构 |
| `docs/10-work-log.md` | 工作日志文档: 每次会话的任务计划与修改记录 |
| `docs/11-work-summary.md` | 工作总结文档 (本文件): 修改总结与效果评估 |
| `deploy/.env` | Docker Compose 环境变量配置 |

#### 修改文件

| 文件 | 修改说明 |
|------|----------|
| `deploy/compose.yml` | GeoServer 版本降级至 2.25.3 (本地可用); 移除过时 version 字段; backend/worker/web 改用预构建镜像 |
| `backend/Dockerfile` | apt-get 增加 `--fix-missing` 提高网络容错性 |
| `frontend/Dockerfile` | node 版本 22-alpine→20-alpine (适配本地环境) |
| `backend/migrations/versions/0003_project_code_active_unique.py` | 修复索引重复创建错误 (IF NOT EXISTS) |

### 实现效果

1. **项目规范建立**
   - CLAUDE.md 定义了虚拟环境路径约束 (F:\polar-gis\.venv, 禁止C盘)
   - 建立了文档维护规则 (每次修改更新 docs/)
   - 建立了 Git 工作流 (每次更新提交并推送)

2. **系统架构文档**
   - 完整记录 50 个后端文件的目录树与职责
   - 完整记录 29 个前端源文件的结构
   - 列出约 60 个 API 端点和 16 张数据表
   - 描述了 Docker Compose 5 服务部署架构

3. **开发环境就绪**
   - Python 3.12.7 + .venv 虚拟环境 (F:\polar-gis\.venv)
   - 所有后端依赖安装完成 (FastAPI, SQLAlchemy, GDAL等)
   - Node.js v22.14.0 可用

4. **项目成功启动**
   - 5 个 Docker 服务全部运行正常
   - PostgreSQL + PostGIS: port 5432 ✅
   - GeoServer: port 8080 ✅
   - Backend API: 健康检查通过 ✅
   - Worker: 后台导入任务处理 ✅
   - Web 前端: http://localhost:8088 ✅

5. **Git 仓库就绪**
   - 初始提交已推送至 https://github.com/shifengdongma/polar-gis.git
   - 包含 106 个文件, 18,416 行代码

### 关键决策

- **GeoServer 版本**: 因 docker.osgeo.org 不可达, 使用本地缓存的 2.25.3 版本替代 2.26.2
- **镜像策略**: 采用预构建镜像策略 (`docker build` 然后 docker compose up), 避免构建时网络问题
- **迁移修复**: 0003 迁移脚本添加 `IF NOT EXISTS` 防止重复创建索引

### 访问地址

- 前端: http://localhost:8088
- API 文档: http://localhost:8088/api/v1/docs (需要后端直接端口)
- GeoServer: http://localhost:8080/geoserver/
- 默认管理员: admin / 123456 (见 deploy/.env)

---

## 会话 #2 — 修复登录 401 错误

**日期**: 2026-07-20
**状态**: ✅ 完成

### 修改内容

| 文件 | 修改说明 |
|------|----------|
| (数据库 users 表) | 重置 admin 账户锁定状态并更新密码哈希 |

### 实现效果

1. **登录问题修复**
   - admin 账户因多次失败登录被锁定 → 已解锁
   - 密码哈希与 .env 同步 → 登录正常

2. **操作说明**
   - .env 修改不需要重新构建镜像，重启容器即可生效
   - 但修改 admin 密码需要同步更新数据库（因为 ensure_initial_admin 不会更新已存在的用户）

### 访问地址

- 前端: http://localhost:8088
- API 文档: http://localhost:8088/api/v1/docs
- GeoServer: http://localhost:8080/geoserver/
- 默认管理员: admin / 123456

---

## 会话 #3 — 生成用户操作使用手册

**日期**: 2026-07-21
**状态**: ✅ 完成

### 修改内容

| 文件 | 修改说明 |
|------|----------|
| `docs/12-user-manual.md` | 新建完整用户操作使用手册 (约 600 行, 9 大章节) |

### 实现效果

1. **完整覆盖所有功能模块**
   - 前端 10 个页面组件 (登录、项目门户、地图工作台、6 个管理页面) 的操作说明
   - 后端 71 个 API 端点的分类参考文档
   - 数据导入全流程说明 (上传→检查→导入→发布→样式)
   - 地图工作台 6 种工具的使用方法
   - 项目管理完整生命周期 (草稿→发布→归档)

2. **面向多种用户角色**
   - 普通用户: 登录、浏览项目、地图操作、空间查询、数据导出
   - 系统管理员: 用户管理、数据管理、项目配置、系统监控
   - 运维人员: Docker 部署、环境变量、健康检查

3. **实用性强**
   - 常见问题 6 大分类 (登录/数据/地图/项目/性能/安全)
   - API 调用示例 (curl 命令可直接复制使用)
   - S-57 更新链规则说明 (含正误示例)
   - 错误代码速查表
   - 环境变量完整参考
   - 快捷键与操作提示

4. **法律合规声明**
   - 明确标注非 ECDIS 系统声明
   - 标注演示数据 (AIS/气象) 为模拟数据
   - 在手册首页和功能说明中多处提示

### 关键决策

- 手册语言使用中文, 与现有文档和用户界面保持一致
- 不重复已有的设计文档内容, 聚焦于用户操作使用视角
- 代码示例使用 curl 命令, 便于运维和技术用户直接测试

---

## 会话 #5 — 批量导入性能优化 + 暂停/取消功能

**日期**: 2026-07-22
**状态**: ✅ 完成

### 修改内容

#### 修改文件

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `backend/app/models.py` | 枚举扩展 | `JobStatus` 新增 `PAUSED = "paused"` |
| `backend/app/services/importer.py` | 核心优化 | `_import_vector_layers` 重写为临时schema单次ogr2ogr + ALTER TABLE方案；新增取消感知检查点；publish阶段改用 batch publish |
| `backend/app/services/geoserver.py` | 性能优化 | `publish_feature_type` 预设 BBox 跳过GeoServer全表扫描；新增 `publish_feature_types_batch` 批量发布方法 |
| `backend/app/services/s57_batch.py` | 架构重构 | `process()` 使用 ThreadPoolExecutor 并行处理 Cell；`_process_cell_worker` 独立 Session 线程安全；`_finalize_batch` 独立 Session 隔离；暂停/取消检测；可配置并行度 |
| `backend/app/api/datasets.py` | 新增API | pause/resume/cancel 三个批量导入控制端点 |
| `backend/app/core/config.py` | 新增配置 | `batch_parallel_workers` 并行worker数量 (默认8) |
| `frontend/src/views/admin/BatchImportView.vue` | UI增强 | 暂停/继续/取消按钮；新增状态标签 |
| `backend/tests/test_s57_batch.py` | 测试适配 | FakeImportProcessor 适配并行处理；create_batch 返回 session factory |

### 实现效果

1. **性能提升**: 188个S-57单元导入时间从 **10小时+** 预计降至 **5-20分钟**（30-120x 提速）
   - ogr2ogr 调用数: ~7,520次 → 188次 (40x 减少)
   - 新增 `-lco PRECISION=NO` 加速导入
   - GeoServer 发布跳过全表 BBox 计算
   - Cell 并行处理 (默认8 workers)

2. **新增功能**:
   - 批量导入支持**暂停**（完成当前Cell后停止，保留进度）
   - 批量导入支持**恢复**（从断点继续处理未完成的Cell）
   - 批量导入支持**取消**（立即中断，标记剩余项为已取消）

3. **向后兼容**: 
   - 已有数据和图层不受影响
   - 单文件导入流程不变
   - API 接口不变（仅新增端点）
   - 所有 46 个已有测试通过

### 关键决策

- 使用**临时 PostgreSQL schema** 而非管道/批处理文件，避免了复杂的表名映射
- 使用 **ThreadPoolExecutor** 而非 ProcessPoolExecutor（导入是I/O密集型）
- 暂停/恢复通过重置 batch.status 为 QUEUED 实现，复用现有的 claim 逻辑
- Worker 进度跟踪使用独立的 DB session 避免事务隔离问题
- 所有改动保持对 PostgreSQL 生产环境的兼容性

### 重新构建命令（保留现有数据）

```bash
cd F:/polar-gis/deploy
docker compose down          # 停止服务 (不删除 volumes)
docker compose build --no-cache backend worker web  # 重新构建镜像
docker compose up -d         # 启动服务
```

**数据安全**: `docker compose down` 不会删除 named volumes (`postgres-data`, `geoserver-data`, `shared-storage`)，已有数据完整保留。切勿使用 `docker compose down -v`。

---

## 会话 #6 — 项目配置"批量选取"数据集功能

**日期**: 2026-07-22
**状态**: ✅ 完成

### 修改内容

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `backend/app/api/datasets.py` | 新增端点 | `GET /admin/datasets/available-ids` 返回所有可用数据集的轻量级 ID 列表 (id/code/name)，支持搜索过滤 |
| `backend/app/api/projects.py` | 功能增强 | `GET /admin/projects/{id}/dataset-layers` 新增 `search` 查询参数，支持按名称/代码过滤 |
| `frontend/src/views/admin/ProjectManagementView.vue` | UI增强 | 新增搜索框 + 全选本页/取消本页/全选全部/取消全部四个批量操作按钮 |

### 实现效果

1. **搜索过滤**: 输入关键词即时过滤数据集列表，支持名称和代码模糊匹配
2. **全选本页**: 一键选中当前页所有可见数据集
3. **取消本页**: 一键取消当前页所有选中
4. **全选全部**: 通过新端点一次性获取所有匹配数据集 ID，跨页全选（不受分页限制）
5. **取消全部**: 一键清空所有选中状态

### 技术要点

- `datasetDrafts` Map 跨页跟踪选中状态，批量操作直接写入 Map
- "全选全部"走独立的轻量端点 `GET /admin/datasets/available-ids`，只返回 id/code/name 三元组，性能高效

---

## 会话 #7 — 修复图层属性加载失败 + 地图性能优化

**日期**: 2026-07-23
**状态**: ✅ 完成

### 修改内容

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `backend/app/api/layers.py` | Bug修复 | `column_reference()` 移除 `.lower()`，保留字段名原始大小写，匹配PostgreSQL实际列名 |
| `backend/app/services/importer.py` | 增强 | ogr2ogr命令添加 `-lco LAUNDER=YES` 统一小写列名；`allowed_fields` 导入时同步小写化 |
| `frontend/src/views/MapWorkspaceView.vue` | 性能优化 | 图层搜索添加200ms防抖；瓦片加载状态300ms延迟稳定化；属性查询和要素识别添加AbortController请求取消 |

### 实现效果

1. **修复DSID等S-57字段查询失败**: `column_reference()` 不再强制小写，生成的SQL列名与PostgreSQL实际列名一致，DSID/LNAM/AGENCY等所有大写S-57属性字段查询正常
2. **新旧数据兼容**: 旧数据(大写列名+大写allowed_fields)→column_reference保留大写匹配；新导入(LAUNDER=YES小写列名+小写allowed_fields)→同样匹配
3. **消除状态指示灯闪烁**: 瓦片加载添加300ms延迟才显示黄色loading状态，快速加载的瓦片(<300ms)不会触发闪烁
4. **搜索输入流畅**: 图层搜索200ms防抖，避免每次按键触发filteredGroups重建
5. **防止竞态条件**: 属性表和要素识别在发送新请求前取消前一个进行中的请求，避免过时响应覆盖新数据

### 技术要点

- `column_reference()` 移除小写是安全的：字段名已通过 `field_pattern` 正则(`^[A-Za-z_][A-Za-z0-9_]*$`)和白名单(`allowed_fields`)双重校验
- ogr2ogr LAUNDER=YES 确保未来所有导入数据统一小写列名，避免混合大小写的混乱
- 瓦片状态稳定化使用 `window.setTimeout/clearTimeout` 管理定时器，`detachWmsLayer` 中确保清理，防止内存泄漏
- AbortController 通过 `controller.signal.aborted` 检查避免在已取消的请求中更新UI
- 搜索联动：输入变化自动重置到第一页

---

## 会话 #8 — 建立后端 S-57 图层分类事实来源

**日期**: 2026-07-26
**状态**: ✅ 完成

### 修改内容

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `backend/app/services/s57_layer_catalog.py` | 新建 | 后端统一 S-57 图层分类目录、不可变规则与纯函数接口 |
| `backend/tests/test_s57_layer_catalog.py` | 新建 | 精确集合和分类行为测试，共 8 项 |
| `docs/09-system-architecture.md` | 修改 | 补充分类服务边界与数据流定位 |
| `docs/10-work-log.md` | 修改 | 记录 RED/GREEN、lint 与实现决策 |
| `docs/11-work-summary.md` | 修改 | 汇总阶段成果 |

### 实现效果

1. **建立唯一分类事实来源**: 核心海图、航行推荐、可选专题、质量元数据和非空间对象由后端同一目录统一判定。
2. **稳定分类契约**: 每条规则统一输出代码、中文名称、展示分类、加载档案、优先级、推荐/渲染/默认可见状态和排序键。
3. **保持纯函数边界**: 模块不依赖数据库、FastAPI、GDAL 或 GeoServer，可由后续导入与解析 API 安全复用。
4. **修正几何语义**: 仅明确无几何值判为无效，`GeometryCollection` 保持有效；已知 `DSID`、`C_AGGR` 始终不可渲染。
5. **不改变现有地图行为**: 所有规则默认不可见，分类元数据不会提前触发现有图层加载。

### 验证结果

- TDD RED 已确认分类模块缺失时测试按预期失败。
- 目标 pytest: `8 passed`。
- 目标 ruff: `All checks passed!`。

### 审查修复

1. 测试现已直接校验生产 `CORE_CHART`、`NAVIGATION_RECOMMENDED`、`OPTIONAL_THEMATIC`、`METADATA_QUALITY`、`NON_SPATIAL` 与独立规格集合精确相等，并对生产集合执行两两互斥检查。
2. 核心对象成员不再由集合和展示表重复维护；`_CORE_CHART_RULES` 成为单一规范表，公开 `CORE_CHART` 从其键派生。
3. 删除了无消费者的 `_RESTRICTION_HARBOR`，保留航行推荐分类原有兜底语义。
4. 测试移除了本地集合自我比较、重复逐成员唯一性计数及对私有规则表名称的实现耦合，规格期望每组仅保留一份。
5. 架构文档移除易过期的固定测试数量描述。

### 阶段边界

本次仅完成分类目录基础；未接入 importer、API 或前端。后续任务应直接复用该目录，不再复制分类集合。

### 补充修复 — 非空间图层(DSID/C_ASSO)属性表加载失败

**问题**: DSID(数据集元数据)和 C_ASSO(要素关联)等 S-57 非空间图层，`ogr2ogr` 导入时不创建 `geom` 列，后端 SQL 硬编码 `ST_Transform(geom,4326)` 导致 "column geom does not exist"；GeoServer 发布无几何列的表后 WMS 瓦片加载失败。

**修改**:
1. `backend/app/api/layers.py` — 新增 `_layer_has_geometry()` 函数检测非空间图层；`search_features`/`export_features` 对非空间图层使用 `NULL AS geometry`；`identify_feature` 返回 400 错误
2. `backend/app/services/importer.py` — GeoServer 发布前过滤掉非空间图层(geometry_type 为 unknown/none/空)
3. `backend/app/schemas.py` + `backend/app/api/projects.py` — `MapLayerConfig` 新增 `geometry_type` 字段
4. `frontend/src/types/index.ts` + `frontend/src/views/MapWorkspaceView.vue` — 新增 `isNonSpatial()` 判断，非空间图层跳过 WMS 加载显示"属性表"标签

---

## 会话 #9 — S-57 海图图层批量加载与智能筛选

**日期**: 2026-07-26
**状态**: ✅ 完成

### 修改内容

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `backend/app/services/importer.py` | 增强 | 新增 `merge_s57_layer_metadata()`；S-57 导入时合并分类快照到 metadata_json.s57；非空间过滤替换为 has_valid_geometry() |
| `backend/app/schemas.py` | 增强 | 新增 BulkMapLayerResolveRequest/Response 系列 Schema；MapDatasetConfig 增加 dataType；S57ImportBatchItemRead 增加 details |
| `backend/app/api/projects.py` | 新增端点 | POST /map-layers/resolve — 项目级 S-57 图层批量解析，含 profile 筛选和稳定排序 |
| `backend/app/services/s57_batch.py` | 增强 | 新增 S57ChainValidationError 含 missingUpdates；validate_s57_chain() 区分 S57_BASE_MISSING vs S57_UPDATE_GAP；s57_error_details() 提取结构化详情 |
| `backend/app/api/datasets.py` | 增强 | 批次详情 API 填充 details.missingUpdates |
| `backend/tests/test_importer.py` | 新建 | S-57 metadata 合并测试 (7 tests) |
| `frontend/src/types/index.ts` | 增强 | 新增批量解析类型和 BulkLayerProgress |
| `frontend/src/api/projects.ts` | 新建 | resolveProjectMapLayers() 等 API 客户端 |
| `frontend/src/utils/mapLayerBatch.ts` | 新建 | 批量常量、排序/去重/阈值/范围转换纯函数 |
| `frontend/src/views/MapWorkspaceView.vue` | 增强 | 数据集复选框、批量加载下拉菜单、分批创建、取消、三种卸载方式、进度区域 |
| `frontend/src/styles.css` | 增强 | 批量工具栏紧凑深色面板样式 |
| `docs/02,04,05,09,10,11,12` | 修改 | 批量加载功能文档 |

### 实现效果

1. **批量加载能力**: 用户无需展开数据集即可选择 S-57 数据集，一键批量加载核心/推荐/全部海图图层
2. **智能筛选**: 自动跳过非空间层(DSID/C_AGGR)、未发布层、不可用层和未映射样式层
3. **分批节奏控制**: 每批 5 层、批间 200ms，不等待瓦片完全加载
4. **失败隔离**: 单层加载失败不影响其他层
5. **精确卸载**: 三种卸载方式，不影响底图、AIS、气象、测量
6. **旧数据零迁移**: 无 metadata.s57 的旧图层由 API 动态分类回退
7. **更新链诊断**: 区分基础文件缺失与更新间断，提供结构化 missingUpdates

### 验证结果

- 后端: 61 tests passed, ruff clean
- 前端: 22 tests passed, vue-tsc clean, vite build 成功
- 无需数据库迁移

---

## 会话 #10 — 一键导入全球海图底图 (2026-07-27)

### 功能概述
在现有S-57批量导入、GeoServer发布、S-57图层分类和底图管理功能之上，实现一键导入全球海图概览底图。默认选取18个用途等级1(概览)海图Cell共29个文件，通过预检→导入→GeoServer Layer Group→GWC→BaseMap注册的完整流程生成WMTS底图。

### 新增API
- `GET /api/v1/admin/s57-basemaps/profiles` — 列出可用底图profile
- `POST /api/v1/admin/s57-basemaps/preflight` — 预检数据包
- `POST /api/v1/admin/s57-basemaps/import` — 启动一键导入
- `GET /api/v1/admin/s57-basemaps/runs/{batchId}` — 运行状态

### 数据库变更
- `s57_import_batches` 新增 `purpose VARCHAR(32)` 和 `metadata_json JSONB`
- Alembic 迁移: `0004_add_purpose_metadata_to_s57_batches.py`

### Worker 变化
- `_finalize_batch()` 增加 basemap 后处理钩子
- 后处理: 收集图层 → Layer Group → GWC → BaseMap 幂等登记
- 后处理失败不回滚已导入数据，旧底图保持可用

### Layer Group
- 名称: `polar_global_enc_overview`
- 仅包含 core_chart + style_mapped 的图层
- 稳定排序: SEAARE → DEPARE → ICEARE → LNDARE → COALNE → ...

### 前端交互
- BatchImportView 增加底图功能区（预检数据包/一键导入/查看最近任务）
- 预检结果对话框显示18 Cell的创建/更新/跳过/阻塞状态
- 高级选项: 用途等级2区域增强/默认底图/EPSG:3413 WMTS/预热缓存
- 运行详情抽屉显示后处理状态和警告

### 验证结果
- 后端: 87 tests passed (61 现有 + 26 新增)
- 数据库迁移已创建，兼容旧数据
- Profile 配置验证: 18 Cell, 29 文件与文件清单一致

---

## 会话 #11 — 海图批量加载性能优化（2026-07-28）

### 优化目标
解决用户批量选择和加载 S-57 海图数据集后浏览器卡顿、交互响应慢、瓦片长时间空白、部分瓦片加载失败或缓慢的问题。

### 核心成果

#### 根因分析（10 项瓶颈）
1. 无视口裁剪 → 40+ 图层同时请求瓦片，超过浏览器 6 连接/源限制
2. 无比例尺过滤 → 高密度图层在所有缩放级别渲染
3. 无并发控制 → 队头阻塞和超时级联
4. 业务图层未使用 GWC → 每次直接渲染而非缓存命中
5. GeoServer 硬编码全球 bbox → 北极数据扫描范围过大
6. SLD 无比例尺规则 → 所有样式在所有缩放级别渲染
7. 无空间索引 + ANALYZE → 导入后查询计划劣化
8. Nginx 无优化 → 缺少 HTTP/2、gzip、keepalive
9. GeoServer 无 JVM 调优 → 内存和 GC 未配置
10. 投影切换全量重建 → 长时间地图全白

#### 新增文件
| 文件 | 行数 | 说明 |
|------|------|------|
| `frontend/src/utils/mapRenderScheduler.ts` | ~350 | 纯函数渲染调度器 |
| `frontend/src/utils/mapRenderScheduler.test.ts` | ~470 | 32 个单元测试 |
| `docs/plans/polar-gis功能优化提示词.md` | 1068 | 优化需求规格 (28 节) |

#### 前端优化
- **状态分离**: selectedLayerIds / attachedLayerIds / activeLayerIds / warmingLayerIds / suspendedLayerIds / manuallyForcedLayerIds / failedLayerIds 七状态模型
- **智能调度**: `buildRenderPlan()` 视口裁剪 + 比例尺过滤 + warming 预算 (≤3) + active 预算 (≤20) + LRU 驱逐
- **三种模式**: standard (完全向后兼容) / smart (智能调度) / overview (仅概览 WMTS)
- **性能统计**: PerLayerStatsManager 追踪瓦片加载耗时/失败数/P95
- **UI 增强**: 图层状态文字、模式切换、活动/休眠/等待统计、性能详情面板
- **DEFAULT_SCALE_HINTS**: 集中维护 30+ S-57 对象类的比例尺规则，与后端 `_SCALE_RULES` 同步
- **Nginx**: perf 日志格式、gzip、upstream keepalive、缓存头穿透

#### 后端优化
- **GWC 传输提示**: resolve API 返回 `render_transport` (gwc_wms/wms)、`tile_service_url`、`cacheable`
- **比例尺提示**: `_SCALE_RULES` 字典 (SOUNDG minScale=25000, nav-aids minScale=50000 等)
- **S57LayerRule 扩展**: 新增 min_scale_denominator / max_scale_denominator / low_zoom_visible / render_cost
- **向后兼容**: 所有新增 API 字段为可选字段

#### 部署修复
- Dockerfile: 阿里云 PyPI/npm 镜像 + pip timeout 120s
- compose.yml: S-57 底图卷挂载从绝对路径 `/data/s57-basemaps` 改为相对路径 `../data/s57-basemaps`
- Nginx: HTTP/2 支持

#### 测试结果
- **后端**: 87 tests passed (零新增失败)
- **前端**: 59 tests passed (27 已有 + 32 新增)
- **TypeScript**: vue-tsc 零错误
- **Python**: pytest 零错误

#### 关键设计决策
1. 纯函数调度器：buildRenderPlan 无副作用，充分可测试
2. 比例尺规则单源：DEFAULT_SCALE_HINTS (前端) 与 _SCALE_RULES (后端) 保持一致
3. standard 模式 = 完全向后兼容，一键回退到优化前行为
4. LRU 保护清单：底图/WMTS/AIS/气象/测量/选择高亮/编辑图层/属性查询 永不驱逐
5. 保守 fallback：null extent = 视口内，未知 objectClass = 无比例尺限制

#### 待完成（阶段五-六）
- 阶段五: SLD 比例尺规则 (s57_styles.py)、PostGIS GiST 索引 + ANALYZE、EPSG:3413 GWC GridSet、GeoServer JVM 调优
- 阶段六: 性能测试场景 A-D 验收、回归测试、文档更新
- 可选: 低缩放简化视图 (ST_SimplifyPreserveTopology)

---

## 会话 #28 — PolarOptionNav-System-V3 导航集成 / 批次 A（2026-10-29）

### 做了什么

- 完成 `docs/plans/v3-integration-audit.md`：明确 V3 六类功能状态（可运行/未接真实数据/
  API 未接 UI/UI 占位/仅文档/缺失），列出可直接复用、必须重构、不可迁移文件与数据缺口。
- 建立 `backend/app/navigation/` 业务域基座：坐标/方向/时间/单位/质量/证据/可行性契约；
  雪龙2 静态资料、25km NEP 静态网格、风险权重版本文件。
- 新增导航配置与测试临时数据根；`.gitignore` 隔离 V3 嵌套仓库。
- 锁定测试基线：后端 214 passed、前端 353 passed。

### 效果

- 后续环境/船舶/风险/规划代码有唯一落点，不再出现 V3 根级 `core/`/`services/` 第二套体系。
- `TimeMatchInfo`/`DataQuality`/`FeasibilityStatus` 为“缺测≠0、未知≠安全”提供类型级约束。
- 合成数据与真实数据通过 manifest quality 区分，`real_only` 可拒绝合成文件。
- 现有 S-57/海冰/手绘航路/认证行为零改动。

### 已知限制

- 本批次尚无实际环境 Provider、API、数据库迁移或前端图层；B-E 批次完成。
- 本机无真实 GEBCO/neXtSIM/CARRA2/TOPAZ5/WAM 数据，最终 E2E 只能使用明确标注的合成数据。
- Polar-GIS 无项目成员 ACL；规划权限沿用“已发布项目 + 认证”，取消限 requester/admin。
- 既有 `ruff` 29 个历史错误未修复（与本任务无关），新增导航代码已单独通过 lint。

---

## 会话 #28 — 批次 B：环境感知与船舶模型（2026-10-29）

### 做了什么

- 实现五类环境 Provider：GEBCO 水深、海冰（IceService/neXtSIM）、CARRA2 风、TOPAZ5 流、WAM 浪；
  统一 `available/times/sample/sample_many/close` 与故障隔离。
- 引入 `navigation_manifest.json` 质量标记：合成测试数据必须标 `synthetic`，`real_only` 拒绝；
  无 manifest 时按真实文件 `real`，issue/observation 时间仍可为 unknown。
- 时间语义：默认 latest-not-after、issue≤requested、按源 max-lag；研究模式才 nearest；
  每字段返回 requested/matched/valid/issue/quality，不把未来预报冒充历史分析。
- 船舶：雪龙2 静态资料、draft 7.85m + UKC 2.0m = 9.85m、15MW/18kn/PC3；明确未接入实时状态。
- API：环境 sources/times/query/batch/field/公开水深瓦片；船舶列表/详情/水深安全。
- 前端：环境图层（水深栅格 + 风/流/浪矢量）接入唯一地图；箭头按地理方位角构造；独立图层状态/图例/
  时间/来源/质量；环境面板、UTC 时间控制、值浮窗、船舶面板；不修改海冰/手绘航路/S-57。

### 效果

- 地图可在不打开第二个 Map 的情况下叠加水深/风/流/浪；每个图层独立显隐/透明度/加载/错误/来源。
- 环境查询单 Provider 失败不影响其他字段；缺测返回 `available=false` + reason，绝不填 0。
- `real_only` 可拒绝合成文件；前端明确显示“含合成数据”和每层 quality。
- 测试：后端 246 passed、前端 365 passed、typecheck 零错误。

### 已知限制

- 无真实环境数据；Provider 数据根为空时全部 unavailable，UI 正常降级。
- 环境显示与研究数据开关允许合成研究数据；规划（C 批次）默认 real_only。
- 风险栅格/规划候选航线/采纳编辑尚未实现（C/D 批次）。
- 现有 `.gitignore` 的 `data/*` 需在部署批次加 `data/navigation` 白名单；本批次未改部署挂载。

---

## 会话 #28 — 批次 C：风险、规划算法、异步任务与持久化（2026-10-29）

### 做了什么

- 风险分项评价器：`legacy_v1` 复现 V3 权重/公式；`real_v1` 禁止合成、雾 null、冰/深度缺失为
  UNKNOWN（非 0）、风/浪按可用权重归一；输出 ice/depth/fog/wind/wave/combined/quality/sources。
- 规划：25km 静态网格 loader、逐格环境适配、统一 EdgeTransitResult（船舶 max speed/power 注入）、
  D* Lite 三种子、自研 NSGA-III 三目标、PlannerService（候选/推荐/风险格/区域风险/重评）。
- 持久化：`planning_runs`+`planning_routes`；风险栅格 gzip 原子文件；Alembic 0005；
  0004 幂等修复支持 fresh DB。
- Worker：可注入 session 的 `run_once`、规划任务认领/心跳/取消/租约；异常不杀 worker。
- API：规划任务、候选航线、风险格/单格、取消、区域风险、采纳后评估；错误码区分环境缺失/
  无路线/超时/取消/算法失败/结果未就绪/网格缺失。

### 效果

- 后端已能在合成 fixture 上真实执行 D* Lite + NSGA-III，返回 Pareto 候选与风险栅格；
  `real_only` 数据不足时明确失败而非伪造。
- 风险/能耗/航时全部来自同一 EdgeTransitResult；Distance 仅统计；船舶选择影响速度/能耗。
- 规划异步执行，不占用地图 API；取消/超时/worker 异常有明确状态。
- 测试：后端 277 passed；SQLite 迁移升级通过。

### 已知限制

- 尚无前端规划工作台（D 批次）；候选航线/风险格还不能在地图上显示。
- 本机无真实环境数据；C 的端到端计算使用合成 fixture，真实环境规划未验证。
- Worker v1 串行，规划会延迟导入任务；后续可拆独立 planner worker。
- evaluate-route 以 ≤5km 加密采样，路线点数上限 1000；超限需新建规划。
