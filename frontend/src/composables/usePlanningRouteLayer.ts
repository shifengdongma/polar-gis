/** Candidate/recommended planning routes on the existing map (independent layer). */
import { shallowRef } from 'vue'
import type OlMap from 'ol/Map'
import Feature from 'ol/Feature'
import type LineString from 'ol/geom/LineString'
import VectorLayer from 'ol/layer/Vector'
import VectorSource from 'ol/source/Vector'
import { Style, Stroke } from 'ol/style'
import type { Extent } from 'ol/extent'
import type { PlanningRoute } from '../types/navigation'
import type { RoutePoint } from '../types'
import { buildRouteLineString, shiftExtentIntoProjection } from '../utils/mapRoute'

export const PLANNING_ROUTE_Z_INDEX = 90
const CANDIDATE_COLORS = ['#9fbcc6', '#e89b27', '#8fb8c9', '#c792ea', '#7dd3a7']

export interface PlanningRouteLayerOptions {
  getMap: () => OlMap | null
  getCrs: () => string
  getFitPadding: () => [number, number, number, number]
}

export interface PlanningRouteLayerApi {
  layer: VectorLayer<VectorSource>
  attach: () => void
  dispose: () => void
  setRoutes: (routes: PlanningRoute[], selectedId?: string | null) => void
  setSelected: (routeId: string | null) => void
  reloadForProjection: () => void
  pickRouteAtPixel: (pixel: number[]) => string | null
  fitRoute: (routeId: string) => void
  clear: () => void
}

export function usePlanningRouteLayer(options: PlanningRouteLayerOptions): PlanningRouteLayerApi {
  const source = new VectorSource()
  const layer = new VectorLayer({
    source,
    zIndex: PLANNING_ROUTE_Z_INDEX,
    style: (feature) => routeStyle(feature as Feature<LineString>),
  })
  const routes = shallowRef<PlanningRoute[]>([])
  let selectedId: string | null = null
  let attached = false

  function attach() {
    const map = options.getMap()
    if (!map || attached) return
    map.addLayer(layer)
    attached = true
  }

  function dispose() {
    const map = options.getMap()
    if (map) map.removeLayer(layer)
    source.clear()
    layer.dispose()
    attached = false
  }

  function setRoutes(next: PlanningRoute[], nextSelected: string | null = null) {
    routes.value = next
    selectedId = nextSelected ?? next.find((route) => route.recommended)?.routeId ?? next[0]?.routeId ?? null
    rebuild()
  }

  function setSelected(routeId: string | null) {
    selectedId = routeId
    layer.changed()
  }

  function reloadForProjection() {
    rebuild()
  }

  function rebuild() {
    source.clear()
    const crs = options.getCrs()
    routes.value.forEach((route, index) => {
      const points: RoutePoint[] = route.coordinates.map(([lon, lat], pointIndex) => ({
        id: `${route.routeId}-${pointIndex}`,
        seq: pointIndex + 1,
        lon,
        lat,
      }))
      const geometry = buildRouteLineString(points, crs)
      if (!geometry) return
      const feature = new Feature({ geometry })
      feature.setProperties({
        routeId: route.routeId,
        planId: route.planId,
        label: route.label,
        recommended: route.recommended,
        candidateIndex: index,
        selected: route.routeId === selectedId,
      })
      source.addFeature(feature)
    })
    layer.changed()
  }

  function pickRouteAtPixel(pixel: number[]): string | null {
    const map = options.getMap()
    if (!map) return null
    let hit: string | null = null
    map.forEachFeatureAtPixel(
      pixel,
      (feature) => {
        const routeId = feature.get('routeId')
        if (typeof routeId === 'string') hit = routeId
        return true
      },
      {
        layerFilter: (candidate) => candidate === layer,
        hitTolerance: 7,
      },
    )
    return hit
  }

  function fitRoute(routeId: string) {
    const map = options.getMap()
    if (!map) return
    const feature = source.getFeatures().find((item) => item.get('routeId') === routeId)
    const geometry = feature?.getGeometry()
    if (!geometry) return
    const extent = shiftExtentIntoProjection(geometry.getExtent() as Extent, options.getCrs())
    map.getView().fit(extent, {
      padding: options.getFitPadding(),
      duration: 420,
      maxZoom: 8,
    })
  }

  function clear() {
    routes.value = []
    selectedId = null
    source.clear()
  }

  function routeStyle(feature: Feature<LineString>): Style {
    const routeId = String(feature.get('routeId') ?? '')
    const recommended = Boolean(feature.get('recommended'))
    const selected = routeId === selectedId
    const candidateIndex = Number(feature.get('candidateIndex') ?? 0)
    const color = recommended
      ? '#35c3d6'
      : CANDIDATE_COLORS[candidateIndex % CANDIDATE_COLORS.length]
    return new Style({
      stroke: new Stroke({
        color: selected ? '#ffd166' : color,
        width: selected ? 5 : recommended ? 3.5 : 2.2,
        lineDash: recommended ? undefined : [9, 6],
        lineCap: 'round',
      }),
      zIndex: selected ? 20 : recommended ? 10 : 0,
    })
  }

  return {
    layer,
    attach,
    dispose,
    setRoutes,
    setSelected,
    reloadForProjection,
    pickRouteAtPixel,
    fitRoute,
    clear,
  }
}
