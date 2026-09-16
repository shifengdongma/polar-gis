# 前端航路规划模拟(绘制/编辑/多航线显示)— 实施计划

## Context

按任务书 `docs/plans/Polar-GIS 前端航路绘制 编辑 多航线显示功能开发任务.md` 实现前端航路规划沙箱:经纬度输入绘制、地图自由绘制(Draw)、拖拽编辑(Modify)、多航路同显/单条显隐、投影切换重建、localStorage 按项目隔离持久化。**纯前端,不改后端/数据库/S-57/WMS/GWC/Bundle/TileCache/调度器**。业务坐标唯一真值为 WGS84 `[lon, lat]`,OpenLayers Feature 仅为渲染结果。

已验证的先例(文档 14 结论):AIS 矢量层是模板 —— 原始经纬度存 feature 属性,`reloadAisGeometry()`(MapWorkspaceView.vue:2076-2082)在投影切换时用 `fromLonLat` 重建几何。航路层复制此范式。

## 核心设计决策(经风险分析修正)

1. **Draw 草图走独立 `Collection<Feature>`**(`features:` 选项),**不落入 routeSource**。原因:OL 10 的 Draw 在 drawend 后才把草图 push 进目标 source(会残留未样式化重复线),且 Draw 内部 overlay 默认 zIndex 0 会被海图(10-40)盖住。需 `draw.getOverlay().setZIndex(96)` + 虚线草图样式。
2. **拖拽期间禁止 reconcile**:`modifystart`/`modifyend` 维护 `isDragging` 标志;reconcile 入口 `if (isDragging) return`;且坐标不变时**绝不** `setGeometry`(`coordinatesEqual` 短路)——Modify 内部对 feature 的 `change` 事件会重建 rBush,中途换几何会拖死拖拽。
3. **不用 Select interaction**。点击选航路改用现有 `singleclick` 处理器里 `map.forEachFeatureAtPixel(..., { layerFilter: l => l === routeLayer, hitTolerance: 6 })`,加守卫 `routesStore.interactionMode === 'idle' && !measureInteraction && routePanelVisible`。避免第二套选中状态与测量 Draw 的交互竞争。
4. **store 用单调 `revision` 计数器**通知地图同步(每次变更 `revision++` + 持久化),composable `watch(() => store.revision)` —— 不做 deep watch routes。
5. **interactionMode 用 `watch(..., { flush: 'sync' })`** 驱动 Draw/Modify 生命周期:面板/视图只调 store,消除"两个 Draw 并存"的微任务窗口。
6. **投影切换全量重建**:`reloadRouteGeometry()` 先强制 mode='idle',再 `source.clear()` + 从 store WGS84 全部重建 —— 杜绝累积 transform。
7. **跨 180° 经线**:`unwrapLongitudes()` 仅作用于渲染几何(EPSG:3857 下 179→-179 展开为 179→181,`fromLonLat` 可处理超范围经度);业务数据永不改写;回写时 `normalizeLongitude()` 收拢到 ±180;`routeSource` 设 `wrapX: true`;`fitRoute` 的 extent 用 `shiftExtentIntoProjection()` 平移回投影范围内。
8. **`crypto.randomUUID()` 需安全上下文** —— `createId()` 提供 `getRandomValues` UUID v4 降级(局域网 http 部署时 crypto.randomUUID 为 undefined)。
9. **抽屉 `:modal="false"`**(默认 mask 会挡死地图绘制)+ `:lock-scroll="false"`。
10. 单条显隐:style function 返回 `null`(禁 `routeLayer.setVisible(false)`)。zIndex:航路层 **95**(> 海图 10-40,< measure 100 / ais 110)。
11. 缩放/平移不重建:VectorLayer + LineString + View resolution 自然完成;不监听 zoom/moveend;线宽常驻像素级(普通 2.5px、选中 4.5px、编辑中虚线)。

## 新增文件(6 个)

### 1. `frontend/src/types/index.ts` — 末尾(477 行后)追加

沿用 `// ── ... ──` 分隔注释风格,新增 `RoutePoint { id, seq, lon, lat }`、`RouteDraft { id, projectId, name, description?, points, visible, createdAt, updatedAt }`、`RouteInteractionMode = 'idle' | 'draw' | 'edit'`。已验证现有类型无冲突。

### 2. `frontend/src/utils/mapRoute.ts`(纯函数,~260 行)

只 import `ol/geom/LineString`、`ol/proj`、`ol/sphere`、`ol/extent`、`ol/style`、`ol/Feature` —— **禁 import ol/layer、ol/source、ol/Map**(保持 jsdom 可测)。命名导出、camelCase(项目约定)。

- `validateRouteCoordinate(lon, lat) → { ok } | { ok:false, error }`:非数字/NaN/Infinity/越界(±180/±90)各自明确文案
- `validateRoutePoint` / `validateRoutePoints`(< 2 点 → "航路至少需要两个航路点")
- `parseRouteCoordinateText(text) → { points, errors }`:按行切,跳过空行与 `#` 注释,行内按 `/[\s,;、]+/` 切,恰好 2 token 且合法;错误文案 `第 N 行坐标格式错误(应为 经度,纬度)`(N 为原始行号)
- `normalizeRoutePoints`:丢非法点、补 id、重排 seq(1-based)
- `unwrapLongitudes(points)`:内部先按 seq 排序,相邻 |Δlon| ≤ 180 连续化(仅渲染用)
- `routePointsToProjectedCoordinates(points, crs)` / `projectedCoordinatesToRoutePoints(coords, crs)`(toLonLat + 过滤非有限 + normalizeLongitude + 新 id)
- `buildRouteLineString(points, crs) → LineString | null`
- `calculateRouteLength(points)`:4326 球面 getLength(跨 180° 天然正确)
- `routeColor(routeId)`:字符串 hash → 固定 8 色池(稳定,不随机)
- `createRouteStyle({ isRouteVisible, isRouteActive, isRouteEditing }) → StyleFunction`:隐藏返回 null;普通/选中/编辑三态;外描边(halo);选中时渲染首尾点标记(`routeWaypoints` MultiPoint 属性 + Style(geometry));Style 实例按 (color, variant) 模块级缓存(styleFunction 每帧每要素执行,禁每次 new)
- `buildRouteFeature(route, crs)`:set routeId/routeName/routeType='route-draft'/routeWaypoints
- `coordinatesEqual` / `shiftExtentIntoProjection(extent, crs)`(3857 跨线 extent 按投影宽度平移)/ `longitudeDelta`(测试用)/ `createId()`(UUID + 降级)

### 3. `frontend/src/stores/routes.ts`(Pinia setup store,~250 行)

- state:`routes`、`activeRouteId`、`interactionMode`、`revision`、`loadedProjectId`;computed:`visibleRouteIds`、`activeRoute`、`canEditPoints`
- localStorage key `polar-gis:route-drafts:${projectId}:v1`,payload `{ version: 1, routes }`;`parseStoredRoutes` 全容错:getItem/JSON.parse 抛错 → 空数组(console.warn);接受 `{version,routes}` 与裸数组两种外形;逐条逐点校验,非法点丢弃,< 2 点整条丢弃,重复 id 去重,缺字段补默认;`saveLocalRoutes` try/catch(配额/隐私模式只警告一次)。**解析失败绝不导致地图工作台加载失败**。
- actions:`ensureLoaded(projectId)`(projectId 变化时重置再加载,幂等)、`createRoute(name?)`(默认名 `航路 N`,N 取未占用最小序号)、`createRouteFromPoints`、`deleteRoute`、`setActiveRoute`、`updateRouteName`、`replaceRoutePoints`(按索引复用旧 point id)、`updateRoutePoint`、`addRoutePoint`、`removeRoutePoint`(≤2 点时拒绝 `{ ok:false, error: '航路至少需要两个航路点' }`)、`toggleRouteVisibility`/`showAllRoutes`/`hideAllRoutes`、`setInteractionMode`、`clearRoutes`、`reset`
- 所有变更动作走私有 `touch()`:`revision++` + 持久化(任务书第八条全清单覆盖)

### 4. `frontend/src/composables/useRouteDrawing.ts`(无 UI,~300 行;新建 composables/ 目录)

```ts
useRouteDrawing({ getMap, getCrs, deactivateOthers, isSelectionEnabled }): RouteDrawingApi
// Api: layer/source、syncRoutesToMap、removeRouteFeature、selectRouteAtPixel、
//      startRouteDraw、cancelRouteDraw、removeLastRoutePoint、startRouteModify、
//      stopRouteModify、reloadRouteGeometry、fitRoute、refreshStyles、dispose
```

- `routeSource = new VectorSource({ wrapX: true })` + `routeLayer = new VectorLayer({ zIndex: 95, updateWhileInteracting: true, style: createRouteStyle(...) })`;`featureByRouteId: Map`
- `reconcileRoutes()`(watch revision 触发):入口 `if (isDragging) return`;按 routeId 对账 —— 不存在则 `buildRouteFeature` 添加;存在则仅 `coordinatesEqual` 为 false 时 `setGeometry`(Feature 身份稳定,Modify 引用不失效);删除多余 feature;防御性清掉无 routeId 的残留要素
- `watch(() => store.interactionMode, applyInteractionMode, { flush: 'sync' })`:
  - 先 teardown(内部先 `draw.abortDrawing()` 丢草图 → removeInteraction → 清 sketch Collection)
  - `'draw'`:sketch Collection + `new Draw({ features: sketch, type: 'LineString', minPoints: 2, style: 虚线 })`,`getOverlay().setZIndex(96)`;drawend → `projectedCoordinatesToRoutePoints` → `replaceRoutePoints(activeRouteId)`(无 active 则 createRouteFromPoints)→ mode 'idle'
  - `'edit'`:`new Modify({ features: new Collection([activeFeature]) })`;modifystart 置 isDragging;modifyend → 先清 isDragging → toLonLat 全部坐标 → `replaceRoutePoints`(mode 保持 edit)
  - `'idle'`:移除交互 + refreshStyles
- `reloadRouteGeometry()`:mode 归 idle → source 全清 → 从 store WGS84 全量重建
- `fitRoute(routeId)`:`getExtent()` → `shiftExtentIntoProjection` → `view.fit({ padding: [90, 470, 90, 420], maxZoom: 12, duration: 500 })`(右侧让开抽屉,左侧让开图层面板)
- `selectRouteAtPixel(pixel)`:forEachFeatureAtPixel + layerFilter;命中 → `store.setActiveRoute`;未命中不清空选中
- `dispose()`:移除 Draw/Modify、清 sketch/routeSource、清 Map
- 不写单测(需真实 OL Map + canvas,jsdom 收益低;由手工场景验证)

### 5. `frontend/src/components/RoutePlannerPanel.vue`(~330 行)

- props `{ visible: boolean, drawing: RouteDrawingApi }`,emit `update:visible`;内部用 `useRoutesStore()`
- 根:`<el-drawer :model-value="visible" @update:model-value="..." :modal="false" :lock-scroll="false" direction="rtl" size="440px" title="航路规划模拟">`;**`:modal="false"` 是硬性要求**
- 顶部 `el-alert`:「当前航路仅用于功能模拟,不作为实际导航依据。」(仿 weather 抽屉 2349-2350 行写法)
- 行 1:`[+ 新建航路]`(ElMessageBox.prompt,默认名 `航路 N` → createRoute + setActiveRoute)、`[全部显示] [全部隐藏]`
- 航路列表:el-checkbox(visible 切换)+ 名称(点击选中)+ `N 个航路点`(< 2 时黄色警示)+ `定位`(drawing.fitRoute)+ `删除`(`ElMessageBox.confirm('删除航路「x」？此操作不可恢复。', '删除航路', { type: 'warning' })`;删 active 前先 mode='idle')
- 当前航路区:名称 el-input(@change 校验非空);点表 el-table(#/经度/纬度/操作):`el-input-number :model-value :min="-180" :max="180" :precision="6" :controls="false" @change=...`(lat ±90),非法值 ElMessage.error 且不写 store,用本地镜像 rowVersion + `:key` 强制重挂载回退显示;行删除 `:disabled="points.length <= 2"`;`[+ 添加航路点]`;底部 `航路长度:xx km`(calculateRouteLength)
- 按钮区:`[地图绘制]`(active 已有 ≥2 点 → confirm 覆盖确认;无 active → prompt 建名)→ drawing.startRouteDraw();drawing 中显示 `[撤销点]`(drawing.removeLastRoutePoint)/`[取消绘制]`(drawing.cancelRouteDraw,删空草稿);`[拖拽编辑] / [结束编辑]`(按 mode 切换);`[定位航路]`
- 批量坐标输入:el-input textarea(placeholder `120.123456,72.123456`)+ `[应用坐标]`:parseRouteCoordinateText,有 errors → 逐条展示错误且**不覆盖** store;无 errors → 无 active 先建航路,再 replaceRoutePoints
- 文案避免「最优航线/真实安全航行路径/导航推荐」

### 6. `frontend/src/utils/mapRoute.test.ts` + `frontend/src/stores/routes.test.ts`

**mapRoute.test.ts**(~30 用例):文件顶部注册 proj4 EPSG:3413(与 MapWorkspaceView.vue:273-275 相同 def + `register(proj4)` + setExtent —— 测试环境不全局注册,注释说明是有意重复)。用例:校验(0,0 / 180,90 / -180,-90 合法;181,0 / 0,91 / NaN / Infinity / 字符串 / null 非法+文案);文本解析(3 行→3 点、`第 2 行坐标格式错误`、空行/# 注释跳过);3857 与 3413 LineString 点数一致 + `toLonLat(coords[0])` 还原 [120,72] 证明未交换 lon/lat;round-trip 4326→crs→4326(用 `longitudeDelta` 断言 < 1e-9,勿对 raw lon 用 toBeCloseTo);跨 180°(179→-179:3857 unwrap 后相邻 Δx 小于半个世界宽、round-trip 还原 179/-179、3413 天然连续);calculateRouteLength(赤道 1° ≈ 111.19km);routeColor 稳定且落池;createRouteStyle(隐藏→null、A/C 可见 B 隐藏、active 线更宽、editing 有 lineDash);shiftExtentIntoProjection;normalizeRoutePoints。注意:Style 只实例化不渲染(jsdom 无 canvas);id 只断言非空唯一。

**routes.test.ts**(~14 用例):仿 `stores/projects.test.ts` 风格(`setActivePinia(createPinia())` + `localStorage.clear()`)。创建/删除/重命名、点位 CRUD、2 点时删除拒绝、显隐+visibleRouteIds、active 生命周期、revision 递增、持久化恢复、**两个 projectId 隔离**、损坏 JSON 不抛、裸数组/高 version/points 非数组/越界坐标容错、< 2 点不写盘。

## MapWorkspaceView.vue 最小侵入修改(16 处,~70 行)

| # | 位置 | 改动 |
|---|---|---|
| 1 | 图标 import(~L17) | 加 `Compass` |
| 2 | L45-48 区域 | import RoutePlannerPanel / useRoutesStore / useRouteDrawing |
| 3 | L142 附近 | `const routesStore = useRoutesStore()` |
| 4 | L161 后 | `routePanelVisible` ref;`stopMeasureInteraction()`(仅 removeInteraction,不清 measureSource/measureText 保测量结果);`deactivateOtherMapInteractions() { queryMode=false; weatherMode=false; stopMeasureInteraction() }` |
| 5 | setup 内 | `const routeDrawing = useRouteDrawing({ getMap: () => map, getCrs: () => currentCrs.value, deactivateOthers: deactivateOtherMapInteractions, isSelectionEnabled: () => routePanelVisible.value })`;`watch(routePanelVisible, open => { if (!open) routesStore.setInteractionMode('idle') })` |
| 6 | activateMeasure 首行(L1883) | `routesStore.setInteractionMode('idle')` |
| 7 | L497 后 | `map.addLayer(routeDrawing.layer)` |
| 8 | singleclick(L504) | 首行 `if (routesStore.interactionMode !== 'idle' || measureInteraction) return`;末分支 `else if (routePanelVisible.value) routeDrawing.selectRouteAtPixel(event.pixel)` |
| 9 | L1037 后 | `routeDrawing.reloadRouteGeometry()`(紧接 reloadAisGeometry,同一同步任务内完成 → 无错投影中间帧) |
| 10 | onMounted L2092 后 | `routesStore.ensureLoaded(config.value.project.id)` |
| 11 | `await buildMap()` 后(L2109) | `routeDrawing.syncRoutesToMap()` |
| 12 | onBeforeUnmount 首行(L2118) | `routeDrawing.dispose()` |
| 13 | L2297-2298 | query/weather 按钮内联改为 `toggleQueryMode()`/`toggleWeatherMode()` 函数(各加 mode 归 idle) |
| 14 | L2300 后 | 新按钮:`<el-tooltip content="航路规划模拟" placement="left"><button :class="{ active: routePanelVisible }" @click="routePanelVisible = !routePanelVisible"><el-icon><Compass /></el-icon></button></el-tooltip>`(复用 `.map-tools button.active` 样式) |
| 15 | L2325 后 | `<RoutePlannerPanel v-model:visible="routePanelVisible" :drawing="routeDrawing" />` |

**明确不动**:unloadAllChartLayers(L1826)、detachWmsLayer、setOverviewVisible(只匹配 `map-base-layer` className)、captureMap(L1912,遍历 `.ol-layer canvas` 自动含航路层)、smart/standard/bundle/queue/cache 全链路、测量/AIS 生命周期。

## styles.css(末尾追加 ~60 行)

`.route-planner-drawer` 内部类(kebab-case,沿用现有 token):route-toolbar / route-list / route-item(.is-active)/ route-warning(color: var(--warning))/ route-length(var(--muted));`@media print` 追加隐藏 `.route-planner-drawer`。

## 构建顺序

| 阶段 | 内容 | 验证 |
|---|---|---|
| P1 | types 追加 | `npm run typecheck` |
| P2 | mapRoute.ts + 测试 | `npx vitest run src/utils/mapRoute.test.ts` |
| P3 | stores/routes.ts + 测试 | `npx vitest run src/stores/routes.test.ts` |
| P4 | useRouteDrawing.ts | `npm run typecheck` |
| P5 | RoutePlannerPanel.vue + styles.css | `npm run typecheck` |
| P6 | MapWorkspaceView 16 处接入 | typecheck + 手工场景 1-5 |
| P7 | 回归:场景 6-12(缩放/拖动/投影 3 循环/测量/AIS/批量加载卸载/smart↔standard,Network 面板确认 zoom/pan 0 请求) | 手工 |
| P8 | 全量验证 + 文档 | 见下 |

## 验证

1. `cd frontend && npm run typecheck`(strict + noUnusedLocals/Parameters,未用参数 `_` 前缀)
2. `npm test`(全部既有测试 + 新增 ~44 用例)
3. `npm run build`
4. 手工验收:任务书场景 1-12(经纬度创建、自由绘制、表格修改即时更新、拖拽双向同步+刷新恢复、多航路单条显隐、缩放 5+5、拖动、投影切换 3 循环无残留/无累积误差、测量互斥、AIS 共存、批量加载/卸载不清航路、smart/standard 切换无影响)。**zoom/pan 全程 0 API/GeoServer 请求**为验收项。

## 文档更新(会话 #21,日期 2026-09-16)

- **docs/09**:追加 `## 5.11 前端航路规划模拟 (会话 #21)`(数据不变量/Route Store+localStorage 容错/routeLayer 样式/绘制编辑交互/投影处理/互斥与生命周期);同步更新 `### 3.1` 目录树(composables/、RoutePlannerPanel、routes.ts、mapRoute.ts)与 `### 6` 前端文件清单计数。
- **docs/10**:`## 会话 #21 — 前端航路规划模拟(绘制/编辑/多航线/投影重建)` + 任务计划表/修改记录表/真实测试输出/关键决策(草图独立 Collection、isDragging+coordinatesEqual、弃 Select 用命中测试、unwrap 仅渲染层、:modal=false、UUID 降级)。
- **docs/11**:`## 会话 #21 — 前端航路规划模拟(2026-09-16)` + 修改了什么/达到的效果/验证结果。
- **docs/12**:`### 4.3` 下追加 `#### 4.3.7 航路规划模拟(新增功能)`(打开/新建/输入坐标/批量粘贴/自由绘制/撤销取消/拖拽编辑/增删点/显隐/定位/删除/投影切换注意/本地草稿与项目隔离),4.3.3 工具表补一行;保留「非认证航海显示/不作为真实导航依据」。TOC 若加则补 4.3.1-4.3.6 保持粒度一致(现有 TOC 只到 ###,可不加)。

## Git

按 CLAUDE.md:完成后 `git add -A && git commit`(中文提交信息,描述新增/修改)+ `git push origin master`(doc 14 与任务书为未跟踪文件,一并提交)。
