<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft,
  Camera,
  CaretBottom,
  CaretRight,
  Check,
  Close,
  DataAnalysis,
  Expand,
  Fold,
  FullScreen,
  Location,
  MapLocation,
  MoreFilled,
  Operation,
  Printer,
  Search,
  WarningFilled,
} from '@element-plus/icons-vue'
import OlMap from 'ol/Map'
import View from 'ol/View'
import Feature from 'ol/Feature'
import Point from 'ol/geom/Point'
import Draw from 'ol/interaction/Draw'
import TileLayer from 'ol/layer/Tile'
import BaseLayer from 'ol/layer/Base'
import VectorLayer from 'ol/layer/Vector'
import OSM from 'ol/source/OSM'
import TileWMS from 'ol/source/TileWMS'
import WMTS, { optionsFromCapabilities } from 'ol/source/WMTS'
import XYZ from 'ol/source/XYZ'
import VectorSource from 'ol/source/Vector'
import WMTSCapabilities from 'ol/format/WMTSCapabilities'
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style'
import { getArea, getLength } from 'ol/sphere'
import { fromLonLat, toLonLat, transformExtent } from 'ol/proj'
import { get as getProjection } from 'ol/proj'
import { register } from 'ol/proj/proj4'
import proj4 from 'proj4'
import { api, apiErrorMessage } from '../api/client'
import { resolveProjectMapLayers } from '../api/projects'
import WeatherChart from '../components/WeatherChart.vue'
import { useProjectsStore } from '../stores/projects'
import type {
  BaseMapRecord,
  BulkLayerProgress,
  BulkResolvedLayer,
  LayerRecord,
  MapConfig,
  MapDatasetConfig,
  MapLayerConfig,
  S57LoadProfile,
} from '../types'
import {
  BULK_ATTACH_BATCH_SIZE,
  BULK_ATTACH_INTERVAL_MS,
  BULK_HARD_LIMIT,
  evaluateBulkThreshold,
  prepareAttachCandidates,
  transformLayerExtent,
  waitForBulkInterval,
  PerLayerStatsManager,
  SMART_RECONCILE_DEBOUNCE_MS,
  SMART_SUSPEND_EVICT_DELAY_MS,
  SMART_MAX_ATTACHED_WMS_LAYERS,
} from '../utils/mapLayerBatch'
import {
  buildRenderPlan,
  isLayerInViewport,
  type ChartRenderMode,
  type ResolvedLayerMeta,
} from '../utils/mapRenderScheduler'
import type { MapTilePerformanceStats } from '../types'
import { parseWgs84Extent } from '../utils/mapExtent'
import { s57LayerTitle } from '../utils/s57ObjectNames'

interface RuntimeLayer {
  config: MapLayerConfig
  visible: boolean
  opacity: number
  loadState: 'idle' | 'loading' | 'loaded' | 'error'
  pendingTiles: number
  loadStateTimer?: number
  datasetId?: string
}

interface RuntimeDataset {
  config: MapDatasetConfig
  expanded: boolean
  loading: boolean
  loaded: boolean
  layers: RuntimeLayer[]
}

interface WeatherPoint {
  forecastAt: string
  temperatureC: number
  windSpeedMs: number
  windDirectionDeg: number
  waveHeightM: number
}

const route = useRoute()
const router = useRouter()
const projectsStore = useProjectsStore()
const mapTarget = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const config = ref<MapConfig | null>(null)
const baseMaps = ref<BaseMapRecord[]>([])
const activeBaseMapId = ref('')
const currentCrs = ref('EPSG:3857')
const runtimeLayers = ref<RuntimeLayer[]>([])
const runtimeDatasets = ref<RuntimeDataset[]>([])
const layerSearch = ref('')
const layerSearchDebounced = ref('')
let layerSearchTimer: number | undefined
const layerPanelCollapsed = ref(false)
const aisVisible = ref(false)
const coordinateText = ref('—')
const measureText = ref('')
const queryMode = ref(false)
const weatherMode = ref(false)
const weatherVisible = ref(false)
const weatherItems = ref<WeatherPoint[]>([])
const weatherCoordinate = ref<[number, number] | null>(null)
const attributeVisible = ref(false)
const attributeRows = ref<Record<string, unknown>[]>([])
const attributeLayer = ref<MapLayerConfig | null>(null)
const attributeLoading = ref(false)
const attributePage = ref(1)
const attributeTotal = ref(0)
const attributeAllowedFields = ref<string[]>([])
const attributeFilterField = ref('')
const attributeFilterValue = ref('')
const attributeSearchController = ref<AbortController | null>(null)
const identifyVisible = ref(false)
const identifyItems = ref<Record<string, unknown>[]>([])
const identifyController = ref<AbortController | null>(null)
const metadataVisible = ref(false)
const metadataLayer = ref<LayerRecord | null>(null)
const legendUrl = ref('')

// ── Batch loading state ────────────────────────────────────────────
const selectedDatasetIds = ref(new Set<string>())
/** Layer IDs the user has turned ON (selected). */
const selectedLayerIds = ref(new Set<string>())
/** Layer IDs with active OpenLayers TileLayer objects. */
const attachedLayerIds = ref(new Set<string>())
/** Layer IDs currently visible and allowed to request tiles. */
const activeLayerIds = ref(new Set<string>())
/** Layer IDs waiting for their first tile to load. */
const warmingLayerIds = ref(new Set<string>())
/** Layer IDs that are selected but temporarily sleeping (viewport/scale/budget). */
const suspendedLayerIds = ref(new Set<string>())
/** Layer IDs the user explicitly forced to display, immune to smart suspend. */
const manuallyForcedLayerIds = ref(new Set<string>())
/** Backward-compat alias: layers the user has turned on. */
const loadedLayerIds = selectedLayerIds
const loadingLayerIds = ref(new Set<string>())
const failedLayerIds = ref(new Map<string, string>())
const renderMode = ref<ChartRenderMode>('smart')
const bulkProgress = ref<BulkLayerProgress | null>(null)
const bulkCancelled = ref(false)
const bulkGeneration = ref(0)
const renderGeneration = ref(0)
const lastBulkAttachedLayerIds = ref(new Set<string>())
let bulkAbortController: AbortController | null = null
let reconcileTimer: number | undefined
let evictTimer: number | undefined
const layerLastInViewportTime = new Map<string, number>()

// ── Performance stats (lightweight, no console spam) ──────────────────
const perfStats = new PerLayerStatsManager()
const perfDisplay = ref<MapTilePerformanceStats | null>(null)
const devShowPerfDetail = ref(false)
let perfPollTimer: number | undefined

function updatePerfDisplay() {
  perfDisplay.value = perfStats.snapshot(
    activeLayerIds.value.size,
    attachedLayerIds.value.size,
    suspendedLayerIds.value.size,
    bulkGeneration.value,
  )
}

function startPerfPoll() {
  updatePerfDisplay()
  perfPollTimer = window.setInterval(updatePerfDisplay, 5000)
}

function stopPerfPoll() {
  window.clearInterval(perfPollTimer)
  perfPollTimer = undefined
}

/** Only S-57 datasets are eligible for batch operations. */
const isS57Dataset = (dataset: RuntimeDataset) => dataset.config.dataType === 's57'

const selectedDatasetCount = computed(() => selectedDatasetIds.value.size)

const currentFilteredDatasetIds = computed(() => {
  const ids = new Set<string>()
  for (const [, datasets] of filteredGroups.value) {
    for (const dataset of datasets) {
      ids.add(dataset.config.id)
    }
  }
  return ids
})

function selectFilteredDatasets() {
  const next = new Set(selectedDatasetIds.value)
  for (const id of currentFilteredDatasetIds.value) {
    next.add(id)
  }
  selectedDatasetIds.value = next
}

function clearDatasetSelection() {
  selectedDatasetIds.value = new Set()
}

function toggleDatasetSelection(datasetId: string) {
  const next = new Set(selectedDatasetIds.value)
  if (next.has(datasetId)) next.delete(datasetId)
  else next.add(datasetId)
  selectedDatasetIds.value = next
}

proj4.defs('EPSG:3413', '+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +datum=WGS84 +units=m +no_defs')
register(proj4)
getProjection('EPSG:3413')?.setExtent([-4194304, -4194304, 4194304, 4194304])

let map: OlMap | null = null
let fallbackBaseLayer: TileLayer<OSM> | null = null
let measureInteraction: Draw | null = null
const wmsLayers = new globalThis.Map<string, TileLayer<TileWMS>>()
const configuredBaseLayers = new globalThis.Map<string, TileLayer<XYZ | WMTS>>()
const measureSource = new VectorSource()
const aisSource = new VectorSource()
const measureLayer = new VectorLayer({
  source: measureSource,
  zIndex: 100,
  style: new Style({
    stroke: new Stroke({ color: '#35c3d6', width: 3 }),
    fill: new Fill({ color: 'rgba(53,195,214,.18)' }),
    image: new CircleStyle({ radius: 5, fill: new Fill({ color: '#35c3d6' }) }),
  }),
})
const aisLayer = new VectorLayer({
  source: aisSource,
  visible: false,
  zIndex: 110,
  style: new Style({
    image: new CircleStyle({ radius: 7, fill: new Fill({ color: '#e89b27' }), stroke: new Stroke({ color: '#fff', width: 2 }) }),
  }),
})

watch(layerSearch, () => {
  window.clearTimeout(layerSearchTimer)
  layerSearchTimer = window.setTimeout(() => {
    layerSearchDebounced.value = layerSearch.value
  }, 200)
})

const filteredGroups = computed(() => {
  const keyword = layerSearchDebounced.value.trim().toLocaleLowerCase()
  const groups = new globalThis.Map<string, RuntimeDataset[]>()
  for (const dataset of runtimeDatasets.value) {
    const matchesDataset = [dataset.config.name, dataset.config.code]
      .some((value) => value.toLocaleLowerCase().includes(keyword))
    const matchesLayer = dataset.layers.some((layer) =>
      [layer.config.name, layer.config.code, layer.config.serviceLayerName]
        .some((value) => value.toLocaleLowerCase().includes(keyword)),
    )
    const matchesGroup = dataset.config.groupName.toLocaleLowerCase().includes(keyword)
    if (keyword && !matchesDataset && !matchesLayer && !matchesGroup) continue
    const group = groups.get(dataset.config.groupName) || []
    group.push(dataset)
    groups.set(dataset.config.groupName, group)
  }
  return [...groups.entries()]
})

const hasFilteredLayers = computed(() => filteredGroups.value.some(([, layers]) => layers.length > 0))

const attributeColumns = computed(() => {
  const first = attributeRows.value[0]
  return first ? Object.keys(first).filter((key) => key !== 'geometry') : []
})

const availableBaseMaps = computed(() =>
  baseMaps.value.filter((baseMap) => baseMap.crs === currentCrs.value),
)

function createView(crs: string) {
  return new View({
    projection: crs,
    center: fromLonLat([80, 72], crs),
    zoom: crs === 'EPSG:3413' ? 3 : 4,
    minZoom: 2,
  })
}

function fitProjectInitialExtent() {
  const extent = parseWgs84Extent(config.value?.project.initialExtent || null)
  if (!map || !extent) return
  map.getView().fit(transformExtent(extent, 'EPSG:4326', currentCrs.value), {
    padding: [70, 70, 70, 390],
    duration: 0,
  })
}

function browserGeoServerUrl(serviceUrl: string) {
  if (serviceUrl.startsWith('/')) return serviceUrl
  try {
    const parsed = new URL(serviceUrl, window.location.origin)
    const geoserverIndex = parsed.pathname.indexOf('/geoserver')
    return geoserverIndex >= 0 ? parsed.pathname.slice(geoserverIndex) : serviceUrl
  } catch {
    return serviceUrl
  }
}

async function createConfiguredBaseLayers() {
  const layers: BaseLayer[] = []
  for (const baseMap of baseMaps.value) {
    try {
      let tileLayer: TileLayer<XYZ | WMTS>
      if (baseMap.mapType === 'WMTS') {
        const response = await fetch(baseMap.urlTemplate)
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const capabilities = new WMTSCapabilities().read(await response.text())
        const capabilityLayer = capabilities.Contents?.Layer?.[0]
        const matrixSet = capabilityLayer?.TileMatrixSetLink?.[0]?.TileMatrixSet
        if (!capabilityLayer?.Identifier || !matrixSet) throw new Error('Capabilities缺少图层或矩阵集')
        const options = optionsFromCapabilities(capabilities, {
          layer: capabilityLayer.Identifier,
          matrixSet,
        })
        if (!options) throw new Error('无法生成WMTS配置')
        tileLayer = new TileLayer({
          className: 'map-base-layer',
          opacity: 0.88,
          source: new WMTS({ ...options, crossOrigin: 'anonymous' }),
        })
      } else {
        tileLayer = new TileLayer({
          className: 'map-base-layer',
          opacity: 0.88,
          source: new XYZ({
            url: baseMap.urlTemplate,
            projection: baseMap.crs,
            crossOrigin: 'anonymous',
            attributions: baseMap.attribution || undefined,
          }),
        })
      }
      tileLayer.setVisible(false)
      configuredBaseLayers.set(baseMap.id, tileLayer)
      layers.push(tileLayer)
    } catch {
      ElMessage.warning(`底图“${baseMap.name}”加载失败，已与业务图层隔离`)
    }
  }
  return layers
}

function applyBaseMapVisibility() {
  const choices = availableBaseMaps.value.filter((item) => configuredBaseLayers.has(item.id))
  if (!choices.some((item) => item.id === activeBaseMapId.value)) {
    activeBaseMapId.value = choices[0]?.id || ''
  }
  for (const [id, layer] of configuredBaseLayers) {
    layer.setVisible(id === activeBaseMapId.value)
  }
  fallbackBaseLayer?.setVisible(!activeBaseMapId.value && currentCrs.value === 'EPSG:3857')
}

function selectBaseMap() {
  applyBaseMapVisibility()
}

async function buildMap() {
  if (!mapTarget.value || !config.value) return
  fallbackBaseLayer = new TileLayer({
    className: 'map-base-layer',
    opacity: 0.88,
    source: new OSM({ crossOrigin: 'anonymous' }),
    visible: false,
  })
  const layers: BaseLayer[] = [fallbackBaseLayer, ...(await createConfiguredBaseLayers())]
  map = new OlMap({ target: mapTarget.value, layers, view: createView(currentCrs.value) })
  for (const runtime of runtimeLayers.value) {
    if (runtime.visible) {
      attachWmsLayer(runtime)
      const next = new Set(selectedLayerIds.value)
      next.add(runtime.config.id)
      selectedLayerIds.value = next
    }
  }
  map.addLayer(measureLayer)
  map.addLayer(aisLayer)
  applyBaseMapVisibility()
  fitProjectInitialExtent()
  map.on('pointermove', (event) => {
    const [longitude, latitude] = toLonLat(event.coordinate, currentCrs.value)
    coordinateText.value = `${latitude.toFixed(5)}°, ${longitude.toFixed(5)}°`
  })
  map.on('singleclick', async (event) => {
    const lonLat = toLonLat(event.coordinate, currentCrs.value) as [number, number]
    if (weatherMode.value) await queryWeather(lonLat)
    else if (queryMode.value) await identify(lonLat)
  })
  map.on('moveend', () => {
    window.clearTimeout(reconcileTimer)
    reconcileTimer = window.setTimeout(reconcileRenderPlan, SMART_RECONCILE_DEBOUNCE_MS)
  })
  // Initial reconcile
  reconcileRenderPlan()
}

function isNonSpatial(layer: MapLayerConfig): boolean {
  const t = (layer.geometryType || '').toLowerCase()
  return t === 'unknown' || t === 'none' || t === '' || t === '无'
}

type AttachResult = 'attached' | 'already-loaded' | 'non-spatial'

function attachWmsLayer(
  runtime: RuntimeLayer,
  opts?: { extent?: number[]; minZoom?: number | null; maxZoom?: number | null; visible?: boolean },
): AttachResult {
  if (!map || wmsLayers.has(runtime.config.id)) return 'already-loaded'
  if (isNonSpatial(runtime.config)) {
    runtime.loadState = 'loaded'
    return 'non-spatial'
  }
  const source = new TileWMS({
    url: browserGeoServerUrl(runtime.config.serviceUrl),
    params: { LAYERS: runtime.config.serviceLayerName, TILED: true, STYLES: runtime.config.styleName || '' },
    crossOrigin: 'anonymous',
    transition: 0,
  })
  source.on('tileloadstart', () => {
    runtime.pendingTiles += 1
    perfStats.recordTileStart(runtime.config.id)
    window.clearTimeout(runtime.loadStateTimer)
    runtime.loadStateTimer = window.setTimeout(() => {
      if (runtime.pendingTiles > 0) {
        runtime.loadState = 'loading'
      }
    }, 300)
  })
  source.on('tileloadend', () => {
    runtime.pendingTiles = Math.max(0, runtime.pendingTiles - 1)
    perfStats.recordTileEnd(runtime.config.id)
    if (runtime.pendingTiles === 0) {
      window.clearTimeout(runtime.loadStateTimer)
      if (runtime.loadState !== 'error') runtime.loadState = 'loaded'
    }
  })
  source.on('tileloaderror', () => {
    runtime.pendingTiles = Math.max(0, runtime.pendingTiles - 1)
    perfStats.recordTileError(runtime.config.id)
    window.clearTimeout(runtime.loadStateTimer)
    runtime.loadState = 'error'
  })
  const tileLayer = new TileLayer({
    source,
    opacity: runtime.opacity,
    zIndex: 10,
    extent: opts?.extent,
    minZoom: opts?.minZoom ?? undefined,
    maxZoom: opts?.maxZoom ?? undefined,
    visible: opts?.visible ?? true,
  })
  wmsLayers.set(runtime.config.id, tileLayer)
  map.addLayer(tileLayer)
  // Track in state sets (unless the caller is doing batch management)
  const lid = runtime.config.id
  if (!attachedLayerIds.value.has(lid)) {
    const nextAtt = new Set(attachedLayerIds.value)
    nextAtt.add(lid)
    attachedLayerIds.value = nextAtt
  }
  if (opts?.visible !== false) {
    const nextAct = new Set(activeLayerIds.value)
    nextAct.add(lid)
    activeLayerIds.value = nextAct
  }
  return 'attached'
}

function detachWmsLayer(runtime: RuntimeLayer) {
  const tileLayer = wmsLayers.get(runtime.config.id)
  if (!tileLayer || !map) return
  map.removeLayer(tileLayer)
  tileLayer.dispose()
  wmsLayers.delete(runtime.config.id)
  window.clearTimeout(runtime.loadStateTimer)
  runtime.pendingTiles = 0
  runtime.loadState = 'idle'
  runtime.loadStateTimer = undefined
  // Clean up from state sets
  const lid = runtime.config.id
  const nextAtt = new Set(attachedLayerIds.value)
  nextAtt.delete(lid)
  attachedLayerIds.value = nextAtt
  const nextAct = new Set(activeLayerIds.value)
  nextAct.delete(lid)
  activeLayerIds.value = nextAct
  const nextWarm = new Set(warmingLayerIds.value)
  nextWarm.delete(lid)
  warmingLayerIds.value = nextWarm
  const nextSus = new Set(suspendedLayerIds.value)
  nextSus.delete(lid)
  suspendedLayerIds.value = nextSus
  layerLastInViewportTime.delete(lid)
}

async function toggleDataset(dataset: RuntimeDataset) {
  dataset.expanded = !dataset.expanded
  if (!dataset.expanded || dataset.loaded || dataset.loading || !config.value) return
  dataset.loading = true
  try {
    const response = await api.get<MapLayerConfig[]>(
      `/projects/${config.value.project.id}/map-datasets/${dataset.config.id}/layers`,
    )
    dataset.layers = response.data.map((layer) => ({
      config: layer,
      visible: false,
      opacity: layer.opacity,
      loadState: 'idle' as const,
      pendingTiles: 0,
      datasetId: dataset.config.id,
    }))
    runtimeLayers.value.push(...dataset.layers)
    dataset.loaded = true
  } catch (error) {
    dataset.expanded = false
    ElMessage.error(apiErrorMessage(error, '图层目录加载失败'))
  } finally {
    dataset.loading = false
  }
}

function toggleLayer(runtime: RuntimeLayer) {
  runtime.visible = !runtime.visible
  const lid = runtime.config.id
  if (runtime.visible) {
    // User selected
    const next = new Set(selectedLayerIds.value)
    next.add(lid)
    selectedLayerIds.value = next
    // In standard mode, attach immediately. In smart, scheduler handles it.
    if (renderMode.value === 'standard') {
      attachWmsLayer(runtime)
      const nextAtt = new Set(attachedLayerIds.value)
      nextAtt.add(lid)
      attachedLayerIds.value = nextAtt
      const nextAct = new Set(activeLayerIds.value)
      nextAct.add(lid)
      activeLayerIds.value = nextAct
    } else {
      reconcileRenderPlan()
    }
  } else {
    // User deselected
    const next = new Set(selectedLayerIds.value)
    next.delete(lid)
    selectedLayerIds.value = next
    const nextAtt = new Set(attachedLayerIds.value)
    if (nextAtt.has(lid)) {
      // Detach immediately for responsiveness
      detachWmsLayer(runtime)
      nextAtt.delete(lid)
      attachedLayerIds.value = nextAtt
    }
    // Clean up from other sets
    const nextAct = new Set(activeLayerIds.value)
    nextAct.delete(lid)
    activeLayerIds.value = nextAct
    const nextSus = new Set(suspendedLayerIds.value)
    nextSus.delete(lid)
    suspendedLayerIds.value = nextSus
    const nextForce = new Set(manuallyForcedLayerIds.value)
    nextForce.delete(lid)
    manuallyForcedLayerIds.value = nextForce
  }
}

function updateOpacity(runtime: RuntimeLayer) {
  wmsLayers.get(runtime.config.id)?.setOpacity(runtime.opacity)
}

function switchProjection(crs: string) {
  if (!map || crs === currentCrs.value) return
  renderGeneration.value += 1
  // Save currently selected layer IDs
  const savedSelectedIds = new Set(selectedLayerIds.value)
  // Detach all WMS layers in old projection
  for (const runtime of runtimeLayers.value) {
    if (wmsLayers.has(runtime.config.id)) {
      detachWmsLayer(runtime)
    }
  }
  currentCrs.value = crs
  applyBaseMapVisibility()
  map.setView(createView(crs))
  fitProjectInitialExtent()
  reloadAisGeometry()
  // Re-attach only previously selected layers
  for (const runtime of runtimeLayers.value) {
    if (savedSelectedIds.has(runtime.config.id)) {
      runtime.visible = true
      const extent = transformLayerExtent(runtime.config.extent, currentCrs.value)
      attachWmsLayer(runtime, {
        extent,
        minZoom: runtime.config.minZoom,
        maxZoom: runtime.config.maxZoom,
      })
    }
  }
  // Restore selectedLayerIds (they survive the projection switch)
  selectedLayerIds.value = savedSelectedIds
  // Recalculate render plan for new projection
  reconcileRenderPlan()
}

// ── Layer status display ──────────────────────────────────────────

function layerStatusLabel(layerId: string): string {
  if (failedLayerIds.value.has(layerId)) return '加载失败'
  if (warmingLayerIds.value.has(layerId)) return '加载中'
  if (activeLayerIds.value.has(layerId)) return '已显示'
  if (suspendedLayerIds.value.has(layerId)) {
    // Check specific suspension reasons if available
    if (!isLayerInViewport(
      runtimeLayers.value.find((r) => r.config.id === layerId)?.config?.extent,
      [0, 0, 0, 0],
      currentCrs.value,
    )) {
      // This is a rough check — the exact reason comes from RenderPlan
    }
    return '视口外休眠'
  }
  if (selectedLayerIds.value.has(layerId) && !attachedLayerIds.value.has(layerId)) return '等待加载'
  if (attachedLayerIds.value.has(layerId) && !activeLayerIds.value.has(layerId)) return '休眠'
  if (runtimeLayers.value.find((r) => r.config.id === layerId)?.loadState === 'loading') return '加载中'
  return ''
}

// ── Render plan reconciliation (smart mode scheduler) ─────────────

function buildResolvedLayerMeta(): ResolvedLayerMeta[] {
  return runtimeLayers.value.map((r) => ({
    id: r.config.id,
    extent: r.config.extent ?? null,
    minZoom: r.config.minZoom ?? null,
    maxZoom: r.config.maxZoom ?? null,
    displayPriority: r.config.sortOrder ?? 900,
    objectClass: r.config.objectClass ?? null,
    loadProfile: '',
    minScaleDenominator: (r.config.metadata as any)?.s57?.minScaleDenominator ?? null,
    maxScaleDenominator: (r.config.metadata as any)?.s57?.maxScaleDenominator ?? null,
    renderCost: (r.config.metadata as any)?.s57?.renderCost ?? null,
  }))
}

function reconcileRenderPlan() {
  if (!map || renderMode.value === 'standard') return

  const view = map.getView()
  if (!view) return
  const size = map.getSize()
  if (!size) return

  const extent = view.calculateExtent(size) as number[]
  const zoom = view.getZoom() ?? 4
  const resolution = view.getResolution() ?? 10000

  const overviewAvail = baseMaps.value.some(
    (b) => b.name.includes('全球海图概览') && b.crs === currentCrs.value && b.isEnabled,
  )

  const plan = buildRenderPlan({
    selectedLayerIds: selectedLayerIds.value,
    attachedLayerIds: attachedLayerIds.value,
    activeLayerIds: activeLayerIds.value,
    warmingLayerIds: warmingLayerIds.value,
    manuallyForcedLayerIds: manuallyForcedLayerIds.value,
    layers: buildResolvedLayerMeta(),
    currentProjection: currentCrs.value,
    viewExtent: extent,
    zoom,
    resolution,
    renderMode: renderMode.value,
    overviewAvailable: overviewAvail,
  })

  // Execute plan
  for (const id of plan.detach) {
    const runtime = runtimeLayers.value.find((r) => r.config.id === id)
    if (runtime) detachWmsLayer(runtime)
  }

  for (const id of plan.suspend) {
    const layer = wmsLayers.get(id)
    if (layer) layer.setVisible(false)
    const nextSus = new Set(suspendedLayerIds.value)
    nextSus.add(id)
    suspendedLayerIds.value = nextSus
    const nextAct = new Set(activeLayerIds.value)
    nextAct.delete(id)
    activeLayerIds.value = nextAct
  }

  for (const id of plan.attach) {
    const runtime = runtimeLayers.value.find((r) => r.config.id === id)
    if (!runtime || attachedLayerIds.value.has(id)) continue
    const extent = transformLayerExtent(runtime.config.extent, currentCrs.value)
    attachWmsLayer(runtime, {
      extent,
      minZoom: runtime.config.minZoom,
      maxZoom: runtime.config.maxZoom,
      visible: false,
    })
    const nextWarm = new Set(warmingLayerIds.value)
    nextWarm.add(id)
    warmingLayerIds.value = nextWarm
    layerLastInViewportTime.set(id, Date.now())
  }

  for (const id of plan.activate) {
    const layer = wmsLayers.get(id)
    if (layer) layer.setVisible(true)
    const nextAct = new Set(activeLayerIds.value)
    nextAct.add(id)
    activeLayerIds.value = nextAct
    const nextSus = new Set(suspendedLayerIds.value)
    nextSus.delete(id)
    suspendedLayerIds.value = nextSus
    layerLastInViewportTime.set(id, Date.now())
  }

  // Update overview WMTS visibility
  setOverviewVisible(plan.overviewVisible)

  // Schedule LRU eviction check
  window.clearTimeout(evictTimer)
  evictTimer = window.setTimeout(runLruEviction, SMART_SUSPEND_EVICT_DELAY_MS)
}

function setOverviewVisible(visible: boolean) {
  // Toggle the polar_global_enc_overview basemap visibility
  for (const bm of baseMaps.value) {
    if (bm.name.includes('全球海图概览') && bm.crs === currentCrs.value) {
      // Make visible/invisible alongside the active base map
      if (visible && bm.id !== activeBaseMapId.value) {
        // Show overview WMTS as overlay
      }
    }
  }
}

function runLruEviction() {
  const protectedIds = new Set([
    ...manuallyForcedLayerIds.value,
    // Also protect layers with open attribute tables
    ...(attributeLayer.value ? [attributeLayer.value.id] : []),
  ])

  const now = Date.now()
  const evictable = [...suspendedLayerIds.value]
    .filter((id) => !protectedIds.has(id))
    .filter((id) => attachedLayerIds.value.has(id))
    .filter((id) => !selectedLayerIds.value.has(id))
    .filter((id) => (now - (layerLastInViewportTime.get(id) ?? 0)) > SMART_SUSPEND_EVICT_DELAY_MS)
    .sort(
      (a, b) => (layerLastInViewportTime.get(a) ?? 0) - (layerLastInViewportTime.get(b) ?? 0),
    )

  const excess = attachedLayerIds.value.size - SMART_MAX_ATTACHED_WMS_LAYERS
  if (excess <= 0) return

  for (let i = 0; i < Math.min(excess, evictable.length); i++) {
    const runtime = runtimeLayers.value.find((r) => r.config.id === evictable[i])
    if (runtime) detachWmsLayer(runtime)
  }
}

function clearSuspendedCache() {
  for (const id of suspendedLayerIds.value) {
    if (!selectedLayerIds.value.has(id)) {
      const runtime = runtimeLayers.value.find((r) => r.config.id === id)
      if (runtime) detachWmsLayer(runtime)
    }
  }
}

// ── Batch loading ──────────────────────────────────────────────────

async function loadSelectedDatasets(profile: S57LoadProfile) {
  if (!config.value || selectedDatasetIds.value.size === 0) {
    ElMessage.info('请先选择 S-57 数据集')
    return
  }
  bulkCancelled.value = false
  bulkGeneration.value += 1
  const generation = bulkGeneration.value
  bulkAbortController?.abort()
  bulkAbortController = new AbortController()

  bulkProgress.value = {
    total: 0,
    processed: 0,
    succeeded: 0,
    failed: 0,
    skipped: 0,
    attachedLayerIds: [],
    errors: [],
  }

  try {
    const response = await resolveProjectMapLayers(
      config.value.project.id,
      {
        datasetIds: [...selectedDatasetIds.value],
        profile,
        includeMetadata: false,
      },
      bulkAbortController.signal,
    )

    // Merge resolved layers into runtime state
    const allResolved: BulkResolvedLayer[] = []
    for (const ds of response.datasets) {
      const runtimeDs = runtimeDatasets.value.find((d) => d.config.id === ds.datasetId)
      if (runtimeDs) {
        for (const rl of ds.layers) {
          const existing = runtimeDs.layers.find((l) => l.config.id === rl.id)
          if (existing) {
            // Merge optional fields
            existing.config.minZoom = rl.minZoom
            existing.config.maxZoom = rl.maxZoom
            existing.config.extent = rl.extent
            existing.config.objectClass = rl.objectClass
            existing.config.objectNameZh = rl.objectNameZh
          } else {
            const config: MapLayerConfig = {
              id: rl.id,
              code: rl.code,
              name: rl.name,
              groupName: rl.groupName,
              sortOrder: rl.sortOrder,
              visibleByDefault: false,
              opacity: rl.opacity,
              queryable: rl.queryable,
              exportable: rl.exportable,
              serviceType: 'WMS',
              serviceUrl: rl.serviceUrl,
              serviceLayerName: rl.geoserverLayerName ?? rl.code,
              styleName: rl.styleName,
              geometryType: rl.geometryType,
              minZoom: rl.minZoom,
              maxZoom: rl.maxZoom,
              extent: rl.extent,
              objectClass: rl.objectClass,
              objectNameZh: rl.objectNameZh,
              metadata: {},
            }
            const runtime: RuntimeLayer = {
              config,
              visible: false,
              opacity: rl.opacity,
              loadState: 'idle' as const,
              pendingTiles: 0,
              datasetId: ds.datasetId,
            }
            runtimeDs.layers.push(runtime)
            runtimeLayers.value.push(runtime)
          }
        }
      }
      allResolved.push(...ds.layers)
    }

    // Filter and sort candidates
    const { candidates, skipped } = prepareAttachCandidates(allResolved, loadedLayerIds.value)
    const { blocked, needsConfirm } = evaluateBulkThreshold(candidates.length)

    if (blocked) {
      ElMessage.warning(`候选图层 ${candidates.length} 个，超过上限 ${BULK_HARD_LIMIT}，请缩小选择范围`)
      bulkProgress.value = null
      return
    }

    if (needsConfirm) {
      try {
        await ElMessageBox.confirm(
          `即将加载 ${candidates.length} 个图层（已跳过 ${skipped} 个已加载图层），继续吗？`,
          '批量加载确认',
          { confirmButtonText: '继续加载', cancelButtonText: '取消', type: 'warning' },
        )
      } catch {
        bulkProgress.value = null
        return
      }
    }

    bulkProgress.value.total = candidates.length
    bulkProgress.value.skipped = skipped
    await loadResolvedLayersInBatches(candidates, generation)

    // Completed — make all new layers visible at once, then reset UI state
    const p = bulkProgress.value
    if (p) {
      for (const layerId of p.attachedLayerIds) {
        wmsLayers.get(layerId)?.setVisible(true)
      }
      if (!bulkCancelled.value) {
        ElMessage.success(`批量加载完成：成功 ${p.succeeded}，失败 ${p.failed}，跳过 ${p.skipped}`)
      }
    }
    bulkProgress.value = null
    bulkCancelled.value = false
  } catch (error) {
    if (bulkAbortController?.signal.aborted) return
    ElMessage.error(apiErrorMessage(error, '批量图层解析失败'))
    bulkProgress.value = null
    bulkCancelled.value = false
  }
}

async function loadResolvedLayersInBatches(
  candidates: BulkResolvedLayer[],
  generation: number,
) {
  if (!map || !config.value) return

  for (let i = 0; i < candidates.length; i += BULK_ATTACH_BATCH_SIZE) {
    if (bulkCancelled.value || bulkGeneration.value !== generation) break

    const batch = candidates.slice(i, i + BULK_ATTACH_BATCH_SIZE)
    for (const resolved of batch) {
      const runtime = runtimeLayers.value.find((l) => l.config.id === resolved.id)
      if (!runtime) continue

      const layerId = resolved.id
      if (loadingLayerIds.value.has(layerId) || selectedLayerIds.value.has(layerId)) {
        if (bulkProgress.value) bulkProgress.value.skipped++
        continue
      }

      const loadingNext = new Set(loadingLayerIds.value)
      loadingNext.add(layerId)
      loadingLayerIds.value = loadingNext

      try {
        const extent = transformLayerExtent(resolved.extent, currentCrs.value)
        const result = attachWmsLayer(runtime, {
          extent,
          minZoom: resolved.minZoom,
          maxZoom: resolved.maxZoom,
          visible: false,
        })
        if (result === 'attached') {
          runtime.visible = true
          // Mark as selected
          const selNext = new Set(selectedLayerIds.value)
          selNext.add(layerId)
          selectedLayerIds.value = selNext

          const attachNext = new Set(lastBulkAttachedLayerIds.value)
          attachNext.add(layerId)
          lastBulkAttachedLayerIds.value = attachNext

          if (bulkProgress.value) {
            bulkProgress.value.succeeded++
            bulkProgress.value.attachedLayerIds.push(layerId)
          }
        } else if (result === 'non-spatial') {
          if (bulkProgress.value) bulkProgress.value.skipped++
        } else {
          if (bulkProgress.value) bulkProgress.value.skipped++
        }
      } catch (err) {
        if (bulkProgress.value) {
          bulkProgress.value.failed++
          bulkProgress.value.errors.push({
            layerId,
            layerName: resolved.name,
            message: err instanceof Error ? err.message : '加载失败',
          })
        }
        const failedNext = new Map(failedLayerIds.value)
        failedNext.set(layerId, err instanceof Error ? err.message : '加载失败')
        failedLayerIds.value = failedNext
      } finally {
        const loadingFinal = new Set(loadingLayerIds.value)
        loadingFinal.delete(layerId)
        loadingLayerIds.value = loadingFinal
        if (bulkProgress.value) bulkProgress.value.processed++
      }
    }

    // Wait between batches (unless cancelled or generation changed)
    if (i + BULK_ATTACH_BATCH_SIZE < candidates.length) {
      try {
        await waitForBulkInterval(
          BULK_ATTACH_INTERVAL_MS,
          bulkAbortController?.signal ?? new AbortController().signal,
          generation,
          () => bulkGeneration.value,
        )
      } catch {
        break
      }
    }
  }
}

function cancelBulkLoad() {
  bulkCancelled.value = true
  bulkAbortController?.abort()
  // Make any already-attached (invisible) layers visible so user sees partial results
  if (bulkProgress.value) {
    for (const layerId of bulkProgress.value.attachedLayerIds) {
      wmsLayers.get(layerId)?.setVisible(true)
    }
  }
  bulkProgress.value = null
}

function unloadSelectedDatasets() {
  if (!config.value || selectedDatasetIds.value.size === 0) return
  const targetIds = selectedDatasetIds.value
  for (const runtime of [...runtimeLayers.value]) {
    if (runtime.datasetId && targetIds.has(runtime.datasetId)) {
      detachWmsLayer(runtime)
      const next = new Set(selectedLayerIds.value)
      next.delete(runtime.config.id)
      selectedLayerIds.value = next
    }
  }
  ElMessage.success('已卸载所选数据集的图层')
}

function unloadAllChartLayers() {
  // Only unload business chart layers (from runtimeLayers), leave base maps,
  // AIS, weather, measure, highlight layers untouched.
  for (const runtime of runtimeLayers.value) {
    detachWmsLayer(runtime)
  }
  loadedLayerIds.value = new Set()
  lastBulkAttachedLayerIds.value = new Set()
  loadingLayerIds.value = new Set()
  failedLayerIds.value = new Map()
  bulkProgress.value = null
  ElMessage.success('已卸载全部海图图层')
}

function unloadCurrentFilteredLayers() {
  const targetDsIds = currentFilteredDatasetIds.value
  for (const runtime of [...runtimeLayers.value]) {
    if (runtime.datasetId && targetDsIds.has(runtime.datasetId)) {
      detachWmsLayer(runtime)
      const next = new Set(loadedLayerIds.value)
      next.delete(runtime.config.id)
      loadedLayerIds.value = next
    }
  }
  ElMessage.success('已卸载当前搜索结果图层')
}

function unloadLastBulkBatch() {
  for (const layerId of lastBulkAttachedLayerIds.value) {
    const runtime = runtimeLayers.value.find((l) => l.config.id === layerId)
    if (runtime) {
      detachWmsLayer(runtime)
      const next = new Set(loadedLayerIds.value)
      next.delete(layerId)
      loadedLayerIds.value = next
    }
  }
  lastBulkAttachedLayerIds.value = new Set()
  ElMessage.success('已卸载本次批量加载的图层')
}

function zoomToLayer(runtime: RuntimeLayer) {
  const extent = runtime.config.metadata.extent
  if (!map || !Array.isArray(extent) || extent.length !== 4) {
    ElMessage.info('该图层暂未提供有效范围')
    return
  }
  map.getView().fit(extent as [number, number, number, number], { padding: [70, 70, 70, 390], duration: 500 })
}

function activateMeasure(type: 'LineString' | 'Polygon') {
  if (!map) return
  if (measureInteraction) map.removeInteraction(measureInteraction)
  measureSource.clear()
  measureText.value = '单击开始绘制，双击结束'
  measureInteraction = new Draw({ source: measureSource, type })
  measureInteraction.on('drawend', (event) => {
    const geometry = event.feature.getGeometry()
    if (!geometry) return
    if (type === 'LineString') {
      const meters = getLength(geometry, { projection: currentCrs.value })
      measureText.value = meters > 1000 ? `${(meters / 1000).toFixed(2)} km` : `${meters.toFixed(1)} m`
    } else {
      const squareMeters = getArea(geometry, { projection: currentCrs.value })
      measureText.value = squareMeters > 1_000_000 ? `${(squareMeters / 1_000_000).toFixed(2)} km²` : `${squareMeters.toFixed(1)} m²`
    }
    if (measureInteraction && map) map.removeInteraction(measureInteraction)
    measureInteraction = null
  })
  map.addInteraction(measureInteraction)
}

function clearMeasure() {
  measureSource.clear()
  measureText.value = ''
  if (measureInteraction && map) map.removeInteraction(measureInteraction)
  measureInteraction = null
}

async function captureMap() {
  if (!map || !mapTarget.value) return
  map.once('rendercomplete', () => {
    const size = map?.getSize()
    if (!size || !mapTarget.value) return
    const canvas = document.createElement('canvas')
    canvas.width = size[0]
    canvas.height = size[1]
    const context = canvas.getContext('2d')
    for (const layerCanvas of mapTarget.value.querySelectorAll<HTMLCanvasElement>('.ol-layer canvas')) {
      if (!context || layerCanvas.width === 0) continue
      context.globalAlpha = Number(layerCanvas.parentElement?.style.opacity || 1)
      const transform = layerCanvas.style.transform.match(/^matrix\(([^)]+)\)$/)?.[1].split(',').map(Number)
      if (transform?.length === 6) context.setTransform(transform[0], transform[1], transform[2], transform[3], transform[4], transform[5])
      context.drawImage(layerCanvas, 0, 0)
    }
    context?.setTransform(1, 0, 0, 1, 0, 0)
    const link = document.createElement('a')
    link.download = `${config.value?.project.code || 'map'}-${Date.now()}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
  })
  map.renderSync()
}

function printMap() {
  window.print()
}

async function loadAttributeTable(layer: MapLayerConfig) {
  attributeLayer.value = layer
  attributeVisible.value = true
  attributePage.value = 1
  attributeFilterField.value = ''
  attributeFilterValue.value = ''
  try {
    const response = await api.get<LayerRecord>(`/layers/${layer.id}/metadata`)
    attributeAllowedFields.value = response.data.allowedFields
  } catch {
    attributeAllowedFields.value = []
  }
  await searchAttributeRows()
}

async function searchAttributeRows() {
  if (!attributeLayer.value) return
  attributeSearchController.value?.abort()
  const controller = new AbortController()
  attributeSearchController.value = controller
  attributeLoading.value = true
  try {
    const filters = attributeFilterField.value && attributeFilterValue.value
      ? [{ field: attributeFilterField.value, operator: 'contains', value: attributeFilterValue.value }]
      : []
    const response = await api.post(`/layers/${attributeLayer.value.id}/features/search`, {
      page: attributePage.value,
      pageSize: 15,
      filters,
    }, { signal: controller.signal })
    if (controller.signal.aborted) return
    attributeRows.value = response.data.items
    attributeTotal.value = response.data.total
  } catch (error) {
    if (controller.signal.aborted) return
    ElMessage.error(apiErrorMessage(error, '属性表加载失败'))
  } finally {
    if (!controller.signal.aborted) {
      attributeLoading.value = false
    }
  }
}

async function exportAttributes(format: 'csv' | 'geojson') {
  if (!attributeLayer.value) return
  const filters = attributeFilterField.value && attributeFilterValue.value
    ? [{ field: attributeFilterField.value, operator: 'contains', value: attributeFilterValue.value }]
    : []
  try {
    const response = await api.post(
      `/layers/${attributeLayer.value.id}/exports`,
      { format, filters, fields: attributeAllowedFields.value },
      { responseType: 'blob' },
    )
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = `${attributeLayer.value.code}.${format === 'csv' ? 'csv' : 'geojson'}`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '导出失败'))
  }
}

async function showLayerDetails(layer: MapLayerConfig) {
  try {
    const [metadataResponse, legendResponse] = await Promise.all([
      api.get<LayerRecord>(`/layers/${layer.id}/metadata`),
      api.get<{ url: string }>(`/layers/${layer.id}/legend`),
    ])
    metadataLayer.value = metadataResponse.data
    legendUrl.value = legendResponse.data.url
    metadataVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '图层信息加载失败'))
  }
}

async function identify(coordinate: [number, number]) {
  const layer = runtimeLayers.value.find((item) => item.visible && item.config.queryable)
  if (!layer) {
    ElMessage.info('当前没有可查询的可见图层')
    return
  }
  identifyController.value?.abort()
  const controller = new AbortController()
  identifyController.value = controller
  try {
    const response = await api.post(`/layers/${layer.config.id}/identify`, { coordinate, crs: 'EPSG:4326', tolerance: 12 }, { signal: controller.signal })
    if (controller.signal.aborted) return
    identifyItems.value = response.data.items
    identifyVisible.value = true
  } catch (error) {
    if (controller.signal.aborted) return
    ElMessage.error(apiErrorMessage(error, '要素查询失败'))
  }
}

async function queryWeather(coordinate: [number, number]) {
  try {
    const response = await api.post('/demo/weather/point', { coordinate, crs: 'EPSG:4326' })
    weatherCoordinate.value = coordinate
    weatherItems.value = response.data.items
    weatherVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '气象数据查询失败'))
  }
}

async function toggleAis() {
  if (aisVisible.value) {
    aisLayer.setVisible(false)
    aisVisible.value = false
    return
  }
  try {
    const response = await api.get('/demo/ais/vessels')
    aisSource.clear()
    for (const vessel of response.data.items) {
      const feature = new Feature({ geometry: new Point(fromLonLat([vessel.longitude, vessel.latitude], currentCrs.value)), ...vessel })
      aisSource.addFeature(feature)
    }
    aisLayer.setVisible(true)
    aisVisible.value = true
    ElMessage.warning('当前显示的是AIS演示数据')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'AIS演示数据加载失败'))
  }
}

function handleOverlayCommand(command: string) {
  if (command === 'ais') void toggleAis()
}

function reloadAisGeometry() {
  for (const feature of aisSource.getFeatures()) {
    const longitude = feature.get('longitude') as number
    const latitude = feature.get('latitude') as number
    feature.setGeometry(new Point(fromLonLat([longitude, latitude], currentCrs.value)))
  }
}

onMounted(async () => {
  try {
    const [mapConfig, baseMapResponse] = await Promise.all([
      projectsStore.loadMapConfig(String(route.params.id)),
      api.get<BaseMapRecord[]>('/base-maps'),
    ])
    config.value = mapConfig
    baseMaps.value = baseMapResponse.data
    currentCrs.value = config.value.project.defaultCrs
    runtimeDatasets.value = config.value.datasets.map((dataset) => ({
      config: dataset,
      expanded: false,
      loading: false,
      loaded: false,
      layers: [],
    }))
    await Promise.all(
      runtimeDatasets.value
        .filter((dataset) => dataset.config.visibleByDefault)
        .map(async (dataset) => {
          await toggleDataset(dataset)
          dataset.layers.forEach((layer) => { layer.visible = true })
        }),
    )
    await nextTick()
    await buildMap()
    startPerfPoll()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '项目地图加载失败'))
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  stopPerfPoll()
  bulkAbortController?.abort()
  for (const runtime of runtimeLayers.value) detachWmsLayer(runtime)
  map?.setTarget(undefined)
  map = null
})
</script>

<template>
  <div v-loading="loading" class="map-workspace">
    <header class="map-header">
      <div class="map-navigation">
        <el-tooltip content="返回项目门户" placement="bottom">
          <button class="map-back" type="button" aria-label="返回项目门户" @click="router.push('/projects')"><el-icon><ArrowLeft /></el-icon></button>
        </el-tooltip>
        <el-tooltip :content="layerPanelCollapsed ? '展开图层目录' : '收起图层目录'" placement="bottom">
          <button class="map-panel-toggle" type="button" :aria-label="layerPanelCollapsed ? '展开图层目录' : '收起图层目录'" @click="layerPanelCollapsed = !layerPanelCollapsed">
            <el-icon><Expand v-if="layerPanelCollapsed" /><Fold v-else /></el-icon>
          </button>
        </el-tooltip>
        <div class="map-project-title"><span class="eyebrow">MAP WORKSPACE</span><strong>{{ config?.project.name || '加载中' }}</strong></div>
      </div>
      <div class="map-view-controls">
        <div class="projection-switch"><button :class="{ active: currentCrs === 'EPSG:3857' }" @click="switchProjection('EPSG:3857')">常规地图</button><button :class="{ active: currentCrs === 'EPSG:3413' }" @click="switchProjection('EPSG:3413')">北极投影</button></div>
        <div class="map-disclaimer">非认证航海显示</div>
      </div>
    </header>
    <aside :class="['layer-panel', 'glass-panel', { 'is-collapsed': layerPanelCollapsed }]">
      <div class="panel-heading"><div><span class="eyebrow">LAYERS</span><h2>图层目录</h2></div><span class="layer-count">{{ runtimeDatasets.length }}</span></div>
      <div class="layer-filters">
        <el-select v-model="activeBaseMapId" class="full-width" placeholder="当前投影暂无配置底图" clearable @change="selectBaseMap">
          <el-option v-for="baseMap in availableBaseMaps" :key="baseMap.id" :label="`${baseMap.name} · ${baseMap.mapType}`" :value="baseMap.id" />
        </el-select>
        <el-input v-model="layerSearch" :prefix-icon="Search" clearable placeholder="搜索图层、代码或分组" />
        <div class="batch-toolbar" v-if="runtimeDatasets.some(ds => isS57Dataset(ds))">
          <div class="batch-select-row">
            <el-button size="small" text @click="selectFilteredDatasets">全选当前结果</el-button>
            <el-button size="small" text @click="clearDatasetSelection">清空选择</el-button>
            <span class="batch-select-count">{{ selectedDatasetCount }} 个数据集</span>
          </div>
          <div class="batch-mode-row" v-if="selectedLayerIds.size > 0">
            <span class="batch-mode-label">{{ renderMode === 'smart' ? '智能' : renderMode === 'standard' ? '标准' : '概览' }}模式</span>
            <span class="batch-mode-stats">活动 {{ activeLayerIds.size }} · 休眠 {{ suspendedLayerIds.size }} · 等待 {{ warmingLayerIds.size }}</span>
            <el-button size="small" text @click="renderMode = renderMode === 'smart' ? 'standard' : 'smart'">
              {{ renderMode === 'smart' ? '切换标准' : '切换智能' }}
            </el-button>
            <el-button v-if="suspendedLayerIds.size > 0" size="small" text @click="reconcileRenderPlan()">恢复调度</el-button>
            <el-button v-if="suspendedLayerIds.size > 0" size="small" text @click="clearSuspendedCache()">清理休眠</el-button>
          </div>
          <div class="batch-actions">
            <el-dropdown trigger="click" placement="bottom-start" @command="(profile: string) => loadSelectedDatasets(profile as S57LoadProfile)">
              <el-button size="small" type="primary" :disabled="selectedDatasetCount === 0 || !!bulkProgress">批量加载<el-icon class="el-icon--right"><CaretBottom /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="core_chart">加载核心海图层</el-dropdown-item>
                  <el-dropdown-item command="navigation_recommended">加载推荐海图层</el-dropdown-item>
                  <el-dropdown-item command="all_spatial">加载全部可显示图层</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-dropdown trigger="click" placement="bottom-start" @command="(cmd: string) => {
              if (cmd === 'selected') unloadSelectedDatasets()
              else if (cmd === 'filtered') unloadCurrentFilteredLayers()
              else if (cmd === 'all') unloadAllChartLayers()
              else if (cmd === 'last_batch') unloadLastBulkBatch()
            }">
              <el-button size="small" :disabled="loadedLayerIds.size === 0">批量卸载<el-icon class="el-icon--right"><CaretBottom /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="selected">卸载所选数据集图层</el-dropdown-item>
                  <el-dropdown-item command="filtered">卸载当前搜索结果图层</el-dropdown-item>
                  <el-dropdown-item command="all" divided>卸载全部海图图层</el-dropdown-item>
                  <el-dropdown-item v-if="lastBulkAttachedLayerIds.size > 0" command="last_batch">卸载本次加载</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div class="batch-progress" v-if="bulkProgress">
            <div class="batch-progress-bar">
              <span class="batch-progress-text">{{ bulkProgress.processed }} / {{ bulkProgress.total }}</span>
              <el-progress :percentage="bulkProgress.total ? Math.round(bulkProgress.processed / bulkProgress.total * 100) : 0" :show-text="false" :stroke-width="4" />
            </div>
            <div class="batch-progress-stats">
              <span class="stat-success"><el-icon><Check /></el-icon>{{ bulkProgress.succeeded }}</span>
              <span class="stat-failed"><el-icon><Close /></el-icon>{{ bulkProgress.failed }}</span>
              <span class="stat-skipped">{{ bulkProgress.skipped }} 跳过</span>
            </div>
            <el-button size="small" text type="danger" @click="cancelBulkLoad" :disabled="bulkCancelled">
              <el-icon><Close /></el-icon>取消剩余
            </el-button>
            <div v-if="bulkProgress.errors.length > 0" class="batch-errors">
              <el-collapse>
                <el-collapse-item :title="`${bulkProgress.errors.length} 个失败详情`">
                  <div v-for="err in bulkProgress.errors" :key="err.layerId" class="batch-error-item">
                    <el-icon><WarningFilled /></el-icon>
                    <span>{{ err.layerName }}</span>
                    <span class="batch-error-msg">{{ err.message }}</span>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>
        </div>
      </div>
      <div class="layer-groups">
        <template v-if="hasFilteredLayers">
          <section v-for="[groupName, datasets] in filteredGroups" :key="groupName" class="layer-group">
            <div class="layer-group-title">{{ groupName }}<span>{{ datasets.length }}</span></div>
            <div v-for="dataset in datasets" :key="dataset.config.id" class="layer-dataset">
              <div class="dataset-summary">
                <el-checkbox
                  v-if="isS57Dataset(dataset)"
                  :model-value="selectedDatasetIds.has(dataset.config.id)"
                  :disabled="!!bulkProgress"
                  size="small"
                  class="dataset-checkbox"
                  @change="toggleDatasetSelection(dataset.config.id)"
                />
                <button class="dataset-expand" type="button" :aria-label="dataset.expanded ? '收起图层' : '展开图层'" @click="toggleDataset(dataset)">
                  <el-icon><CaretBottom v-if="dataset.expanded" /><CaretRight v-else /></el-icon>
                </button>
                <button class="dataset-title" type="button" @click="toggleDataset(dataset)">
                  <strong>{{ dataset.config.name }}</strong>
                  <small>{{ dataset.config.code }} · {{ dataset.config.memberLayerCount }} 个图层</small>
                </button>
                <span v-if="dataset.loading" class="dataset-loading">加载中</span>
              </div>
              <template v-if="dataset.expanded && dataset.loaded">
                <div v-for="runtime in dataset.layers" :key="runtime.config.id" class="layer-row layer-row-child">
                  <button :class="['visibility-toggle', { active: runtime.visible }]" type="button" @click="toggleLayer(runtime)"><span></span></button>
                  <div class="layer-name">
                    <strong>{{ s57LayerTitle(runtime.config) }}</strong>
                    <small>
                      <span class="layer-status-text">{{ layerStatusLabel(runtime.config.id) }}</span>
                      <template v-if="isNonSpatial(runtime.config)">
                        <span class="layer-state loaded"></span>属性表<span v-if="runtime.config.queryable"> · 可查询</span>
                      </template>
                      <template v-else>
                        <span :class="['layer-state', runtime.loadState]"></span>{{ runtime.config.queryable ? '可查询' : '仅显示' }}<span v-if="runtime.loadState === 'error'"> · 加载失败</span>
                      </template>
                    </small>
                  </div>
                  <el-popover placement="right-start" :width="230" trigger="click" popper-class="layer-action-popover">
                    <div class="layer-action-title"><strong>{{ s57LayerTitle(runtime.config) }}</strong><span>{{ Math.round(runtime.opacity * 100) }}%</span></div>
                    <el-slider v-model="runtime.opacity" :step="0.05" @input="updateOpacity(runtime)" />
                    <div class="layer-action-list">
                      <el-button text @click="zoomToLayer(runtime)">定位到图层</el-button>
                      <el-button text @click="showLayerDetails(runtime.config)">图例与元数据</el-button>
                      <el-button v-if="runtime.config.queryable" text @click="loadAttributeTable(runtime.config)">查看属性表</el-button>
                    </div>
                    <template #reference><button class="more-button" type="button" aria-label="图层操作"><el-icon><MoreFilled /></el-icon></button></template>
                  </el-popover>
                </div>
              </template>
            </div>
          </section>
        </template>
        <el-empty v-else class="layer-empty" description="未找到匹配图层" :image-size="36" />
      </div>
      <div class="layer-panel-footer">
        <el-dropdown trigger="click" placement="top-start" @command="handleOverlayCommand">
          <button class="overlay-menu-trigger" type="button" aria-label="环境叠加">
            <el-icon><Operation /></el-icon><span>环境叠加</span><span class="overlay-menu-count">1</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu class="overlay-menu">
              <el-dropdown-item command="ais">
                <span class="demo-badge">演示</span><span>AIS 船位</span><span class="overlay-state">{{ aisVisible ? '已开启' : '未开启' }}</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </aside>
    <div ref="mapTarget" class="map-canvas"></div>
    <div class="map-tools glass-panel">
      <el-tooltip content="要素识别" placement="left"><button :class="{ active: queryMode }" @click="queryMode = !queryMode; weatherMode = false"><el-icon><Location /></el-icon></button></el-tooltip>
      <el-tooltip content="点位气象演示" placement="left"><button :class="{ active: weatherMode }" @click="weatherMode = !weatherMode; queryMode = false"><el-icon><DataAnalysis /></el-icon></button></el-tooltip>
      <el-tooltip content="测量距离" placement="left"><button @click="activateMeasure('LineString')"><el-icon><MapLocation /></el-icon></button></el-tooltip>
      <el-tooltip content="测量面积" placement="left"><button @click="activateMeasure('Polygon')"><el-icon><FullScreen /></el-icon></button></el-tooltip>
      <el-tooltip content="地图截图" placement="left"><button @click="captureMap"><el-icon><Camera /></el-icon></button></el-tooltip>
      <el-tooltip content="打印地图" placement="left"><button @click="printMap"><el-icon><Printer /></el-icon></button></el-tooltip>
    </div>
    <div class="map-status">
      <span>{{ coordinateText }}</span><span>{{ currentCrs }}</span><span v-if="measureText" class="measure-result">{{ measureText }} <button @click="clearMeasure">清除</button></span>
      <template v-if="perfDisplay">
        <span class="perf-stat" title="活动图层">活动 {{ perfDisplay.activeLayerCount }}</span>
        <span class="perf-stat" title="等待瓦片">瓦片 {{ perfDisplay.pendingTileCount }}</span>
        <span v-if="perfDisplay.failedTileCount > 0" class="perf-stat perf-failed" title="失败瓦片">失败 {{ perfDisplay.failedTileCount }}</span>
        <button class="perf-toggle" type="button" @click="devShowPerfDetail = !devShowPerfDetail" title="性能详情">⚙</button>
      </template>
    </div>
    <!-- Dev-only: collapsible performance detail panel -->
    <div v-if="devShowPerfDetail && perfDisplay" class="perf-detail">
      <div><span>活动图层</span><span>{{ perfDisplay.activeLayerCount }}</span></div>
      <div><span>已挂载图层</span><span>{{ perfDisplay.attachedLayerCount }}</span></div>
      <div><span>休眠图层</span><span>{{ perfDisplay.suspendedLayerCount }}</span></div>
      <div><span>等待瓦片</span><span>{{ perfDisplay.pendingTileCount }}</span></div>
      <div><span>已加载瓦片</span><span>{{ perfDisplay.loadedTileCount }}</span></div>
      <div><span>失败瓦片</span><span>{{ perfDisplay.failedTileCount }}</span></div>
      <div><span>重试次数</span><span>{{ perfDisplay.retriedTileCount }}</span></div>
      <div><span>平均耗时</span><span>{{ perfDisplay.averageTileDurationMs }}ms</span></div>
      <div><span>P95耗时</span><span>{{ perfDisplay.p95TileDurationMs }}ms</span></div>
      <div><span>当前代</span><span>{{ perfDisplay.currentGeneration }}</span></div>
    </div>
    <el-drawer v-model="attributeVisible" :title="`${attributeLayer?.name || ''} · 属性表`" size="55%">
      <div class="tab-toolbar">
        <el-select v-model="attributeFilterField" clearable placeholder="筛选字段" style="width: 180px"><el-option v-for="field in attributeAllowedFields" :key="field" :label="field" :value="field" /></el-select>
        <el-input v-model="attributeFilterValue" clearable placeholder="包含文本" style="width: 220px" @keyup.enter="attributePage = 1; searchAttributeRows()" />
        <el-button type="primary" @click="attributePage = 1; searchAttributeRows()">查询</el-button>
        <el-button v-if="attributeLayer?.exportable" @click="exportAttributes('csv')">导出CSV</el-button>
        <el-button v-if="attributeLayer?.exportable" @click="exportAttributes('geojson')">导出GeoJSON</el-button>
      </div>
      <el-table v-loading="attributeLoading" :data="attributeRows" height="calc(100vh - 180px)" stripe>
        <el-table-column v-for="column in attributeColumns" :key="column" :prop="column" :label="column" min-width="140" show-overflow-tooltip />
      </el-table>
      <el-pagination v-model:current-page="attributePage" :page-size="15" :total="attributeTotal" layout="prev, pager, next, total" @current-change="searchAttributeRows" />
    </el-drawer>
    <el-drawer v-model="metadataVisible" :title="`${metadataLayer?.name || ''} · 图层信息`" size="420px">
      <div class="legend-preview"><img v-if="legendUrl" :src="legendUrl" alt="图层图例" /></div>
      <el-descriptions v-if="metadataLayer" :column="1" border>
        <el-descriptions-item label="代码">{{ metadataLayer.code }}</el-descriptions-item>
        <el-descriptions-item label="几何类型">{{ metadataLayer.geometryType || '—' }}</el-descriptions-item>
        <el-descriptions-item label="坐标系">{{ metadataLayer.sourceCrs || '—' }}</el-descriptions-item>
        <el-descriptions-item label="允许字段">{{ metadataLayer.allowedFields.join('、') || '无' }}</el-descriptions-item>
        <el-descriptions-item label="查询/导出">{{ metadataLayer.queryable ? '可查询' : '不可查询' }} / {{ metadataLayer.exportable ? '可导出' : '不可导出' }}</el-descriptions-item>
      </el-descriptions>
    </el-drawer>
    <el-drawer v-model="weatherVisible" title="72小时水文气象演示" size="48%">
      <el-alert title="演示数据，仅用于功能验证，不代表实时或权威海洋信息。" type="warning" :closable="false" show-icon />
      <p v-if="weatherCoordinate" class="weather-coordinate">查询坐标：{{ weatherCoordinate[1].toFixed(4) }}°, {{ weatherCoordinate[0].toFixed(4) }}°</p>
      <WeatherChart :items="weatherItems" />
    </el-drawer>
    <el-drawer v-model="identifyVisible" title="要素识别结果" size="420px">
      <el-empty v-if="!identifyItems.length" description="当前位置没有可查询要素" />
      <el-descriptions v-for="(item, index) in identifyItems" v-else :key="index" :column="1" border class="identify-card">
        <el-descriptions-item v-for="(value, key) in item" :key="key" :label="String(key)">{{ key === 'geometry' ? '空间几何' : value }}</el-descriptions-item>
      </el-descriptions>
    </el-drawer>
  </div>
</template>
