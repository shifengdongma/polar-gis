/**
 * 航路绘制 composable — 只负责 OpenLayers 地图交互,不负责 UI。
 *
 * 数据流(不可颠倒):
 *   Routes Store (WGS84 [lon,lat] 唯一业务真值)
 *        ↓ revision 通知
 *   reconcileRoutes() → fromLonLat → Feature<LineString>(1 个 layer,N 个 feature)
 *        ↑ modifyend / drawend → toLonLat 回写
 *   Store
 *
 * 关键决策:
 * - Draw 草图走独立 Collection<Feature>,绝不落入 routeSource(避免重复线);
 * - Modify 拖拽期间(modifystart → modifyend)禁止 reconcile,且坐标不变绝不
 *   setGeometry(coordinatesEqual 短路),保证 Feature 身份稳定、不打断拖拽;
 * - 投影切换由 reloadRouteGeometry() 从 Store WGS84 全量重建,杜绝累积 transform。
 */
import { watch } from 'vue'
import { ElMessage } from 'element-plus'
import Collection from 'ol/Collection'
import type { Extent } from 'ol/extent'
import Feature from 'ol/Feature'
import LineString from 'ol/geom/LineString'
import type { DrawEvent } from 'ol/interaction/Draw'
import Draw from 'ol/interaction/Draw'
import Modify from 'ol/interaction/Modify'
import VectorLayer from 'ol/layer/Vector'
import type OlMap from 'ol/Map'
import type { Pixel } from 'ol/pixel'
import VectorSource from 'ol/source/Vector'
import { Stroke, Style } from 'ol/style'
import { useRoutesStore } from '../stores/routes'
import type { RouteInteractionMode } from '../types'
import {
  ROUTE_MIN_POINTS,
  buildRouteFeature,
  buildRouteLineString,
  coordinatesEqual,
  createRouteStyle,
  projectedCoordinatesToRoutePoints,
  routePointIndexById,
  shiftCoordinateIntoWorldCopy,
  shiftExtentIntoProjection,
} from '../utils/mapRoute'

/** 高于海图 WMS(10-40),低于测量层(100)与 AIS(110) */
const ROUTE_LAYER_Z_INDEX = 95
/** Draw 内部草图 overlay 默认 zIndex 0,会被海图盖住 —— 抬到航路层之上 */
const SKETCH_OVERLAY_Z_INDEX = 96

/**
 * fitRoute 的让位 padding [上, 右, 下, 左]。
 * 右侧 550 = 航路面板抽屉 520px + 30px 边距;左侧 420 让开图层面板。
 * 抽屉宽度改动时必须同步这里,否则定位后航路会被抽屉压住。
 */
const ROUTE_FIT_PADDING: [number, number, number, number] = [90, 550, 90, 420]

/** 命中航路要素的像素容差(forEachFeatureAtPixel 与航段判定共用,保证两者一致) */
const ROUTE_HIT_TOLERANCE_PX = 6
/** 命中航路点的像素容差:须大于起点/终点标记半径(7px),否则点不到标记 */
const ROUTE_VERTEX_HIT_TOLERANCE_PX = 9

/** 定位航路点后的短暂高亮时长 */
const ROUTE_POINT_FLASH_MS = 2400

export interface RoutePickResult {
  routeId: string
  /** 命中的航段序号(1-based);命中航路但在航段容差之外为 null */
  segmentIndex: number | null
  /** 命中航路点时的 seq 升序下标;否则 null */
  pointIndex: number | null
}

export interface RouteDrawingOptions {
  getMap: () => OlMap | null
  getCrs: () => string
  /** 进入绘制/编辑前由视图关闭要素识别 / 气象 / 测量等互斥交互 */
  deactivateOthers: () => void
  /** 仅当返回 true 时允许点击地图选中航路(航路面板打开时) */
  isSelectionEnabled?: () => boolean
}

export interface RouteDrawingApi {
  readonly layer: VectorLayer<VectorSource>
  readonly source: VectorSource
  syncRoutesToMap(): void
  /** 点击命中测试:选中航路并返回命中细节(航段 / 航路点) */
  pickRouteAtPixel(pixel: Pixel, coordinate: number[]): RoutePickResult | null
  startRouteDraw(): void
  cancelRouteDraw(): void
  removeLastRoutePoint(): void
  startRouteModify(): void
  stopRouteModify(): void
  reloadRouteGeometry(): void
  fitRoute(routeId: string): void
  /** 高亮选中航段(1-based);null 清除高亮 */
  highlightSegment(routeId: string | null, segmentIndex: number | null): void
  /** 定位并短暂高亮某个航路点(不进入绘制/编辑,不改数据) */
  locateRoutePoint(routeId: string, pointId: string): void
  /** 航路渲染几何的 extent(浮窗锚点对齐世界副本用);无则 null */
  getRouteExtent(routeId: string): [number, number, number, number] | null
  dispose(): void
}

function sketchStyle(): Style {
  return new Style({
    stroke: new Stroke({ color: '#ff6b35', width: 3, lineDash: [6, 6] }),
  })
}

export function useRouteDrawing(options: RouteDrawingOptions): RouteDrawingApi {
  const store = useRoutesStore()
  const routeSource = new VectorSource({ wrapX: true })

  // 高亮态只存在于地图侧(不是业务数据,绝不进 Store):
  // 航段下标是 1-based 的 seq 顺序口径,与几何重建无关,故投影切换后依然正确。
  let highlightedSegment: { routeId: string; index: number } | null = null
  let highlightedPoint: { routeId: string; index: number; timer: number } | null = null

  const routeLayer = new VectorLayer({
    source: routeSource,
    zIndex: ROUTE_LAYER_Z_INDEX,
    updateWhileInteracting: true,
    style: createRouteStyle({
      isRouteVisible: (routeId) => store.routes.some((route) => route.id === routeId && route.visible),
      isRouteActive: (routeId) => store.activeRouteId === routeId,
      isRouteEditing: (routeId) => store.interactionMode === 'edit' && store.activeRouteId === routeId,
      getHighlightedSegment: (routeId) => (highlightedSegment?.routeId === routeId ? highlightedSegment.index : null),
      getHighlightedPointIndex: (routeId) => (highlightedPoint?.routeId === routeId ? highlightedPoint.index : null),
    }),
  })
  const featureByRouteId = new Map<string, Feature<LineString>>()
  let drawInteraction: Draw | null = null
  let modifyInteraction: Modify | null = null
  let sketchFeatures: Collection<Feature> | null = null
  let isDragging = false

  function refreshStyles() {
    routeLayer.changed()
  }

  function removeRouteFeature(routeId: string) {
    const feature = featureByRouteId.get(routeId)
    if (!feature) return
    featureByRouteId.delete(routeId)
    routeSource.removeFeature(feature)
  }

  /** 以 Store 为真值对账地图要素:新增 / 更新几何 / 删除,Feature 身份保持稳定 */
  function reconcileRoutes() {
    if (isDragging) return
    const seen = new Set<string>()
    for (const route of store.routes) {
      seen.add(route.id)
      if (route.points.length < ROUTE_MIN_POINTS) {
        removeRouteFeature(route.id) // 非法草稿不渲染
        continue
      }
      const existing = featureByRouteId.get(route.id)
      if (!existing) {
        const feature = buildRouteFeature(route, options.getCrs())
        if (!feature) continue
        featureByRouteId.set(route.id, feature)
        routeSource.addFeature(feature)
        continue
      }
      const geometry = buildRouteLineString(route.points, options.getCrs())
      if (!geometry) {
        removeRouteFeature(route.id)
        continue
      }
      const current = existing.getGeometry()
      if (!current || !coordinatesEqual(current.getCoordinates(), geometry.getCoordinates())) {
        existing.setGeometry(geometry)
      }
      if (existing.get('routeName') !== route.name) existing.set('routeName', route.name)
    }
    for (const [routeId, feature] of featureByRouteId) {
      if (!seen.has(routeId)) {
        featureByRouteId.delete(routeId)
        routeSource.removeFeature(feature)
      }
    }
    // 防御性清理:routeSource 由本 composable 独占,不应残留无 routeId 的要素
    for (const feature of routeSource.getFeatures()) {
      if (!feature.get('routeId')) routeSource.removeFeature(feature)
    }
    refreshStyles()
  }

  function teardownDraw() {
    if (!drawInteraction) return
    drawInteraction.abortDrawing() // 丢弃草图,不产生航路
    const map = options.getMap()
    if (map) map.removeInteraction(drawInteraction)
    drawInteraction = null
    if (sketchFeatures) {
      sketchFeatures.clear()
      sketchFeatures = null
    }
  }

  function teardownModify() {
    if (!modifyInteraction) return
    const map = options.getMap()
    if (map) map.removeInteraction(modifyInteraction)
    modifyInteraction = null
    isDragging = false
  }

  function onDrawEnd(event: DrawEvent) {
    const geometry = event.feature.getGeometry()
    if (!(geometry instanceof LineString)) return
    const points = projectedCoordinatesToRoutePoints(geometry.getCoordinates(), options.getCrs())
    if (points.length < ROUTE_MIN_POINTS) {
      ElMessage.warning('航路至少需要两个航路点,已放弃本次绘制')
      store.setInteractionMode('idle')
      return
    }
    const activeId = store.activeRouteId
    if (activeId && store.routes.some((route) => route.id === activeId)) {
      store.replaceRoutePoints(activeId, points)
    } else {
      store.createRouteFromPoints(undefined, points) // 内部自动设为 active
    }
    store.setInteractionMode('idle') // sync watcher 收尾:移除 Draw、清理草图
  }

  function onModifyEnd(feature: Feature<LineString>) {
    isDragging = false
    const geometry = feature.getGeometry()
    const routeId = feature.get('routeId') as string | undefined
    if (!geometry || !routeId) return
    const points = projectedCoordinatesToRoutePoints(geometry.getCoordinates(), options.getCrs())
    if (points.length < ROUTE_MIN_POINTS) return // Modify 不会减少点数,防御
    store.replaceRoutePoints(routeId, points)
  }

  function applyInteractionMode(mode: RouteInteractionMode) {
    teardownDraw()
    teardownModify()
    const map = options.getMap()
    if (!map) return
    if (mode === 'draw') {
      options.deactivateOthers()
      sketchFeatures = new Collection<Feature>()
      drawInteraction = new Draw({
        features: sketchFeatures,
        type: 'LineString',
        minPoints: ROUTE_MIN_POINTS,
        style: sketchStyle(),
      })
      drawInteraction.getOverlay().setZIndex(SKETCH_OVERLAY_Z_INDEX)
      drawInteraction.on('drawend', onDrawEnd)
      map.addInteraction(drawInteraction)
    } else if (mode === 'edit') {
      options.deactivateOthers()
      const activeId = store.activeRouteId
      const feature = activeId ? featureByRouteId.get(activeId) : undefined
      if (!feature) {
        store.setInteractionMode('idle')
        return
      }
      const modifyFeatures = new Collection<Feature>([feature])
      modifyInteraction = new Modify({ features: modifyFeatures })
      modifyInteraction.on('modifystart', () => {
        isDragging = true
      })
      modifyInteraction.on('modifyend', () => {
        onModifyEnd(feature)
      })
      map.addInteraction(modifyInteraction)
    }
    refreshStyles()
  }

  // sync flush:消除「航路 Draw 与测量 Draw 并存」的微任务窗口
  const stopModeWatch = watch(() => store.interactionMode, (mode) => applyInteractionMode(mode), { flush: 'sync' })
  const stopRevisionWatch = watch(() => store.revision, () => reconcileRoutes())

  function syncRoutesToMap() {
    reconcileRoutes()
  }

  function startRouteDraw() {
    store.setInteractionMode('draw')
  }

  function cancelRouteDraw() {
    const active = store.activeRoute
    store.setInteractionMode('idle') // sync watcher → abortDrawing,丢弃草图
    if (active && active.points.length < ROUTE_MIN_POINTS) store.deleteRoute(active.id)
  }

  function removeLastRoutePoint() {
    if (drawInteraction) drawInteraction.removeLastPoint()
  }

  function startRouteModify() {
    const active = store.activeRoute
    if (!active) {
      ElMessage.warning('请先选择一条航路')
      return
    }
    if (active.points.length < ROUTE_MIN_POINTS) {
      ElMessage.warning('航路至少需要两个航路点')
      return
    }
    store.setInteractionMode('edit')
  }

  function stopRouteModify() {
    if (store.interactionMode === 'edit') store.setInteractionMode('idle')
  }

  /** 投影切换后从 Store WGS84 全量重建几何(仿 reloadAisGeometry 范式) */
  function reloadRouteGeometry() {
    if (store.interactionMode !== 'idle') store.setInteractionMode('idle')
    featureByRouteId.clear()
    routeSource.clear()
    reconcileRoutes()
  }

  function fitRoute(routeId: string) {
    const map = options.getMap()
    const feature = featureByRouteId.get(routeId)
    if (!map || !feature) return
    const geometry = feature.getGeometry()
    if (!geometry) return
    const extent = shiftExtentIntoProjection(geometry.getExtent(), options.getCrs())
    map.getView().fit(extent, { padding: ROUTE_FIT_PADDING, maxZoom: 12, duration: 500 })
  }

  /** 点到线段的距离(视空间/投影平面内,与屏幕上看到的直线段一致) */
  function distanceToSegment(point: number[], start: number[], end: number[]): number {
    const dx = end[0]! - start[0]!
    const dy = end[1]! - start[1]!
    const lengthSquared = dx * dx + dy * dy
    if (lengthSquared === 0) return Math.hypot(point[0]! - start[0]!, point[1]! - start[1]!)
    let t = ((point[0]! - start[0]!) * dx + (point[1]! - start[1]!) * dy) / lengthSquared
    t = Math.min(1, Math.max(0, t))
    return Math.hypot(point[0]! - (start[0]! + t * dx), point[1]! - (start[1]! + t * dy))
  }

  /**
   * 点击命中测试(不用 Select interaction,避免与测量/识别交互竞争)。
   *
   * - 只命中 routeLayer 一个图层(layerFilter),不遍历海图图层;
   * - 隐藏航路不会被命中:createRouteStyle 对隐藏航路返回 undefined,要素不进入
   *   渲染重放组,forEachFeatureAtPixel 自然取不到;
   * - 命中后先判航路点(容差更大,便于点中起点/终点标记),再判航段;
   * - 渲染几何的顶点按 seq 升序且已 unwrap,因此「渲染下标 i ↔ 第 i 个航路点」。
   */
  function pickRouteAtPixel(pixel: Pixel, coordinate: number[]): RoutePickResult | null {
    const map = options.getMap()
    if (!map) return null
    if (options.isSelectionEnabled && !options.isSelectionEnabled()) return null
    let result: RoutePickResult | null = null
    map.forEachFeatureAtPixel(
      pixel,
      (feature) => {
        const routeId = feature.get('routeId') as string | undefined
        if (!routeId) return undefined
        store.setActiveRoute(routeId)
        result = { routeId, segmentIndex: null, pointIndex: null }
        return true // 取最上层命中即停
      },
      { layerFilter: (layer) => layer === routeLayer, hitTolerance: ROUTE_HIT_TOLERANCE_PX },
    )
    if (!result) return null
    const picked = result as RoutePickResult
    const feature = featureByRouteId.get(picked.routeId)
    const geometry = feature?.getGeometry()
    const coordinates = geometry?.getCoordinates() ?? []
    if (coordinates.length < ROUTE_MIN_POINTS) return picked
    const resolution = map.getView().getResolution() ?? 0
    const click =
      geometry && options.getCrs() === 'EPSG:3857'
        ? // 3857 可能渲染在另一个世界副本上,先把点击坐标平移到同一副本
          (shiftCoordinateIntoWorldCopyLocal(coordinate, geometry.getExtent()) as number[])
        : coordinate
    const vertexTolerance = ROUTE_VERTEX_HIT_TOLERANCE_PX * resolution
    let nearestVertex = -1
    let nearestVertexDistance = Number.POSITIVE_INFINITY
    for (let i = 0; i < coordinates.length; i++) {
      const distance = Math.hypot(click[0]! - coordinates[i]![0]!, click[1]! - coordinates[i]![1]!)
      if (distance < nearestVertexDistance) {
        nearestVertexDistance = distance
        nearestVertex = i
      }
    }
    if (nearestVertex >= 0 && nearestVertexDistance <= vertexTolerance) {
      return { ...picked, pointIndex: nearestVertex, segmentIndex: null }
    }
    const segmentTolerance = ROUTE_HIT_TOLERANCE_PX * resolution
    let nearestSegment = -1
    let nearestSegmentDistance = Number.POSITIVE_INFINITY
    for (let i = 1; i < coordinates.length; i++) {
      const distance = distanceToSegment(click, coordinates[i - 1]!, coordinates[i]!)
      if (distance < nearestSegmentDistance) {
        nearestSegmentDistance = distance
        nearestSegment = i
      }
    }
    if (nearestSegment >= 1 && nearestSegmentDistance <= segmentTolerance) {
      return { ...picked, segmentIndex: nearestSegment, pointIndex: null }
    }
    return picked
  }

  /** 把坐标平移到与航路渲染几何同一世界副本(仅 3857 需要;3413 原样返回) */
  function shiftCoordinateIntoWorldCopyLocal(coordinate: number[], referenceExtent: Extent): number[] {
    return shiftCoordinateIntoWorldCopy(coordinate, referenceExtent, options.getCrs())
  }

  /** 高亮选中航段(1-based);传 null 清除。仅触发样式重算,不新建几何/图层 */
  function highlightSegment(routeId: string | null, segmentIndex: number | null) {
    highlightedSegment = routeId !== null && segmentIndex !== null ? { routeId, index: segmentIndex } : null
    routeLayer.changed()
  }

  /** 定位并短暂高亮某个航路点:不改数据、不进入绘制/编辑、不触发测量/识别 */
  function locateRoutePoint(routeId: string, pointId: string) {
    const map = options.getMap()
    const route = store.routes.find((item) => item.id === routeId)
    if (!map || !route) return
    // 下标以 seq 升序为准(与渲染几何、点表、航段口径完全一致)
    const index = routePointIndexById(route.points, pointId)
    if (index < 0) return
    // 直接取渲染要素的坐标 —— 它已经处于正确的世界副本,跨 180° 时视觉上合理
    const coordinate = featureByRouteId.get(routeId)?.getGeometry()?.getCoordinates()[index]
    if (!coordinate) return
    if (highlightedPoint) window.clearTimeout(highlightedPoint.timer)
    highlightedPoint = {
      routeId,
      index,
      timer: window.setTimeout(() => {
        highlightedPoint = null
        routeLayer.changed()
      }, ROUTE_POINT_FLASH_MS),
    }
    routeLayer.changed()
    const view = map.getView()
    view.animate({
      center: coordinate,
      zoom: Math.max(view.getZoom() ?? 0, 6),
      duration: 400,
    })
  }

  /** 航路渲染几何的 extent(浮窗锚点对齐世界副本用) */
  function getRouteExtent(routeId: string): [number, number, number, number] | null {
    const geometry = featureByRouteId.get(routeId)?.getGeometry()
    return geometry ? (geometry.getExtent() as [number, number, number, number]) : null
  }

  function dispose() {
    stopModeWatch()
    stopRevisionWatch()
    teardownDraw()
    teardownModify()
    if (highlightedPoint) window.clearTimeout(highlightedPoint.timer)
    highlightedPoint = null
    highlightedSegment = null
    routeSource.clear()
    featureByRouteId.clear()
  }

  return {
    layer: routeLayer,
    source: routeSource,
    syncRoutesToMap,
    pickRouteAtPixel,
    startRouteDraw,
    cancelRouteDraw,
    removeLastRoutePoint,
    startRouteModify,
    stopRouteModify,
    reloadRouteGeometry,
    fitRoute,
    highlightSegment,
    locateRoutePoint,
    getRouteExtent,
    dispose,
  }
}
