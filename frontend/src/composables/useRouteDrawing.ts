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
  shiftExtentIntoProjection,
} from '../utils/mapRoute'

/** 高于海图 WMS(10-40),低于测量层(100)与 AIS(110) */
const ROUTE_LAYER_Z_INDEX = 95
/** Draw 内部草图 overlay 默认 zIndex 0,会被海图盖住 —— 抬到航路层之上 */
const SKETCH_OVERLAY_Z_INDEX = 96

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
  selectRouteAtPixel(pixel: Pixel): boolean
  startRouteDraw(): void
  cancelRouteDraw(): void
  removeLastRoutePoint(): void
  startRouteModify(): void
  stopRouteModify(): void
  reloadRouteGeometry(): void
  fitRoute(routeId: string): void
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
  const routeLayer = new VectorLayer({
    source: routeSource,
    zIndex: ROUTE_LAYER_Z_INDEX,
    updateWhileInteracting: true,
    style: createRouteStyle({
      isRouteVisible: (routeId) => store.routes.some((route) => route.id === routeId && route.visible),
      isRouteActive: (routeId) => store.activeRouteId === routeId,
      isRouteEditing: (routeId) => store.interactionMode === 'edit' && store.activeRouteId === routeId,
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
    // 右侧让开航路面板抽屉,左侧让开图层面板
    map.getView().fit(extent, { padding: [90, 470, 90, 420], maxZoom: 12, duration: 500 })
  }

  /** 点击命中测试选航路(不用 Select interaction,避免与测量/识别交互竞争) */
  function selectRouteAtPixel(pixel: Pixel): boolean {
    const map = options.getMap()
    if (!map) return false
    if (options.isSelectionEnabled && !options.isSelectionEnabled()) return false
    let hit = false
    map.forEachFeatureAtPixel(
      pixel,
      (feature) => {
        const routeId = feature.get('routeId') as string | undefined
        if (routeId) {
          store.setActiveRoute(routeId)
          hit = true
          return true // 取最上层命中即停
        }
        return undefined
      },
      { layerFilter: (layer) => layer === routeLayer, hitTolerance: 6 },
    )
    return hit
  }

  function dispose() {
    stopModeWatch()
    stopRevisionWatch()
    teardownDraw()
    teardownModify()
    routeSource.clear()
    featureByRouteId.clear()
  }

  return {
    layer: routeLayer,
    source: routeSource,
    syncRoutesToMap,
    selectRouteAtPixel,
    startRouteDraw,
    cancelRouteDraw,
    removeLastRoutePoint,
    startRouteModify,
    stopRouteModify,
    reloadRouteGeometry,
    fitRoute,
    dispose,
  }
}
