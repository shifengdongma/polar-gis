# 航路绘制功能优化 — 实施计划（Polar-GIS 前端）

## Context

`docs/plans/航路绘制功能优化.md` 提出五项任务（A 悬停坐标、B 航线信息浮窗、C 航段/航点定位/说明、D 后端规划结果契约草案、E 测量投影审计与修复）。本计划在实际仓库中完成开发、测试与文档更新，不只是输出方案。

出发点是一个**已确认的真实缺陷**：`switchProjection()`（`MapWorkspaceView.vue:1060-1097`）重建海图 WMS、渲染 bundle、瓦片缓存、AIS 与航路几何，**唯独不处理 `measureSource` / `measureText` / `measureInteraction`** —— 切换投影后测量图形留在旧投影坐标上（位置错误），状态栏仍显示旧数值；进行中的测量 Draw 也不会被移除，还会永久卡住 `singleclick` 的 `|| measureInteraction` 守卫，使要素识别 / 气象查询静默失效。

目标：修复测量投影生命周期（任务 E）→ 抽出航段公共计算（C1 基础）→ 航线信息浮窗（B）→ 悬停坐标提示（A）→ 航点定位与说明（C2/C3）+ 规划结果契约草案（D）。

**基线**：分支 `master`，HEAD `594b47a`，工作区干净（仅 `docs/plans/航路绘制功能优化.md` 未跟踪）。前端 11 个测试文件 / 197 用例通过，`typecheck` 零错误。

---

## 一、现状核对：任务书 vs 实际代码

任务书给的线索**基本属实**（pointermove 五位小数经纬度且无节流；`singleclick` + `forEachFeatureAtPixel` 仅命中 `routeLayer`；业务坐标恒为 WGS84 `[lon,lat]`；测量用 `ol/sphere` 并传当前 CRS；草稿按项目存 localStorage）。**四处需要修正**：

1. **测量没有任何地图内提示/浮窗**（结果只在底部状态栏），`ol/Overlay` 在仓库中零使用；测距/测面积按钮**没有 `active` 状态**（`measureInteraction` 是模块级 `let`，非响应式）。
2. **航路选中被面板可见性门控**：`isSelectionEnabled: () => routePanelVisible.value`（`:214`）→ 面板关闭时点击航线无任何反应。
3. **`calculateRouteLength` 只有一个调用点**（`RoutePlannerPanel.vue:42`），地图侧测量走的是另一条独立的 `ol/sphere` 路径。
4. 任务书"任务 E"预设的若干疑点经实测**不成立**（见下）。

### 实测结论（node 直连仓库内 ol@10.6.1，非推测）

**不是缺陷的**（不写"已修复"，如实记录）：

- `getLength(geom, {projection: currentCrs})` **数值正确**：固定 WGS84 点组 `[[10,70],[30,75],[50,72],[20,78]]` 在 4326/3857/3413 下均为 `2642270.001110` m（误差 0.0000）。因为 `ol/sphere.getLength` 内部先 `clone().transform(P,'EPSG:4326')` 再做 haversine。
- haversine 对 Δλ 取 `sin²`，**天然跨 180° 安全**（170E→170W 与参考值一致）。
- `getArea` 对**普通多边形**在两种投影下与 EPSG:4326 参考**完全一致**（0.00%）。
- 球面模型比 WGS84 椭球测地线**偏短 0.28%–0.42%**（高纬 −0.42%、中纬 45N −0.28%）——按"近似地表距离"表述，不"修"。

**真实缺陷 5 项**：

| # | 问题 | 证据 / 复现 |
|---|---|---|
| 1 | 测量几何在投影切换后不重建、`measureText` 不重算 | 3857 几何被声明为 3413 → **+77.8%**；3413 几何被声明为 3857 → **−1.14%**。复现：测量一条线 → 切换投影 → 文本不变、图形错位 |
| 2 | 进行中的测量 Draw 不在投影切换的清理路径上 | 切换后 Draw 仍存活并会 `drawend`，其坐标随后按新 CRS 解释 |
| 3 | 面积跨 180° 经线**偏大 17 倍** | 20°×6° 盒 @70–76N 跨 170E..170W：`getArea` 返回 7,371,200 km²，真值 433,600 km² |
| 4 | 面积对**环绕极点**的环返回 **0** | 80°N 环真值 3,874,523 km²，`getArea` 返回 0（4/8/36/360 顶点全部为 0）。EPSG:3413 下极点就在屏幕中心，用户**可以**画出这种环 |
| 5 | 互斥缺口：残余测量 Draw 静默阻塞识别/气象 | `activateMeasure` 不清 `queryMode`/`weatherMode`；`toggleQueryMode`/`toggleWeatherMode` 不调 `stopMeasureInteraction()` → `:549` 守卫永远提前 return，点击无任何反馈 |

**关键不变量（已验证，供实现与测试引用）**：

- `canWrapX()`：**3857 = true，3413 = false**（proj4 注册的投影默认 `global: false`）→ 世界副本平移**只需 3857**；3413 的"投影范围外"判定可直接用 `containsCoordinate(extent, coordinate)`。
- `fromLonLat([181,70],'EPSG:3857')` → x `20148827.83`（**不回绕**），而 `toLonLat` 同值 → `−179`（**回绕**）→ 渲染几何可能与重算坐标**不在同一世界副本**，锚点与命中测试必须显式平移到同一副本。
- `toLonLat` 对 3413 越界坐标返回**有限但无意义**的值（`[5e6,5e6]`→lon 90/lat 30.5；`[2e7,2e7]`→lon 90/lat −43.08），**不返回 NaN**；往返转换误差 0.0000 m。→ **不能靠 NaN 判断"范围外"**，必须显式检查。
- `getLength` 字面上就是 `Σ getDistance`（同一 `DEFAULT_RADIUS = 6371008.8`）→ 分段和与总长可**逐位相同**（实测 `true`）：金值 `862219.483740 / 709458.259753 / 1070592.257618`，累计 `2642270.001110`。
- 地面分辨率 `getPointResolution(crs, view.getResolution(), 指针坐标, 'm')`：3857 zoom4→2532 m/px、zoom6→633、zoom8→158；3413 zoom3→19753、zoom5→4938、zoom7→1235。**同一 zoom 在两投影下地面精度差 7.8 倍** → 门槛必须用地面分辨率而非 zoom。
- 测地面积算法（Van Oosterom–Strackee，见阶段 1）：80°N 环 720 顶点 → 3,874,475 vs 解析真值 3,874,523（**0.001%**）；跨 180° 盒 → 425,977 km²，与同盒在常规坐标下**逐位相同**（向量法**不需要 unwrap**）；小多边形与 `ol/sphere.getArea` 相同（0.000%）；与 `ol/sphere` 的边模型差异：小多边形 0.000%、20°×6° 高纬盒 **−1.76%**、赤道 10°×10° +0.25%。
- `.map-canvas` 最终为 `inset: 0`（`styles.css:350` 覆盖 `:161` 的 `72px 0 0`）→ 与 `.map-workspace`（`position: fixed; inset: 0`）同框。

---

## 二、已确认的产品决策

1. **选线入口**：保持"面板打开时才能选中"的现有语义，仅增加可发现性提示（工具栏 tooltip 文案 + 面板打开时的状态栏提示），不自动打开面板。
2. **极点面积**：实现极点感知算法（采用测地扇形法，**一种算法覆盖全部多边形**）。
3. **C1 航段信息**：点表新增两列（「入站航段」= 距离 · 初始真方位；「累计」；起点行显示「—」），抽屉 440px → **520px**，同步把 `fitRoute` 右侧让位 `470` → `550`。

---

## 三、分阶段实施（每阶段先跑 typecheck + 相关测试，再进入下一阶段）

### 阶段 1 — 任务 E：测量投影审计与修复

**新建 `frontend/src/utils/mapMeasure.ts`**（纯模块：只 import ol 的几何/投影/球面模块，中文 JSDoc，具名导出，无 default export——完全对齐 `mapRoute.ts` 的约束）：

- `sphericalExcess(a,b,c) = 2·atan2(a·(b×c), 1 + a·b + b·c + c·a)`；`sphericalRingArea(ringLonLat)` = 以 0 号顶点扇形三角化求和 × R²（**R 直接 import `ol/sphere` 的 `DEFAULT_RADIUS`**，与距离共用同一球体），再取最小侧 `min(A, 4πR² − A)`；顶点数 < 3、非有限、退化/近对跖三角形 → `null`。**该算法对环两侧都成立且与经度回绕无关，因此"是否环绕极点"不再需要检测分支。**
- `projectedToLonLatSafe(coordinate, crs)`：有限性 → CRS 已知 → `!canWrapX()` 时 `containsCoordinate(proj.getExtent(), coordinate)` → `|lat| ≤ 90`；任一失败返回 `null`。经度用现有 `normalizeLongitude` 收拢。
- `buildMeasureGeometry(draft, crs)` / `measureGeometryToDraft(geometry, crs)` / `formatMeasureResult(draft)` / `formatDistance` / `formatArea` / `hoverDecimalsForGroundResolution` / 常量 `HOVER_MIN_GROUND_RESOLUTION_METERS = 1000`。
- **距离文本必须 km + NM（1 NM = 1852 m），短距离兼显 m；面积恒用 m²/km²，绝不换算海里。**
- 模块头注明：多边形面积采用**大圆边**（与 `getLength` 的大圆语义一致），大范围高纬多边形与旧 `getArea`（(λ,sinφ) 线性边）差异 ≤ ~1.8%。

**`MapWorkspaceView.vue` 改动**：

- 新增 `measureMode = ref<'none'|'LineString'|'Polygon'>('none')` 与 `measureDraft = shallowRef<MeasureDraft|null>(null)`；`measureInteraction` 退化为纯 OL 句柄，`measureMode` 成为"测量已激活"的唯一真值（同时驱动工具栏 `active`、`singleclick` 守卫、`stopMeasureInteraction()`）。
- `drawend` → `measureGeometryToDraft` 得到 WGS84 真值 → `applyMeasureDraft()`；**文本一律由 WGS84 真值生成**，不再调用 `getLength`/`getArea` → 显示值**按构造与投影无关**，整类"陈旧 CRS"缺陷消失而不是被补丁掩盖。
- 新增 `syncMeasureForProjection()`，在 `switchProjection` 内 `reloadRouteGeometry()` 之后调用（与 `reloadAisGeometry()` 同范式）：
  - 绘制中 → 移除 Draw、清 source 与真值、`measureText = '投影已切换，请重新测量'` + `ElMessage.warning`，**绝不把旧 CRS 几何当新 CRS 计算**；
  - 已完成 → 保留真值，按新投影重建显示几何并**从真值重算文本**。
- 互斥缺口修复：`toggleQueryMode` / `toggleWeatherMode` 补 `stopMeasureInteraction()`；`activateMeasure` 补 `queryMode.value = false` / `weatherMode.value = false` / `closeRouteFlyout()`；守卫改为 `measureMode.value !== 'none'`。
- 工具栏两个测量按钮加 `:class="{ active: measureMode === … }"`（`.map-tools button.active` 已存在，无需新 CSS）。

### 阶段 2 — 航段公共计算（`frontend/src/utils/mapRoute.ts`，扩展而非新建第二套）

- `METERS_PER_NAUTICAL_MILE = 1852`、`METERS_PER_DEGREE_LAT = 111320`。
- `routeSegments(points): RouteSegment[]`（`{index, from, to, distanceMeters, cumulativeMeters, initialBearingDeg}`），按 `seq` 升序，n 点 → n−1 段，距离用 `getDistance`（与 `getLength` 同一函数、同一顺序 → 逐位一致）。
- **`calculateRouteLength` 重写为 `routeSegments(...).reduce(Σ distanceMeters, 0)`**，"分段和 ≡ 总长"由构造保证；保留 `< 2 → 0` 契约，现有测试不变。
- `initialBearing(fromLon, fromLat, toLon, toLat)`：`atan2(sinΔλ·cosφ₂, cosφ₁·sinφ₂ − sinφ₁·cosφ₂·cosΔλ)`，`((x%360)+360)%360`；**不手工归一化 Δλ**（sin/cos 本身 2π 周期，跨 180° 自动正确）；重合点/非有限 → `null`。
- `formatDistance` / `formatArea` / `formatBearing`（文本层；非有限 → `—`）。
- `unwrapLongitudeSequence(lons)` 抽出，`unwrapLongitudes` 变为其薄包装（现有断言即回归防护）。
- `shiftCoordinateIntoWorldCopy(coordinate, referenceExtent, crs)`：`canWrapX()` 为 false 或非 3857 时原样返回；否则按整世界宽平移。命中测试与浮窗重锚共用它 → 两者必然一致。
- `routePointIndexById(points, pointId)`（C2 用）。

### 阶段 3 — 任务 B：航线信息浮窗

**新建 `frontend/src/components/RouteInfoFlyout.vue`**（纯展示，不碰 OL 对象，只调用传入的 `drawing` API——与 `RoutePlannerPanel` 同契约）：
内容：航路名 + 关闭；总长（km + NM）、航点数、起点/终点坐标；按 `seq` 的可滚动航点列表（点击 → 定位该点）；点中航段时显示航段序号（第 a 点 → 第 b 点）、该段距离、截至该段终点的累计距离、**初始真方位**；操作：定位整条航路（复用 `fitRoute`）、定位所选航点；脚注说明"按航路点顺序的球面最短路径（大圆）分段之和 · 屏幕直线段与大地线在极区/高纬/跨日期变更线处可能不重合 · 非实际可航里程"。数据来自同一个 `routeSegments` computed → 与面板不可能漂移。

**`useRouteDrawing.ts`**：`selectRouteAtPixel` → `pickRouteAtPixel(pixel, coordinate): RoutePickResult | null`（`{routeId, segmentIndex, pointIndex}`），内部保留现有门控与 `forEachFeatureAtPixel({layerFilter: layer === routeLayer, hitTolerance: 6})`、`setActiveRoute`。**隐藏航路自动不可命中**（`createRouteStyle` 对隐藏航路返回 `undefined`，不进入渲染重放组）。命中后：顶点优先（9 px 容差，> 起终点标记半径 7），再段判定（6 px 容差，复用同一常量），在**视空间**用 `hitTolerance × resolution` 做点—线段距离；渲染坐标已 unwrap 且按 seq 排序，**渲染下标 i ↔ seq 排序点 i** 一一对应。空点点击 → 只关浮窗，**不改选中**（避免误删/误改）。
新增 `highlightSegment()` / `flashRoutePoint()` / `getRouteAnchorCoordinate()`；`dispose()` 清计时器。`reloadRouteGeometry()` **故意不清高亮**（下标基于 seq，重建后仍正确）。

**高亮渲染**：扩展 `RouteStyleContext` 增加**可选**的 `getHighlightedSegment` / `getHighlightedPointIndex`（可选成员保证现有调用点与测试不受影响）；在 `createRouteStyle` 末尾追加一条 `Style` + `setGeometry(new LineString([...]))`（或 `Point`），stroke/image 走模块级缓存，**不新增 source/layer/interaction**。颜色 `ROUTE_SEGMENT_HIGHLIGHT_COLOR` / `ROUTE_POINT_HIGHLIGHT_COLOR = '#ffd166'` 定义在 `mapRoute.ts`。

**锚定与 DOM（与设计建议不同，取更稳妥方案）**：浮窗与悬停提示都挂在 `.map-canvas` 的**兄弟节点** `.map-overlay-root`（`position: absolute; inset: 0; pointer-events: none; z-index: 30`）里——与现有 `.map-tools` / `.map-status` 完全同一模式，**不往 OL 的 target 里塞 Vue 子节点**，几何上因 `.map-canvas` 已是 `inset: 0` 而完全重合。不用 `ol/Overlay`（`ol.css` 无 overlay 容器规则，OL 又用内联 `pointer-events: none`，Overlay 只买到重锚定，而重锚定本就是几行 `postrender` 监听）。
- 浮窗锚点：点击时**原样保存 `event.coordinate`**（与渲染要素同一副本，平移缩放重锚定精确）；仅投影切换时由 `lonLat` 重算并用 `shiftCoordinateIntoWorldCopy` 平移到与航路渲染几何同一副本。`postrender` 监听只在浮窗打开时挂载/卸载；像素用 `map.getPixelFromCoordinate` + `map.getSize()` 夹取在地图视口内（右侧预留抽屉 520px），`flipX/flipY` 仅由 `map.getSize()` 推导，**不做逐帧布局读取**。
- 生命周期：一个 `watch([revision, activeRouteId, interactionMode, routePanelVisible, currentCrs])` → 路由不存在/被隐藏/面板关闭/非 idle/项目或页面变化 → 关闭；否则实时刷新（内容直接读 store），并校正失效的 `segmentIndex`。`toggleQueryMode` / `toggleWeatherMode` / `activateMeasure` / `deactivateOtherMapInteractions` 均调 `closeRouteFlyout()`。

**可发现性（决策 1）**：工具栏 tooltip 改 `航路规划模拟 · 打开后可在地图上点选航路查看详情`；`.map-status` 在面板打开时显示 `点击地图上的航路可查看详情`。

### 阶段 4 — 任务 A：悬停坐标提示

- **复用现有 `pointermove` 监听**（`buildMap` 内 `:543`），状态栏写入保持原样不动，新增 `requestAnimationFrame` 合帧路径（`hoverRaf` + `flushHover`），**每帧最多一次**。
- 门槛：`getPointResolution(view.getProjection(), view.getResolution(), 指针坐标, 'm')` > `1000 m/px` → 隐藏（用指针坐标 → 纬度正确 → 两投影地面精度差异被正确体现；注释写明 1000 的依据）。小数位 `clamp(floor(log10(111320 / groundRes)), 2, 5)`——保证**末位数字从不细于 1 像素**（需注明 `floor` 在十进制档内会在 1–10 px 间漂移，这是预期行为而非缺陷）。
- 格式 `经度 123.4567° E · 纬度 74.1234° N`（**明确标注经纬度顺序**、明确方位字母）；经度 `normalizeLongitude` 收拢，退化方位呈现一致。
- 隐藏条件：低于门槛、浮窗打开、指针离开地图（viewport `pointerleave`）、`event.dragging`、触控/非精确指针（`matchMedia('(hover: hover) and (pointer: fine)')` + 逐事件 `pointerType !== 'mouse'`）、地图销毁（`onBeforeUnmount` 取消 rAF 并摘监听）、坐标非法（用 `projectedToLonLatSafe`，**不依赖 NaN**）。滚轮缩放后由 `moveend` 自校正。
- 定位为指针像素锚定（`translate(14px,14px)`，边缘翻转为 `calc(-100% - 14px)`），`pointer-events: none` 不遮指针不拦截事件、不写 Store、不创建航点。

### 阶段 5 — 任务 C2/C3 + 任务 D

- **C1**：`RoutePointRow` 增加 `inboundLegText` / `cumulativeDistanceText`（`types/index.ts`）；`pointRows` 由**一次** `routeSegments(points)` 构建（起点 `'—'`，其余 `距离 · 初始真方位`）；新增两列「入站航段」「累计」（表头 `title` 注明"大圆分段距离之和；方位为初始真方位角，非磁方位、也不代表整段恒定航向"）；`activeRouteLengthText` 改用 `formatDistance(calculateRouteLength(...))`；抽屉 440 → 520px，`useRouteDrawing.ts` 的 fit padding 提为常量 `ROUTE_FIT_PADDING`（470 → 550）。
- **C2**：`locateRoutePoint(routeId, pointId)` —— 下标由 `routePointIndexById` 得出，**坐标直接取渲染要素的 `coordinates[index]`**（已是对的副本，跨 180° 天然合理），`view.animate({center, zoom: max(当前, 6), duration: 400})` + 短暂高亮；不改数据、不进绘制/编辑、不触发测量/识别。面板点表加 `@row-click` 与「定位」按钮，`interactionMode !== 'idle'` 时忽略。
- **C3**：在现有 `.route-direction-legend` 区块追加一行说明（WGS84、`(经度, 纬度)` 顺序、km/NM + `1 NM = 1852 m`、初始真方位角、"模拟航路，仅供展示与交互验证，不作为实际导航依据"）。**不在占地图面积的区域加常驻帮助块。**
- **D**：新建 `frontend/src/types/routePlanning.ts`，**只有类型与适配接口、零运行时代码、不接 API、不造假数据**：`RoutePlanningStatus = 'missing'|'loading'|'computing'|'failed'|'stale'|'complete'`、`RoutePlanningRiskLevel`、`RoutePlanningSegmentResult`、`RoutePlanningResult`（routeId / resultVersion / computedAt / status / dataSource / totalDistanceMeters / estimatedDurationSeconds / riskLevel / riskIndicators / segments）、`RoutePlanningResultAdapter`（接入层负责字段校验 + 单位/时间格式转换 + 身份区分），以及显示原则：**非 `complete` 一律不渲染数值**，只显示状态文案。文件头与 `docs/09` §5.13 说明当前无任何页面消费它。

### 阶段 6 — 文档与提交

- `docs/09-system-architecture.md`：新增 §5.12（测量投影生命周期、球面面积算法与 ≤1.8% 边界、悬停门槛与小数位推导、浮窗/航段/定位、`.map-overlay-root` 指针规则）、§5.13（任务 D 契约）、§6 文件清单（前端 +3 源文件与对应测试）。
- `docs/10-work-log.md`：会话 #24，含任务书要求的**"现状—可复现问题—修复方式—验证结果"**与实测数值表。
- `docs/11-work-summary.md`：会话 #24（修改了什么 / 达到的效果 / 验证结果）。
- `docs/12-user-manual.md`：§4.3 补坐标悬停提示、航线浮窗、航段两列、航点定位、面板打开才可选线的条件、精度与"非认证航海显示"声明。
- `git add -A && git commit && git push origin master`（CLAUDE.md 硬性要求）。

---

## 四、测试与验收

**纯函数单测（独立推导的期望值，不复刻生产实现）**：

- `mapMeasure.test.ts`（新建）：`sphericalRingArea` 对**解析闭式** `2πR²(1−sin φ)`（80°N/720 顶点 ≤0.01%、80°N/36 顶点 ≤0.5%、75°N、60°N）；**极点环 ≠ 0** 的回归守卫；**跨 180° 不变量**（`area([[170,70],[-170,70],[-170,76],[170,76]]) === area([[-10,70],[10,70],[10,76],[-10,76]])`）；与独立实现 `ol/sphere.getArea` 在小多边形上的一致性（示例取 0.2°×0.2° 盒 **@70–70.2°N → 168 km²**，两算法实测相同；期望值按实际样例现算，不照抄）；反向环同面积、重复顶点无影响、< 3 顶点与 NaN → `null`；`projectedToLonLatSafe`（3413 `[0,0]→[-45,90]`、`[5e6,5e6]→null`、`[2e7,2e7]→null`、3857 越界仍有限）；`hoverDecimalsForGroundResolution`（2532→2、1000→2、158→2、39.6→3、9.9→4、0.5→5）；`buildMeasureGeometry`/`measureGeometryToDraft` 往返；**同一组 WGS84 点在 3857 与 3413 下 `formatMeasureResult` 文本完全相同**（投影不变性回归守卫）。
- `mapRoute.test.ts`（扩充）：`routeSegments` 金值 `862219.483740 / 709458.259753 / 1070592.257618`（6 位小数）与累计；`calculateRouteLength(points) === Σ segments`（`toBe`，逐位）；`initialBearing` 表（**含外部参考 JFK→LHR ≈ 51.3525°**，与公开大圆数据 ~51°21′ 一致）+ 全域 `[0,360)` 断言；重合点段距离 0 且方位 `null`；非有限输入不抛异常；乱序 `seq` 仍按 seq 计算；`formatDistance`（`812.3→812.3 m / 0.44 NM`、`2642270.001→2642.27 km / 1426.71 NM`、`NaN→—`）；`formatArea`（输出**永不含 NM**）。

**UI/组件（沿用仓库唯一先例——源码文本断言）**：扩充 `RoutePlannerPanel.test.ts`（`入站航段`/`累计` 列、`size="520px"`、起点 `'—'`、`1 NM = 1852 m`、`初始真方位`，且不得移除既有断言）；新建 `RouteInfoFlyout.test.ts`（含 `初始真方位`/`NM`/`定位整条航路`/`定位所选航点`/`关闭`，且**不含任何写接口** `replaceRoutePoints`/`updateRoutePoint`/`createRoute`/`removeRoutePoint`/`deleteRoute`；`styles.css` 断言 `.map-overlay-root{pointer-events:none}`、`.route-info-flyout{pointer-events:auto}`、`.map-hover-coord{pointer-events:none}` 与角色色值等于导入的颜色常量）；新建 `MapWorkspaceView.test.ts`（`pointermove` + `requestAnimationFrame`；守卫用 `measureMode.value`；两个 toggle 都调 `stopMeasureInteraction`；`switchProjection` 调 `syncMeasureForProjection`；测量按钮有 `active`；tooltip 含 `可在地图上点选航路`；`.map-status` 含 `点击地图上的航路可查看详情`）。

**浏览器手工验证（列明步骤）**：悬停门槛上下（3857 在 72°N 约 z6 起、0° 约 z8 起；3413 约 z6 起）、小数位随分辨率变化、拖动/离开/触控隐藏、滚轮后自校正；浮窗单条/多条/隐藏航路、点段 vs 点顶点 vs 点空白（只关窗不改选中）、边缘翻转、1280×720 下不与 520px 抽屉重叠、定位操作不进入绘制/编辑、投影切换后重锚定且高亮存活、改名/拖拽/删除/隐藏后的刷新或关闭；测量投影切换（进行中 / 完成后两种）；回归：海图批量加载与卸载、smart/standard、AIS、要素识别、气象、航路 localStorage 恢复、截图（浮层不得进入截图）、平移缩放。

**无法验证（将如实列明，不写"全部通过"）**：要素识别与气象的端到端（需后端 identify / demo-weather 接口）、S-57 真实海图渲染与 RenderPlan/bundle 路径、GWC 瓦片缓存、底图/WMTS capabilities、项目切换 API、真实瓦片上的截图合成——均依赖运行中的后端与 GeoServer。

---

## 五、风险与限制

1. **抽屉 440→520px + `fitRoute` padding 470→550** —— 已交付功能的可见取景变化；两处为同一常量，需在 1280×720 / 1920×1080 手工确认。
2. **3857 世界副本不一致**（`fromLonLat` 不回绕 / `toLonLat` 回绕）——本次改动最微妙之处；`shiftCoordinateIntoWorldCopy` 是唯一收口点，需单测 + 跨 180° 航路的手工验证。
3. **面积语义变化**：大范围高纬多边形相对旧 `getArea` 变化 ≤1.76%（小多边形 0.000%），是**刻意且有据**的更正（实现 `ol/sphere` 自己文档所称的大圆边契约，并与 `getLength` 的大圆语义一致），须在文档与界面文案中如实说明，避免被误判为回归。
4. **`decimals` 十进制档跳变**属预期行为，需注释说明以免后人"修复"。
5. **浮层不与 OL target 混住**（选择兄弟节点方案）已规避 Vue 与 OL 争抢 `.map-canvas` 子节点的风险；若出现异常，回退方案是改挂到 `.map-workspace` 并保持 `inset: 0`。
6. `tsconfig` 开启 `noUnusedLocals`/`noUnusedParameters` —— 每阶段跑 typecheck，不要攒到最后。
