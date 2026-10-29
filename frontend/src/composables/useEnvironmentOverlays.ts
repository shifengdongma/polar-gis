/**
 * Environment overlays (bathymetry/wind/current/wave) on the existing map.
 *
 * - Never creates a second map or registers map listeners.
 * - Bathymetry uses the same shared LRU/queue as S-57/ice with generation abort.
 * - Wind/current/wave are authenticated viewport samples rendered as arrows.
 * - All layer state is independent (visibility/loading/error/source/quality).
 */
import { computed, reactive, ref, shallowRef } from 'vue'
import type OlMap from 'ol/Map'
import Feature from 'ol/Feature'
import TileLayer from 'ol/layer/Tile'
import VectorLayer from 'ol/layer/Vector'
import XYZ from 'ol/source/XYZ'
import VectorSource from 'ol/source/Vector'
import TileState from 'ol/TileState'
import { toLonLat } from 'ol/proj'
import { apiErrorMessage } from '../api/client'
import {
  fetchEnvironmentField,
  fetchNavigationSources,
  queryEnvironment,
} from '../api/navigation'
import type {
  DataPolicy,
  EnvironmentField,
  EnvironmentLayerState,
  EnvironmentSource,
  FieldObservation,
} from '../types/navigation'
import type { LRUTileCache } from '../utils/tileCache'
import type { TileRequestQueue } from '../utils/tileRequestQueue'
import { TILE_RETRY_BASE_DELAY_MS, TILE_RETRY_MAX_ATTEMPTS } from '../utils/mapLayerBatch'
import {
  BATHY_MAX_ZOOM,
  ENVIRONMENT_Z_INDEX,
  arrowStyle,
  bathyTileUrl,
  buildArrowFeature,
  createBathyTileGrid,
  environmentBbox,
} from '../utils/mapEnvironment'

export interface EnvironmentOverlaysOptions {
  getMap: () => OlMap | null
  getCrs: () => string
  tileCache: LRUTileCache
  tileRequestQueue: TileRequestQueue
  /** Other map interactions (measure/route/identify) temporarily suppress hover. */
  canQuery: () => boolean
}

export interface EnvironmentTooltipState {
  x: number
  y: number
  flipX: boolean
  flipY: boolean
  longitude: number
  latitude: number
  field: EnvironmentField
  observation: FieldObservation
}

const VECTOR_FIELDS = ['wind', 'current', 'wave'] as const
const ALL_FIELDS: EnvironmentField[] = ['bathymetry', 'ice', 'wind', 'current', 'wave']
const HOVER_DEBOUNCE_MS = 120
const VECTOR_REFRESH_DEBOUNCE_MS = 300

function initialLayerState(): EnvironmentLayerState {
  return {
    visible: false,
    opacity: 0.75,
    loading: false,
    error: '',
    quality: null,
    source: null,
    matchedTime: null,
    available: null,
    reason: null,
  }
}

function defaultRequestedTime(): string {
  const now = new Date()
  now.setUTCMinutes(0, 0, 0)
  return now.toISOString().replace('.000Z', 'Z')
}

export function useEnvironmentOverlays(options: EnvironmentOverlaysOptions) {
  const sources = ref<EnvironmentSource[]>([])
  const sourcesLoading = ref(false)
  /** True once the first sources request has settled (success or failure). */
  const sourcesLoaded = ref(false)
  const sourcesError = ref('')
  const requestedTime = ref(defaultRequestedTime())
  const displayPolicy = ref<DataPolicy>('allow_synthetic_research')
  const layers = reactive<Record<EnvironmentField, EnvironmentLayerState>>({
    bathymetry: initialLayerState(),
    ice: initialLayerState(),
    wind: initialLayerState(),
    current: initialLayerState(),
    wave: initialLayerState(),
  })
  const tooltip = shallowRef<EnvironmentTooltipState | null>(null)

  let bathyLayer: TileLayer<XYZ> | null = null
  let vectorLayers: Record<(typeof VECTOR_FIELDS)[number], VectorLayer<VectorSource>> | null = null
  let attached = false
  let tileGeneration = 0
  const tileControllers = new Set<AbortController>()
  let vectorTimer = 0
  let hoverTimer = 0
  let hoverRequestId = 0
  let hoverController: AbortController | null = null
  const vectorControllers = new Map<string, AbortController>()
  const vectorGenerations = new Map<string, number>()

  const visibleFields = computed(() =>
    ALL_FIELDS.filter((field) => layers[field].visible),
  )
  const anyVisible = computed(() => visibleFields.value.length > 0)

  function abortStaleTiles() {
    tileGeneration += 1
    for (const controller of tileControllers) controller.abort()
    tileControllers.clear()
  }

  function createTileLoader() {
    return (tile: any, src: string) => {
      const generation = tileGeneration
      const image = tile.getImage() as HTMLImageElement
      const controller = new AbortController()
      tileControllers.add(controller)
      const release = () => tileControllers.delete(controller)
      let attempts = 0
      const aborted = () => controller.signal.aborted || generation !== tileGeneration
      tile.addEventListener('change', () => {
        if ((tile as any).getState?.() === TileState.EMPTY) controller.abort()
      })
      const tryLoad = () => {
        if (aborted()) {
          release()
          return
        }
        attempts += 1
        const cached = options.tileCache.get(src)
        if (cached) {
          release()
          const objectUrl = URL.createObjectURL(cached)
          image.onload = () => URL.revokeObjectURL(objectUrl)
          image.src = objectUrl
          return
        }
        options.tileRequestQueue
          .fetch(src, controller.signal)
          .then((response) => {
            if (response.ok) return response.blob()
            if (
              [429, 502, 503, 504].includes(response.status) &&
              attempts < TILE_RETRY_MAX_ATTEMPTS
            ) {
              window.setTimeout(
                tryLoad,
                TILE_RETRY_BASE_DELAY_MS * Math.pow(2, attempts - 1),
              )
              return null
            }
            release()
            tile.setState(TileState.ERROR)
            return null
          })
          .then((blob) => {
            if (!blob || aborted()) {
              release()
              return
            }
            options.tileCache.set(src, blob)
            release()
            const objectUrl = URL.createObjectURL(blob)
            image.onload = () => URL.revokeObjectURL(objectUrl)
            image.src = objectUrl
          })
          .catch((error) => {
            if (aborted()) {
              release()
              return
            }
            if (error instanceof TypeError && attempts < TILE_RETRY_MAX_ATTEMPTS) {
              window.setTimeout(
                tryLoad,
                TILE_RETRY_BASE_DELAY_MS * Math.pow(2, attempts - 1),
              )
            } else {
              release()
              tile.setState(TileState.ERROR)
            }
          })
      }
      tryLoad()
    }
  }

  const loadTile = createTileLoader()

  function attach() {
    const map = options.getMap()
    if (!map || attached) return
    bathyLayer = new TileLayer({
      zIndex: ENVIRONMENT_Z_INDEX.bathymetry,
      visible: false,
      opacity: layers.bathymetry.opacity,
    })
    vectorLayers = {
      wind: new VectorLayer({
        source: new VectorSource(),
        zIndex: ENVIRONMENT_Z_INDEX.wind,
        visible: false,
        style: arrowStyle('wind'),
      }),
      current: new VectorLayer({
        source: new VectorSource(),
        zIndex: ENVIRONMENT_Z_INDEX.current,
        visible: false,
        style: arrowStyle('current'),
      }),
      wave: new VectorLayer({
        source: new VectorSource(),
        zIndex: ENVIRONMENT_Z_INDEX.wave,
        visible: false,
        style: arrowStyle('wave'),
      }),
    }
    map.addLayer(bathyLayer)
    for (const field of VECTOR_FIELDS) {
      const layer = vectorLayers[field]
      // The user may toggle a layer from the overlay menu before the map has
      // finished building.  Re-apply the already-selected state here;
      // otherwise the layer stays invisible until the project is re-entered.
      layer.setVisible(layers[field].visible)
      layer.setOpacity(layers[field].opacity)
      map.addLayer(layer)
    }
    attached = true
    refreshAll()
    if (!sourcesLoaded.value && !sourcesLoading.value) void loadSources()
  }

  function dispose() {
    clearHover()
    abortStaleTiles()
    window.clearTimeout(vectorTimer)
    for (const controller of vectorControllers.values()) controller.abort()
    vectorControllers.clear()
    const map = options.getMap()
    if (bathyLayer) {
      if (map) map.removeLayer(bathyLayer)
      bathyLayer.dispose()
      bathyLayer = null
    }
    if (vectorLayers) {
      for (const field of VECTOR_FIELDS) {
        const layer = vectorLayers[field]
        if (map) map.removeLayer(layer)
        layer.dispose()
      }
      vectorLayers = null
    }
    attached = false
  }

  async function loadSources() {
    if (sourcesLoading.value) return
    sourcesLoading.value = true
    sourcesError.value = ''
    try {
      sources.value = await fetchNavigationSources()
      for (const source of sources.value) {
        layers[source.field].quality = source.quality
        layers[source.field].source = source.source
        layers[source.field].available = source.available
        layers[source.field].reason = source.reason
        layers[source.field].error = source.available
          ? ''
          : source.reason ?? '数据不可用'
      }
    } catch (error) {
      // Keep any previously loaded metadata; a transient failure must not
      // make an already-populated panel look like it has no data.
      sourcesError.value = apiErrorMessage(error, '环境数据源加载失败')
    } finally {
      sourcesLoading.value = false
      sourcesLoaded.value = true
    }
  }

  function bathySource(): XYZ | null {
    if (!layers.bathymetry.visible) return null
    const crs = options.getCrs()
    return new XYZ({
      url: bathyTileUrl(crs),
      projection: crs,
      tileGrid: createBathyTileGrid(crs),
      maxZoom: BATHY_MAX_ZOOM,
      crossOrigin: 'anonymous',
      transition: 0,
      tileLoadFunction: loadTile,
    })
  }

  function refreshBathy() {
    abortStaleTiles()
    if (!bathyLayer) return
    const source = bathySource()
    bathyLayer.setSource(source)
    bathyLayer.setVisible(Boolean(source))
    bathyLayer.setOpacity(layers.bathymetry.opacity)
    if (source) {
      layers.bathymetry.error = ''
      layers.bathymetry.loading = true
      // XYZ has no per-layer load event; the first tile load clears loading via
      // the source's tileloadend listener.
      source.on('tileloadend', () => {
        layers.bathymetry.loading = false
      })
      source.on('tileloaderror', () => {
        layers.bathymetry.loading = false
        layers.bathymetry.error = '水深瓦片加载失败'
      })
    } else {
      layers.bathymetry.loading = false
    }
  }

  async function refreshVector(field: 'wind' | 'current' | 'wave') {
    const map = options.getMap()
    const layer = vectorLayers?.[field]
    if (!map || !layer) return
    if (!layers[field].visible) {
      layer.getSource()?.clear()
      return
    }
    const generation = (vectorGenerations.get(field) ?? 0) + 1
    vectorGenerations.set(field, generation)
    vectorControllers.get(field)?.abort()
    const controller = new AbortController()
    vectorControllers.set(field, controller)
    layers[field].loading = true
    layers[field].error = ''
    const view = map.getView()
    const zoom = Math.round(view.getZoom() ?? 3)
    const bbox = environmentBbox(view.calculateExtent(map.getSize() ?? [800, 600]), options.getCrs())
    try {
      const response = await fetchEnvironmentField(
        {
          field,
          bbox,
          time: requestedTime.value,
          zoom,
          maxPoints: 600,
          dataPolicy: displayPolicy.value,
        },
        controller.signal,
      )
      if (generation !== vectorGenerations.get(field) || controller.signal.aborted) return
      const source = layer.getSource()
      source?.clear()
      const features: Feature[] = []
      for (const point of response.points) {
        const feature = buildArrowFeature(point, options.getCrs(), zoom)
        if (feature) features.push(feature)
      }
      source?.addFeatures(features)
      layers[field].available = response.available
      layers[field].source = response.source
      layers[field].matchedTime = response.matchedTimes[0] ?? null
      layers[field].reason = response.reason
      layers[field].quality =
        response.points.find((point) => point.available)?.quality ?? null
      if (!response.available) layers[field].error = response.reason ?? '数据不可用'
      else if (!features.length) layers[field].error = '当前视口无可用采样点'
    } catch (error) {
      if (controller.signal.aborted) return
      layers[field].error = apiErrorMessage(error, `${field} 数据加载失败`)
    } finally {
      if (generation === vectorGenerations.get(field)) layers[field].loading = false
    }
  }

  function refreshVectors() {
    for (const field of VECTOR_FIELDS) void refreshVector(field)
  }

  function scheduleRefreshVectors() {
    window.clearTimeout(vectorTimer)
    vectorTimer = window.setTimeout(refreshVectors, VECTOR_REFRESH_DEBOUNCE_MS)
  }

  function refreshAll() {
    refreshBathy()
    scheduleRefreshVectors()
  }

  function reloadForProjection() {
    clearHover()
    refreshAll()
  }

  function setVisible(field: EnvironmentField, visible: boolean) {
    layers[field].visible = visible
    if (!visible) {
      clearHover()
      if (field === 'bathymetry') {
        refreshBathy()
      } else if (vectorLayers) {
        const vectorField = field as 'wind' | 'current' | 'wave'
        vectorGenerations.set(vectorField, (vectorGenerations.get(vectorField) ?? 0) + 1)
        vectorControllers.get(vectorField)?.abort()
        vectorLayers[vectorField].setVisible(false)
        vectorLayers[vectorField].getSource()?.clear()
      }
      return
    }
    if (field === 'bathymetry') {
      refreshBathy()
    } else if (vectorLayers) {
      const layer = vectorLayers[field as 'wind' | 'current' | 'wave']
      layer.setVisible(true)
      void refreshVector(field as 'wind' | 'current' | 'wave')
    }
  }

  function toggle(field: EnvironmentField, next?: boolean) {
    setVisible(field, next ?? !layers[field].visible)
  }

  function setOpacity(field: EnvironmentField, opacity: number) {
    layers[field].opacity = opacity
    if (field === 'bathymetry') bathyLayer?.setOpacity(opacity)
    else vectorLayers?.[field as 'wind' | 'current' | 'wave']?.setOpacity(opacity)
  }

  function setTime(value: string) {
    if (!value) return
    requestedTime.value = value.includes('T') ? value : `${value}T00:00:00Z`
    refreshAll()
  }

  function setDisplayPolicy(policy: DataPolicy) {
    displayPolicy.value = policy
    refreshAll()
  }

  function clearHover() {
    window.clearTimeout(hoverTimer)
    hoverController?.abort()
    hoverController = null
    tooltip.value = null
  }

  function handlePointerMove(event: { pixel: number[]; coordinate: number[]; dragging: boolean }) {
    if (event.dragging || !options.canQuery() || !anyVisible.value) {
      clearHover()
      return
    }
    const map = options.getMap()
    if (!map) return
    const coordinate = map.getCoordinateFromPixel(event.pixel)
    const [longitude, latitude] = toLonLat(coordinate, options.getCrs())
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
      clearHover()
      return
    }
    window.clearTimeout(hoverTimer)
    hoverTimer = window.setTimeout(() => {
      void queryHover(event.pixel, longitude, latitude)
    }, HOVER_DEBOUNCE_MS)
  }

  async function queryHover(pixel: number[], longitude: number, latitude: number) {
    const fields = visibleFields.value.filter((field) => field !== 'ice')
    if (!fields.length) return
    hoverController?.abort()
    const controller = new AbortController()
    hoverController = controller
    const requestId = ++hoverRequestId
    try {
      const sample = await queryEnvironment(
        {
          longitude,
          latitude,
          time: requestedTime.value,
          fields,
          dataPolicy: displayPolicy.value,
        },
        controller.signal,
      )
      if (requestId !== hoverRequestId || controller.signal.aborted) return
      const observation =
        fields
          .map((field) => sample.fields[field])
          .find((field) => field?.available) ??
        fields.map((field) => sample.fields[field]).find(Boolean)
      if (!observation) {
        tooltip.value = null
        return
      }
      const map = options.getMap()
      const [width, height] = map?.getSize() ?? [0, 0]
      tooltip.value = {
        x: pixel[0],
        y: pixel[1],
        flipX: pixel[0] > width * 0.62,
        flipY: pixel[1] > height * 0.6,
        longitude,
        latitude,
        field: observation.field,
        observation,
      }
    } catch {
      if (!controller.signal.aborted) tooltip.value = null
    }
  }

  return {
    sources,
    sourcesLoading,
    sourcesLoaded,
    sourcesError,
    requestedTime,
    displayPolicy,
    layers,
    tooltip,
    anyVisible,
    visibleFields,
    loadSources,
    attach,
    dispose,
    reloadForProjection,
    refreshAll,
    scheduleRefreshVectors,
    setVisible,
    toggle,
    setOpacity,
    setTime,
    setDisplayPolicy,
    handlePointerMove,
    clearHover,
  }
}

export type EnvironmentOverlaysApi = ReturnType<typeof useEnvironmentOverlays>

