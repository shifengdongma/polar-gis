<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft,
  Camera,
  CaretBottom,
  CaretRight,
  Check,
  Close,
  Compass,
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
import type LineString from 'ol/geom/LineString'
import type Polygon from 'ol/geom/Polygon'
import Draw from 'ol/interaction/Draw'
import TileLayer from 'ol/layer/Tile'
import BaseLayer from 'ol/layer/Base'
import VectorLayer from 'ol/layer/Vector'
import OSM from 'ol/source/OSM'
import TileWMS from 'ol/source/TileWMS'
import TileState from 'ol/TileState'
import WMTS, { optionsFromCapabilities } from 'ol/source/WMTS'
import XYZ from 'ol/source/XYZ'
import VectorSource from 'ol/source/Vector'
import WMTSCapabilities from 'ol/format/WMTSCapabilities'
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style'
import { fromLonLat, toLonLat, transformExtent } from 'ol/proj'
import { get as getProjection, getPointResolution } from 'ol/proj'
import { register } from 'ol/proj/proj4'
import { unByKey } from 'ol/Observable'
import proj4 from 'proj4'
import { api, apiErrorMessage } from '../api/client'
import { resolveProjectMapLayers } from '../api/projects'
import EnvironmentLayerPanel from '../components/EnvironmentLayerPanel.vue'
import EnvironmentValueTooltip from '../components/EnvironmentValueTooltip.vue'
import IceLayerPanel from '../components/IceLayerPanel.vue'
import IceTimeline from '../components/IceTimeline.vue'
import IceValueTooltip from '../components/IceValueTooltip.vue'
import RouteInfoFlyout from '../components/RouteInfoFlyout.vue'
import RoutePlannerPanel from '../components/RoutePlannerPanel.vue'
import WeatherChart from '../components/WeatherChart.vue'
import { useEnvironmentOverlays } from '../composables/useEnvironmentOverlays'
import { useIceOverlay } from '../composables/useIceOverlay'
import { useRouteDrawing } from '../composables/useRouteDrawing'
import { useProjectsStore } from '../stores/projects'
import { useRoutesStore } from '../stores/routes'
import {
  HOVER_MIN_GROUND_RESOLUTION_METERS,
  buildMeasureGeometry,
  formatMeasureResult,
  hoverDecimalsForGroundResolution,
  measureGeometryToDraft,
  projectedToLonLatSafe,
  type MeasureDraft,
} from '../utils/mapMeasure'
import type {
  BaseMapRecord,
  BulkLayerProgress,
  BulkResolvedLayer,
  LayerRecord,
  MapConfig,
  MapDatasetConfig,
  MapLayerConfig,
  RenderBundleConfig,
  S57LoadProfile,
} from '../types'
import {
  BULK_ATTACH_BATCH_SIZE,
  BULK_ATTACH_INTERVAL_MS,
  BULK_HARD_LIMIT,
  ENABLE_GWC_TILES,
  evaluateBulkThreshold,
  prepareAttachCandidates,
  transformLayerExtent,
  waitForBulkInterval,
  PerLayerStatsManager,
  SMART_RECONCILE_DEBOUNCE_MS,
  SMART_SUSPEND_EVICT_DELAY_MS,
  SMART_MAX_ATTACHED_WMS_LAYERS,
  TILE_RETRY_MAX_ATTEMPTS,
  TILE_RETRY_BASE_DELAY_MS,
  TILE_WARMING_TIMEOUT_MS,
  TILE_CACHE_MAX_ENTRIES,
  TILE_CACHE_MAX_BYTES,
  TILE_MAX_CONCURRENT_FETCH,
  TILE_MAX_QUEUED_FETCH,
  ENABLE_TILE_MERGING,
} from '../utils/mapLayerBatch'
import { LRUTileCache } from '../utils/tileCache'
import { TileRequestQueue } from '../utils/tileRequestQueue'
import {
  groupResolvedLayers,
  createMergedTileSource,
  joinLayerParams,
  toMergeableLayer,
  type MergeGroup,
} from '../utils/mapTileMerger'
import {
  buildRenderPlan,
  ENABLE_RENDER_BUNDLES,
  isLayerInViewport,
  type BundleRenderPlan,
  type ChartRenderMode,
  type ResolvedLayerMeta,
} from '../utils/mapRenderScheduler'
import {
  attachBundle,
  detachBundle,
  disposeAllBundles,
  getAllBundleRuntimes,
  getBundleRuntime,
  isLayerCoveredByBundle,
  setBundleVisible,
} from '../utils/mapRenderBundles'
import { fetchRenderPlan } from '../api/projects'
import type { MapTilePerformanceStats } from '../types'
import { parseWgs84Extent } from '../utils/mapExtent'
import { formatLonLat, shiftCoordinateIntoWorldCopy } from '../utils/mapRoute'
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
const routesStore = useRoutesStore()
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
/** 测量激活态(唯一真值):驱动工具栏高亮、singleclick 守卫与 Draw 生命周期 */
const measureMode = ref<'none' | 'LineString' | 'Polygon'>('none')
/** 测量真值(WGS84)。结果显示只由它推导,故与投影无关 */
const measureDraft = shallowRef<MeasureDraft | null>(null)

// ── 地图内坐标提示 ───────────────────────────────────────────────────
// 复用下方 pointermove 监听 + requestAnimationFrame 合帧:每帧最多更新一次。
// 与底部状态栏(恒显五位小数)不同,这里只在视口地面分辨率足够细时出现,
// 且小数位随分辨率变化 —— 避免暗示地图本身给不出的定位精度。
const hover = ref<{ x: number; y: number; flipX: boolean; flipY: boolean; text: string } | null>(null)
let hoverCoordinate: number[] | null = null
let hoverPixel: number[] | null = null
let hoverRaf = 0
/** 触控设备没有 hover 能力;逐事件再按 pointerType 兜底(混合设备) */
let hoverEnabled = true
/** 地图视口元素,用于卸载时摘掉 pointerleave 监听 */
let hoverViewport: HTMLElement | null = null
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
const routePanelVisible = ref(false)

/**
 * 指针所在位置的地面分辨率(米/像素)。
 *
 * 必须用 getPointResolution 而不是 zoom:同一个 zoom 数字在 EPSG:3857 与
 * EPSG:3413 下的地面精度相差数倍(实测 3857 zoom4 ≈ 2532 m/px,3413 zoom4
 * ≈ 39500 m/px),且同一投影内也随纬度变化。传入指针坐标即可得到该点的真实值。
 */
function groundResolutionMeters(coordinate: number[]): number {
  if (!map) return Number.NaN
  const view = map.getView()
  const resolution = view.getResolution()
  if (resolution === undefined || !Number.isFinite(resolution)) return Number.NaN
  return getPointResolution(view.getProjection(), resolution, coordinate, 'm')
}

/** rAF 回调:一帧最多一次 DOM 更新 */
function flushHover() {
  hoverRaf = 0
  const coordinate = hoverCoordinate
  const pixel = hoverPixel
  // 冰情值浮窗显示期间隐藏经纬度提示(优先级:地图工具/航路浮窗 > 冰情 > 经纬度)
  if (!hoverEnabled || !coordinate || !pixel || routeFlyout.value || iceOverlay.hover.value || environmentOverlays.tooltip.value) {
    hover.value = null
    return
  }
  const groundResolution = groundResolutionMeters(coordinate)
  if (!Number.isFinite(groundResolution) || groundResolution > HOVER_MIN_GROUND_RESOLUTION_METERS) {
    // 视图太粗:显示经纬度只会暗示地图给不出的精度
    hover.value = null
    return
  }
  // 投影范围外 / 非法坐标 -> 不显示(proj4 对 3413 越界坐标会给「有限但无意义」
  // 的值,不会返回 NaN,所以必须显式判定)
  const lonLat = projectedToLonLatSafe(coordinate, currentCrs.value)
  if (!lonLat) {
    hover.value = null
    return
  }
  const [width, height] = map?.getSize() ?? [0, 0]
  hover.value = {
    x: pixel[0],
    y: pixel[1],
    flipX: pixel[0] > width * 0.6,
    flipY: pixel[1] > height * 0.65,
    text: formatLonLat(lonLat[0], lonLat[1], hoverDecimalsForGroundResolution(groundResolution)),
  }
}

function scheduleHover() {
  if (!hoverRaf) hoverRaf = requestAnimationFrame(flushHover)
}

/** 隐藏提示并丢弃待处理帧(地图外 / 拖动 / 触控 / 销毁 / 非法坐标) */
function hideHover() {
  hoverCoordinate = null
  hoverPixel = null
  if (hoverRaf) {
    cancelAnimationFrame(hoverRaf)
    hoverRaf = 0
  }
  hover.value = null
}

/** 结束测量 Draw 但保留已有测量结果(source / 真值 / 文本不清除) */
function stopMeasureInteraction() {
  if (measureInteraction && map) map.removeInteraction(measureInteraction)
  measureInteraction = null
  measureMode.value = 'none'
}

/** 航路绘制/编辑与要素识别/气象/测量互斥:进入航路交互前关闭其余地图交互 */
function deactivateOtherMapInteractions() {
  queryMode.value = false
  weatherMode.value = false
  stopMeasureInteraction()
}

function toggleQueryMode() {
  routesStore.setInteractionMode('idle') // 互斥:结束航路绘制/编辑
  stopMeasureInteraction() // 互斥:否则残留的测量 Draw 会静默吃掉所有点击
  closeRouteFlyout() // 识别模式下不让航路浮窗抢占点击
  queryMode.value = !queryMode.value
  weatherMode.value = false
}

function toggleWeatherMode() {
  routesStore.setInteractionMode('idle')
  stopMeasureInteraction()
  closeRouteFlyout()
  weatherMode.value = !weatherMode.value
  queryMode.value = false
}

const routeDrawing = useRouteDrawing({
  getMap: () => map,
  getCrs: () => currentCrs.value,
  deactivateOthers: deactivateOtherMapInteractions,
  // 定位让位随面板折叠状态自适应:两侧折叠后「定位整条航路」占满完整地图大屏
  getFitPadding: () => [90, routePanelVisible.value ? 550 : 40, 90, layerPanelCollapsed.value ? 40 : 420],
})
// 关闭航路面板时结束绘制/编辑交互,不影响原地图浏览
watch(routePanelVisible, (open) => {
  if (!open) routesStore.setInteractionMode('idle')
})

// ── 航线信息浮窗(地图内) ──────────────────────────────────────────
// 不用 ol/Overlay:浮层挂在 .map-canvas 的兄弟节点 .map-overlay-root 上(与
// .map-tools / .map-status 同一模式),几何上与地图视口完全重合 ——
// 既不与 OpenLayers 争抢 target 的子节点,也不参与地图的指针事件。
interface RouteFlyoutState {
  routeId: string
  /** 点击处 WGS84 真值(业务真值,不落 Store),投影切换后据此重锚 */
  lonLat: [number, number]
  /** 锚点投影坐标,可能是渲染几何所在的世界副本 */
  projected: number[]
  /** projected 所属投影 */
  crs: string
  /** 选中航段(1-based);null 表示只选中了整条航路 */
  segmentIndex: number | null
}

const routeFlyout = shallowRef<RouteFlyoutState | null>(null)
const routeFlyoutPixel = ref({ x: 0, y: 0, flipX: false, flipY: false })
let stopRouteFlyoutRender: (() => void) | null = null

const routeFlyoutRoute = computed(() => {
  const state = routeFlyout.value
  if (!state) return null
  return routesStore.routes.find((route) => route.id === state.routeId) ?? null
})
const routeFlyoutSegmentIndex = computed(() => routeFlyout.value?.segmentIndex ?? null)

/** 只在浮窗打开期间挂 postrender:平移/缩放时重锚,关闭后零开销 */
function attachRouteFlyoutRender() {
  if (!map || stopRouteFlyoutRender) return
  const key = map.on('postrender', updateRouteFlyoutPixel)
  stopRouteFlyoutRender = () => unByKey(key)
}

function detachRouteFlyoutRender() {
  if (stopRouteFlyoutRender) {
    stopRouteFlyoutRender()
    stopRouteFlyoutRender = null
  }
}

/**
 * 重算浮窗锚点像素并夹取在地图视口内(右侧让开航路面板抽屉)。
 * 位置只由 map.getSize() 推导,不读 DOM 布局,因此可以安全地每帧调用。
 */
function updateRouteFlyoutPixel() {
  const state = routeFlyout.value
  if (!map || !state) return
  if (state.crs !== currentCrs.value) {
    // 投影切换:由 WGS84 真值重算,再平移到与渲染几何同一世界副本
    // (3857 下 fromLonLat 不回绕、toLonLat 会回绕,不这么做锚点会跑到另一个副本)
    const extent = routeDrawing.getRouteExtent(state.routeId)
    const projected = fromLonLat(state.lonLat, currentCrs.value)
    state.projected = extent ? shiftCoordinateIntoWorldCopy(projected, extent, currentCrs.value) : projected
    state.crs = currentCrs.value
  }
  const pixel = map.getPixelFromCoordinate(state.projected)
  if (!pixel) return
  const [width, height] = map.getSize() ?? [0, 0]
  const reservedRight = routePanelVisible.value ? 540 : 16
  const maxX = Math.max(24, width - reservedRight)
  const x = Math.min(Math.max(pixel[0], 8), maxX)
  const y = Math.min(Math.max(pixel[1], 8), Math.max(24, height - 12))
  const flipX = x > maxX - 320
  const flipY = y > height - 300
  // postrender 每帧都会调用;仅当锚点真的移动时才写 ref,避免每帧重渲染浮窗
  const current = routeFlyoutPixel.value
  if (current.x === x && current.y === y && current.flipX === flipX && current.flipY === flipY) return
  routeFlyoutPixel.value = { x, y, flipX, flipY }
}

function openRouteFlyout(routeId: string, coordinate: number[], lonLat: [number, number], segmentIndex: number | null) {
  routeFlyout.value = {
    routeId,
    lonLat,
    projected: [...coordinate],
    crs: currentCrs.value,
    segmentIndex,
  }
  routeDrawing.highlightSegment(routeId, segmentIndex)
  attachRouteFlyoutRender()
  updateRouteFlyoutPixel()
}

/** 关闭浮窗。只清地图侧展示态,绝不改动航路数据与选中航路 */
function closeRouteFlyout() {
  if (!routeFlyout.value) return
  routeFlyout.value = null
  routeDrawing.highlightSegment(null, null)
  detachRouteFlyoutRender()
}

/**
 * 浮窗与 Store 对账:航路被删除 / 隐藏 / 进入绘制编辑态 → 关闭;
 * 航段序号失效(航点被删) → 清掉高亮;其余情况内容直接读 Store 实时刷新。
 * 面板折叠/展开**不**关闭浮窗,只经 updateRouteFlyoutPixel() 重算锚点让位(540↔16)。
 */
function syncRouteFlyout() {
  const state = routeFlyout.value
  if (!state) return
  const route = routesStore.routes.find((item) => item.id === state.routeId)
  if (!route || !route.visible || routesStore.interactionMode !== 'idle') {
    closeRouteFlyout()
    return
  }
  if (state.segmentIndex !== null && state.segmentIndex > route.points.length - 1) {
    routeFlyout.value = { ...state, segmentIndex: null }
    routeDrawing.highlightSegment(null, null)
  }
  updateRouteFlyoutPixel()
}

watch(
  [
    () => routesStore.revision,
    () => routesStore.activeRouteId,
    () => routesStore.interactionMode,
    routePanelVisible,
    () => currentCrs.value,
  ],
  () => syncRouteFlyout(),
)

// ── Batch loading state ────────────────────────────────────────────
const selectedDatasetIds = shallowRef(new Set<string>())
/** Layer IDs the user has turned ON (selected). */
const selectedLayerIds = shallowRef(new Set<string>())
/** Layer IDs with active OpenLayers TileLayer objects. */
const attachedLayerIds = shallowRef(new Set<string>())
/** Layer IDs currently visible and allowed to request tiles. */
const activeLayerIds = shallowRef(new Set<string>())
/** Layer IDs waiting for their first tile to load. */
const warmingLayerIds = shallowRef(new Set<string>())
/** Layer IDs that are selected but temporarily sleeping (viewport/scale/budget). */
const suspendedLayerIds = shallowRef(new Set<string>())
/** Layer IDs the user explicitly forced to display, immune to smart suspend. */
const manuallyForcedLayerIds = shallowRef(new Set<string>())
/** Backward-compat alias: layers the user has turned on. */
const loadedLayerIds = selectedLayerIds
const loadingLayerIds = shallowRef(new Set<string>())
const failedLayerIds = ref(new Map<string, string>())
const renderMode = ref<ChartRenderMode>('smart')
const bulkProgress = ref<BulkLayerProgress | null>(null)
const bulkCancelled = ref(false)
const bulkGeneration = ref(0)
const renderGeneration = ref(0)
const lastBulkAttachedLayerIds = ref(new Set<string>())
/** Last profile used for batch loading — needed for bundle plan API. */
const lastLoadProfile = ref<S57LoadProfile>('core_chart')
let lastBundlePlanCacheKey = ''
type BundlePlanInput = { bundles: RenderBundleConfig[]; standaloneLayerIds: string[] }
let lastBundlePlanCache: BundlePlanInput | undefined
let bulkAbortController: AbortController | null = null
let reconcileTimer: number | undefined
let evictTimer: number | undefined
const layerLastInViewportTime = new Map<string, number>()
const layerWarmingStartTime = new Map<string, number>()

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
const tileCache = new LRUTileCache(TILE_CACHE_MAX_ENTRIES, TILE_CACHE_MAX_BYTES)
const tileRequestQueue = new TileRequestQueue(TILE_MAX_CONCURRENT_FETCH, TILE_MAX_QUEUED_FETCH)

// ── Merged group state (standard-mode TileWMS source sharing) ─────────
// When ENABLE_TILE_MERGING is on, layers are grouped by (serviceUrl,
// renderTransport) and share one TileWMS source with comma-separated
// LAYERS / per-layer STYLES.
interface MergedGroupRuntime {
  source: TileWMS
  memberIds: Set<string>
  pendingTiles: number
}
const mergedGroupRuntimes = new Map<string, MergedGroupRuntime>()
const mergedGroupMembers = new Map<string, string>()  // layerId → groupId
/** Groups whose shared-source params need rebuilding after member detach. */
const dirtyMergedGroups = new Set<string>()

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

// ── 冰情叠加(独立环境叠加层) ──────────────────────────────────────
// 与 S-57 图层状态体系彻底解耦:两个独立 XYZ TileLayer 直接挂到既有地图,
// 不进入 runtimeLayers / Render Bundle / 渲染调度;hover 复用唯一的
// pointermove 分发,不注册第二个地图监听。瓦片请求管线(限流队列 + LRU
// 缓存 + 丢弃即中止)复用海图同一套通用实例 —— 实测自管 <img> 请求会
// 堆积拖垮地图(会话 #26.1)。
const icePanelOpen = ref(false)
const environmentPanelOpen = ref(false)
const iceOverlay = useIceOverlay({
  getMap: () => map,
  getCrs: () => currentCrs.value,
  // 与海图瓦片共享的请求管线:全局并发上限 + 缓存复用 + 中止释放
  tileCache,
  tileRequestQueue,
  // 测量/识别/气象/航路绘制编辑/航路浮窗进行中 → 暂停冰情值查询
  // (优先级:航路浮窗/当前地图工具 > 冰情 hover > 普通经纬度 hover)
  canQueryValue: () =>
    routesStore.interactionMode === 'idle' &&
    measureMode.value === 'none' &&
    !queryMode.value &&
    !weatherMode.value &&
    !routeFlyout.value,
})
/** 时间轴让位:随图层面板折叠 / 航路面板展开自适应(不写死像素) */
const iceTimelineLeft = computed(() => (layerPanelCollapsed.value ? 16 : 300))
const iceTimelineRight = computed(() => (routePanelVisible.value ? 540 : 16))

// ── 环境图层(水深/风/流/浪) ────────────────────────────────────────
// 与海冰/海图同样只挂到既有唯一地图;不进入 runtimeLayers/bundle/scheduler。
const environmentOverlays = useEnvironmentOverlays({
  getMap: () => map,
  getCrs: () => currentCrs.value,
  tileCache,
  tileRequestQueue,
  canQuery: () =>
    routesStore.interactionMode === 'idle' &&
    measureMode.value === 'none' &&
    !queryMode.value &&
    !weatherMode.value &&
    !routeFlyout.value &&
    !iceOverlay.hover.value,
})
/** 环境叠加菜单中的冰情状态文案 */
const iceOverlayState = computed(() => {
  if (iceOverlay.error.value) return '不可用'
  if ((iceOverlay.info.value?.dates.length ?? 0) === 0) return '无数据'
  return iceOverlay.concentrationVisible.value || iceOverlay.thicknessVisible.value
    ? '已开启'
    : '未开启'
})

watch(layerSearch, () => {
  window.clearTimeout(layerSearchTimer)
  layerSearchTimer = window.setTimeout(() => {
    layerSearchDebounced.value = layerSearch.value
  }, 200)
})

// ── Render mode transitions ──────────────────────────────────────────
// reconcileRenderPlan returns early in standard mode, so composite bundles
// would otherwise linger on the map — dispose them when leaving smart mode.
// Per-layer TileWMS for bundle-covered layers is never created in smart mode
// (scheduler skips bundledLayerIds), so switching to standard must also
// re-attach those layers manually, otherwise the map goes blank.
watch(renderMode, (mode) => {
  if (!map) return
  if (mode === 'standard') {
    // Leaving smart mode: dispose composite bundles, then re-attach every
    // selected layer via shared merged-group TileWMS sources
    // (standard semantics = all on).
    disposeAllBundles(map)
    const selected = runtimeLayers.value.filter(
      (rt) => selectedLayerIds.value.has(rt.config.id) && !wmsLayers.has(rt.config.id),
    )
    attachRuntimeGroups(selected, undefined, true)
    return
  }
  // Entering smart/overview: per-layer TileWMS leftovers from standard mode
  // would double-render next to the rebuilt bundle composites — detach them
  // first, then let reconcileRenderPlan rebuild bundles and re-attach
  // standalone layers via executePerLayerPlan. (Overview fully suspends
  // layers; bundle disposal happens inside reconcileRenderPlan.)
  if (mode === 'smart' || mode === 'overview') {
    for (const runtime of runtimeLayers.value) {
      const lid = runtime.config.id
      if (selectedLayerIds.value.has(lid) && wmsLayers.has(lid)) {
        detachWmsLayer(runtime)
      }
    }
    reconcileRenderPlan()
  }
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
  const visibleRuntimes = runtimeLayers.value.filter((rt) => rt.visible)
  attachRuntimeGroups(visibleRuntimes, undefined, true)
  for (const runtime of visibleRuntimes) {
    const next = new Set(selectedLayerIds.value)
    next.add(runtime.config.id)
    selectedLayerIds.value = next
  }
  map.addLayer(measureLayer)
  map.addLayer(aisLayer)
  map.addLayer(routeDrawing.layer)
  iceOverlay.attach()
  environmentOverlays.attach()
  applyBaseMapVisibility()
  fitProjectInitialExtent()
  hoverEnabled = window.matchMedia?.('(hover: hover) and (pointer: fine)').matches ?? true
  hoverViewport = map.getViewport()
  hoverViewport.addEventListener('pointerleave', hideHover)
  hoverViewport.addEventListener('pointerleave', iceOverlay.clearHover)
  map.on('pointermove', (event) => {
    const [longitude, latitude] = toLonLat(event.coordinate, currentCrs.value)
    coordinateText.value = `${latitude.toFixed(5)}°, ${longitude.toFixed(5)}°`
    // 拖动期间不显示(平移时提示会跟着乱跑);非鼠标指针(触控)没有悬停语义
    const original = event.originalEvent as PointerEvent | undefined
    const pointerSuppressed =
      !hoverEnabled || original?.pointerType === 'touch' || original?.pointerType === 'pen'
    // 冰情 hover 与坐标提示共用唯一 pointermove;触控/拖动以 dragging=true 抑制查询
    iceOverlay.handlePointerMove({
      pixel: event.pixel,
      coordinate: event.coordinate,
      dragging: event.dragging || pointerSuppressed,
    })
    environmentOverlays.handlePointerMove({
      pixel: event.pixel,
      coordinate: event.coordinate,
      dragging: event.dragging || pointerSuppressed,
    })
    if (pointerSuppressed || event.dragging) {
      hideHover()
      return
    }
    hoverCoordinate = event.coordinate
    hoverPixel = event.pixel
    scheduleHover()
  })
  map.on('singleclick', async (event) => {
    // 航路绘制/编辑或测量进行中时,不触发要素识别 / 气象查询 / 航路选中
    if (routesStore.interactionMode !== 'idle' || measureMode.value !== 'none') return
    environmentOverlays.clearHover()
    const lonLat = toLonLat(event.coordinate, currentCrs.value) as [number, number]
    if (weatherMode.value) await queryWeather(lonLat)
    else if (queryMode.value) await identify(lonLat)
    else {
      // 命中航路 → 选中并弹浮窗;命中空白 → 只关浮窗,不动选中航路
      // 点选不依赖航路面板是否打开(面板折叠后仍可点击航路查看详情)
      const pick = routeDrawing.pickRouteAtPixel(event.pixel, event.coordinate)
      if (pick) openRouteFlyout(pick.routeId, event.coordinate, lonLat, pick.segmentIndex)
      else closeRouteFlyout()
    }
  })
  map.on('moveend', () => {
    window.clearTimeout(reconcileTimer)
    reconcileTimer = window.setTimeout(reconcileRenderPlan, SMART_RECONCILE_DEBOUNCE_MS)
    environmentOverlays.scheduleRefreshVectors()
    // 滚轮缩放后指针没动,提示里的坐标/小数位需要按新分辨率自校正
    if (hoverCoordinate) scheduleHover()
  })
  // Initial reconcile
  reconcileRenderPlan()
}

function isNonSpatial(layer: MapLayerConfig): boolean {
  const t = (layer.geometryType || '').toLowerCase()
  return t === 'unknown' || t === 'none' || t === '' || t === '无'
}

type AttachResult = 'attached' | 'already-loaded' | 'non-spatial'

/**
 * Compute a stable zIndex for WMS tile layers based on S-57 object class semantics.
 * Fill layers draw at the bottom, point features and aids draw on top.
 */
function layerZIndex(objectClass: string | null | undefined): number {
  const code = (objectClass ?? '').toUpperCase()
  if (['DEPARE', 'LNDARE', 'ICEARE', 'SEAARE'].includes(code)) return 10
  if (['DEPCNT'].includes(code)) return 20
  if (['COALNE', 'NAVLNE', 'FAIRWY'].includes(code)) return 25
  if (['WRECKS', 'OBSTRN', 'UWTROC'].includes(code)) return 30
  if (['SOUNDG'].includes(code)) return 35
  if (['LIGHTS', 'BOYSPP', 'BOYLAT', 'BOYCAR', 'BCNSPP', 'BCNLAT', 'BCNCAR'].includes(code)) return 40
  return 15
}

/**
 * Create a tileLoadFunction that retries recoverable HTTP errors
 * (429, 502, 503, 504) and network failures with exponential backoff.
 * Uses the existing TILE_RETRY_MAX_ATTEMPTS / TILE_RETRY_BASE_DELAY_MS constants.
 */
function createRetryTileLoadFunction(stats: PerLayerStatsManager): (tile: any, src: string) => void {
  return (tile, src) => {
    const img = tile.getImage() as HTMLImageElement
    const controller = new AbortController()
    let attempts = 0

    // Abort in-flight fetch when OpenLayers discards the tile (pan/zoom).
    tile.addEventListener('change', () => {
      // OpenLayers TileState: 0=IDLE, 1=LOADING, 2=LOADED, 3=ERROR, 4=ABORT
      if ((tile as any).getState?.() === 4) {
        controller.abort()
      }
    })

    const tryLoad = () => {
      if (controller.signal.aborted) return
      attempts++

      // 1. Check LRU tile cache first — avoid redundant fetches for
      //    previously loaded tiles (pan-back, layer toggle, etc.).
      const cached = tileCache.get(src)
      if (cached) {
        const objectUrl = URL.createObjectURL(cached)
        img.onload = () => URL.revokeObjectURL(objectUrl)
        img.src = objectUrl
        return
      }

      // 2. Fetch tile from GeoServer via the concurrency-limited queue.
      tileRequestQueue.fetch(src, controller.signal)
        .then((response) => {
          if (response.ok) {
            return response.blob()
          }
          // Only retry recoverable HTTP errors: 429, 502, 503, 504
          if (
            [429, 502, 503, 504].includes(response.status) &&
            attempts < TILE_RETRY_MAX_ATTEMPTS
          ) {
            stats.recordRetry()
            const delay = TILE_RETRY_BASE_DELAY_MS * Math.pow(2, attempts - 1)
            setTimeout(tryLoad, delay)
            return null
          }
          // Non-recoverable (400, 404, 500, etc.) or retries exhausted:
          // mark the tile errored so OpenLayers fires tileloaderror (drains
          // warming, marks the layer errored) and re-requests the tile on
          // the next render. Without this the tile stays LOADING forever.
          tile.setState(TileState.ERROR)
          return null
        })
        .then((blob) => {
          if (blob) {
            // Cache successful responses for future pan-back / toggle scenarios.
            tileCache.set(src, blob)
            const objectUrl = URL.createObjectURL(blob)
            img.onload = () => URL.revokeObjectURL(objectUrl)
            img.src = objectUrl
          }
        })
        .catch((err) => {
          if (controller.signal.aborted) return
          // Only retry on network failures (TypeError), not HTTP errors
          if (err instanceof TypeError && attempts < TILE_RETRY_MAX_ATTEMPTS) {
            stats.recordRetry()
            const delay = TILE_RETRY_BASE_DELAY_MS * Math.pow(2, attempts - 1)
            setTimeout(tryLoad, delay)
          } else if (!controller.signal.aborted) {
            // Retries exhausted or unrecoverable rejection (queue overflow
            // QuotaExceededError etc.) — mark errored so OL retries later.
            tile.setState(TileState.ERROR)
          }
        })
    }
    tryLoad()
  }
}

function attachWmsLayer(
  runtime: RuntimeLayer,
  opts?: { extent?: number[]; minZoom?: number | null; maxZoom?: number | null; visible?: boolean },
  sharedSource?: TileWMS,
): AttachResult {
  if (!map || wmsLayers.has(runtime.config.id)) return 'already-loaded'
  if (isNonSpatial(runtime.config)) {
    runtime.loadState = 'loaded'
    return 'non-spatial'
  }

  const source = sharedSource ?? (() => {
    // Cacheable layers route through the GWC tile endpoint when available.
    // Force WMS 1.1.1 so OpenLayers emits SRS instead of CRS — GWC WMS-C
    // gridsets are keyed on SRS, avoiding 1.3.0/CRS handling differences.
    const useGwc =
      ENABLE_GWC_TILES && runtime.config.renderTransport === 'gwc_wms' && !!runtime.config.tileServiceUrl
    const s = new TileWMS({
      url: browserGeoServerUrl(useGwc ? runtime.config.tileServiceUrl! : runtime.config.serviceUrl),
      params: {
        LAYERS: runtime.config.serviceLayerName,
        TILED: true,
        STYLES: runtime.config.styleName || '',
        ...(useGwc ? { VERSION: '1.1.1' } : {}),
      },
      crossOrigin: 'anonymous',
      transition: 0,
      tileLoadFunction: createRetryTileLoadFunction(perfStats),
    })
    s.on('tileloadstart', () => {
      runtime.pendingTiles += 1
      perfStats.recordTileStart(runtime.config.id)
      window.clearTimeout(runtime.loadStateTimer)
      runtime.loadStateTimer = window.setTimeout(() => {
        if (runtime.pendingTiles > 0) {
          runtime.loadState = 'loading'
        }
      }, 300)
    })
    s.on('tileloadend', () => {
      runtime.pendingTiles = Math.max(0, runtime.pendingTiles - 1)
      perfStats.recordTileEnd(runtime.config.id)
      if (runtime.pendingTiles === 0) {
        window.clearTimeout(runtime.loadStateTimer)
        if (runtime.loadState !== 'error') runtime.loadState = 'loaded'
        // Drain from warming queue — first tile(s) successfully loaded
        const nextWarm = new Set(warmingLayerIds.value)
        if (nextWarm.delete(runtime.config.id)) {
          warmingLayerIds.value = nextWarm
        }
      }
    })
    s.on('tileloaderror', () => {
      runtime.pendingTiles = Math.max(0, runtime.pendingTiles - 1)
      perfStats.recordTileError(runtime.config.id)
      window.clearTimeout(runtime.loadStateTimer)
      runtime.loadState = 'error'
      // Drain from warming queue on error too — allow next candidate to proceed
      const nextWarm = new Set(warmingLayerIds.value)
      if (nextWarm.delete(runtime.config.id)) {
        warmingLayerIds.value = nextWarm
      }
    })
    return s
  })()

  const tileLayer = new TileLayer({
    source,
    opacity: runtime.opacity,
    zIndex: layerZIndex(runtime.config.objectClass),
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

  const lid = runtime.config.id
  const groupId = mergedGroupMembers.get(lid)

  if (groupId) {
    // Merged group member — release layer from group, dispose shared
    // source only when the last member is detached. Remaining members'
    // shared-source LAYERS/STYLES are rebuilt (coalesced via microtask)
    // so the removed layer name stops being requested.
    mergedGroupMembers.delete(lid)
    const grp = mergedGroupRuntimes.get(groupId)
    if (grp) {
      grp.memberIds.delete(lid)
      if (grp.memberIds.size === 0) {
        // Last member gone — dispose shared source and group runtime
        grp.source.dispose()
        mergedGroupRuntimes.delete(groupId)
        dirtyMergedGroups.delete(groupId)
      } else {
        dirtyMergedGroups.add(groupId)
        queueMicrotask(flushDirtyMergedGroups)
      }
    }
    // Dispose the individual TileLayer (shared source survives if group
    // has remaining members).
    tileLayer.dispose()
  } else {
    // Standalone layer — dispose both TileLayer and its private source
    tileLayer.dispose()
  }

  wmsLayers.delete(lid)
  window.clearTimeout(runtime.loadStateTimer)
  runtime.pendingTiles = 0
  runtime.loadState = 'idle'
  runtime.loadStateTimer = undefined
  // Clean up from state sets
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
  layerWarmingStartTime.delete(lid)
}

// ── Merged group lifecycle ────────────────────────────────────────────

/**
 * Register a shared merged-group source: member→group mapping, group
 * runtime, and group-level tile events. Event closures iterate
 * grpRuntime.memberIds (not a captured snapshot) so member-set updates in
 * syncMergedGroup / detachWmsLayer stay reflected.
 */
function registerMergedGroup(gid: string, group: MergeGroup, source: TileWMS): void {
  for (const lid of group.layerIds) {
    mergedGroupMembers.set(lid, gid)
  }

  const grpRuntime: MergedGroupRuntime = { source, memberIds: new Set(group.layerIds), pendingTiles: 0 }
  mergedGroupRuntimes.set(gid, grpRuntime)

  // Group-level tile event wiring:
  // When tiles load for the composite LAYERS param, update ALL member
  // runtimes — each tile covers every layer in the group.
  source.on('tileloadstart', () => {
    grpRuntime.pendingTiles += 1
    for (const lid of grpRuntime.memberIds) {
      const rt = runtimeLayers.value.find((r) => r.config.id === lid)
      if (!rt) continue
      rt.pendingTiles += 1
      perfStats.recordTileStart(lid)
      window.clearTimeout(rt.loadStateTimer)
      rt.loadStateTimer = window.setTimeout(() => {
        if (rt.pendingTiles > 0) rt.loadState = 'loading'
      }, 300)
    }
  })
  source.on('tileloadend', () => {
    grpRuntime.pendingTiles = Math.max(0, grpRuntime.pendingTiles - 1)
    for (const lid of grpRuntime.memberIds) {
      const rt = runtimeLayers.value.find((r) => r.config.id === lid)
      if (!rt) continue
      rt.pendingTiles = Math.max(0, rt.pendingTiles - 1)
      perfStats.recordTileEnd(lid)
      if (rt.pendingTiles === 0) {
        window.clearTimeout(rt.loadStateTimer)
        if (rt.loadState !== 'error') rt.loadState = 'loaded'
        const nextWarm = new Set(warmingLayerIds.value)
        if (nextWarm.delete(lid)) warmingLayerIds.value = nextWarm
      }
    }
  })
  source.on('tileloaderror', () => {
    grpRuntime.pendingTiles = Math.max(0, grpRuntime.pendingTiles - 1)
    for (const lid of grpRuntime.memberIds) {
      const rt = runtimeLayers.value.find((r) => r.config.id === lid)
      if (!rt) continue
      rt.pendingTiles = Math.max(0, rt.pendingTiles - 1)
      perfStats.recordTileError(lid)
      window.clearTimeout(rt.loadStateTimer)
      rt.loadState = 'error'
      const nextWarm = new Set(warmingLayerIds.value)
      if (nextWarm.delete(lid)) warmingLayerIds.value = nextWarm
    }
  })
}

/**
 * Reuse an existing group runtime for a (possibly changed) group: update
 * the member set and rebuild the shared source's LAYERS/STYLES params.
 * Covers re-attaching a full group after a subset was detached.
 */
function syncMergedGroup(gid: string, group: MergeGroup): TileWMS {
  const grp = mergedGroupRuntimes.get(gid)!
  const incoming = new Set(group.layerIds)
  const same =
    incoming.size === grp.memberIds.size &&
    [...incoming].every((id) => grp.memberIds.has(id))
  if (!same) {
    for (const id of grp.memberIds) if (!incoming.has(id)) mergedGroupMembers.delete(id)
    for (const id of incoming) if (!grp.memberIds.has(id)) mergedGroupMembers.set(id, gid)
    grp.memberIds = incoming
    grp.source.updateParams(joinLayerParams(group.layerNames, group.styles))
  }
  return grp.source
}

/**
 * Rebuild shared-source LAYERS/STYLES for groups whose membership changed.
 * Coalesced via microtask: a synchronous detach burst (mode switch,
 * projection switch, unload-all) triggers one rebuild instead of one per
 * detached member.
 */
function flushDirtyMergedGroups(): void {
  for (const gid of [...dirtyMergedGroups]) {
    dirtyMergedGroups.delete(gid)
    const grp = mergedGroupRuntimes.get(gid)
    if (!grp || grp.memberIds.size === 0) continue
    const names: string[] = []
    const styles: string[] = []
    for (const memberId of grp.memberIds) {
      const rt = runtimeLayers.value.find((r) => r.config.id === memberId)
      if (!rt) continue
      names.push(rt.config.serviceLayerName)
      styles.push(rt.config.styleName || '')
    }
    grp.source.updateParams(joinLayerParams(names, styles))
  }
}

/**
 * Attach runtime layers via shared merged-group TileWMS sources.
 * When ENABLE_TILE_MERGING is off, falls back to per-layer sources.
 * Members keep their own minZoom/maxZoom (and optionally extent) — the
 * shared source only carries LAYERS/STYLES.
 */
function attachRuntimeGroups(
  runtimes: RuntimeLayer[],
  optionsFor?: (rt: RuntimeLayer) => { extent?: number[] } | undefined,
  visible = true,
): void {
  if (!map) return
  const eligible = runtimes.filter((rt) => !wmsLayers.has(rt.config.id) && !isNonSpatial(rt.config))
  if (eligible.length === 0) return

  if (!ENABLE_TILE_MERGING) {
    for (const rt of eligible) {
      attachWmsLayer(rt, {
        ...(optionsFor?.(rt) ?? {}),
        minZoom: rt.config.minZoom,
        maxZoom: rt.config.maxZoom,
        visible,
      })
    }
    return
  }

  const groups = groupResolvedLayers(eligible.map((rt) => toMergeableLayer(rt.config)))
  const tileLoadFn = createRetryTileLoadFunction(perfStats)
  for (const group of groups) {
    const gid = group.layerIds.slice().sort().join('|')
    const source = mergedGroupRuntimes.has(gid)
      ? syncMergedGroup(gid, group)
      : (() => {
          const s = createMergedTileSource(group, TileWMS, tileLoadFn)
          registerMergedGroup(gid, group, s)
          return s
        })()
    for (const lid of group.layerIds) {
      const rt = eligible.find((r) => r.config.id === lid)
      if (!rt) continue
      attachWmsLayer(rt, {
        extent: optionsFor?.(rt)?.extent,
        minZoom: rt.config.minZoom,
        maxZoom: rt.config.maxZoom,
        visible,
      }, source)
    }
  }
}

async function toggleDataset(dataset: RuntimeDataset) {
  dataset.expanded = !dataset.expanded
  if (!dataset.expanded || dataset.loading || !config.value) return
  // If layers are already populated (e.g., by batch load), skip API re-fetch
  if (dataset.layers.length > 0) {
    dataset.loaded = true
    return
  }
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

    if (ENABLE_RENDER_BUNDLES && renderMode.value === 'smart') {
      // Bundle mode: trigger scheduler to rebuild bundles atomically.
      // Do NOT immediately detach — the bundle handles the transition.
      reconcileRenderPlan()
    } else {
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
  // Dispose all composite bundles and invalidate bundle plan cache
  disposeAllBundles(map)
  lastBundlePlanCacheKey = ''
  lastBundlePlanCache = undefined
  // Invalidate tile cache and abort pending requests — different CRS
  // produces different tile URLs
  tileRequestQueue.abortAll()
  tileCache.clear()
  currentCrs.value = crs
  applyBaseMapVisibility()
  map.setView(createView(crs))
  fitProjectInitialExtent()
  reloadAisGeometry()
  routeDrawing.reloadRouteGeometry()
  syncMeasureForProjection()
  // 冰情:保留日期/可见性/透明度,只替换 XYZ Source 与 TileGrid
  iceOverlay.reloadForProjection()
  environmentOverlays.reloadForProjection()
  // Re-attach only previously selected layers (shared merged-group sources)
  const toReattach = runtimeLayers.value.filter((rt) => savedSelectedIds.has(rt.config.id))
  for (const runtime of toReattach) runtime.visible = true
  attachRuntimeGroups(
    toReattach,
    (rt) => ({ extent: transformLayerExtent(rt.config.extent, currentCrs.value) }),
    true,
  )
  // Restore selectedLayerIds (they survive the projection switch)
  selectedLayerIds.value = savedSelectedIds
  // Recalculate render plan for new projection
  reconcileRenderPlan()
}

// ── Layer status display ──────────────────────────────────────────

function layerStatusLabel(layerId: string): string {
  if (failedLayerIds.value.has(layerId)) return '加载失败'
  if (warmingLayerIds.value.has(layerId)) return '加载中'
  // Bundled layers are selected but never enter attached/active sets —
  // they render via composite bundles, so report them as displayed.
  if (renderMode.value === 'smart' && isLayerCoveredByBundle(layerId)) return '已显示'
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
    loadProfile: (r.config.metadata as any)?.s57?.loadProfile ?? '',
    minScaleDenominator: (r.config.metadata as any)?.s57?.minScaleDenominator ?? null,
    maxScaleDenominator: (r.config.metadata as any)?.s57?.maxScaleDenominator ?? null,
    renderCost: (r.config.metadata as any)?.s57?.renderCost ?? null,
  }))
}

/**
 * Fetch (or reuse the cached) bundle render plan for a layer-id set.
 * Cached by (sorted layer IDs + projection) — the bundle structure only
 * changes when layer selection or projection changes. Returns undefined
 * on fetch failure (caller falls back to per-layer rendering).
 */
async function fetchBundlePlanInputFor(
  layerIds: ReadonlySet<string>,
  crs: string,
  viewExtent: number[],
  zoom: number,
): Promise<BundlePlanInput | undefined> {
  const key = [...layerIds].sort().join(',') + '|' + crs
  if (lastBundlePlanCacheKey === key && lastBundlePlanCache) return lastBundlePlanCache
  if (!ENABLE_RENDER_BUNDLES || layerIds.size === 0) return undefined
  const projectId = config.value?.project.id
  if (!projectId) return undefined
  try {
    const renderPlanResp = await fetchRenderPlan(projectId, {
      layerIds: [...layerIds],
      profile: lastLoadProfile.value,
      projection: crs,
      renderMode: 'smart',
      viewExtent,
      zoom: Math.round(zoom),
    })
    const input: BundlePlanInput = {
      bundles: renderPlanResp.bundles,
      standaloneLayerIds: renderPlanResp.standaloneLayers.map((s) => s.layerId),
    }
    lastBundlePlanCacheKey = key
    lastBundlePlanCache = input
    return input
  } catch {
    // Fall back to per-layer smart mode on error
    return undefined
  }
}

async function reconcileRenderPlan() {
  if (!map || renderMode.value === 'standard') return

  // Drain stale warming entries — allows the queue to progress when a layer
  // never fires tileloadend (e.g. out-of-viewport tiles are never requested).
  const now = Date.now()
  let warmingChanged = false
  let nextWarm = warmingLayerIds.value
  for (const lid of warmingLayerIds.value) {
    const start = layerWarmingStartTime.get(lid) ?? now
    if (now - start > TILE_WARMING_TIMEOUT_MS) {
      if (!warmingChanged) { nextWarm = new Set(warmingLayerIds.value); warmingChanged = true }
      nextWarm.delete(lid)
      layerWarmingStartTime.delete(lid)
    }
  }
  if (warmingChanged) warmingLayerIds.value = nextWarm

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

  // Phase 1: smart mode with bundles — fetch render plan from API
  // (cached by sorted layer IDs + projection).
  const bundlePlanInput =
    ENABLE_RENDER_BUNDLES && renderMode.value === 'smart'
      ? await fetchBundlePlanInputFor(selectedLayerIds.value, currentCrs.value, extent, zoom)
      : undefined

  // No bundle plan to reconcile against (empty selection or fetch failure):
  // dispose any attached bundles so stale composites don't leak on the map,
  // then fall through to the per-layer path.
  if (!bundlePlanInput && getAllBundleRuntimes().length > 0) {
    disposeAllBundles(map!)
  }

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
    bundlePlanInput,
    attachedBundleIds: new Set(getAllBundleRuntimes().map((r) => r.config.bundleId)),
  })

  // Execute bundle plan if present (smart mode with bundles)
  if (plan.bundlePlan) {
    executeBundlePlan(plan.bundlePlan, plan)
  } else {
    // Execute per-layer plan (existing logic)
    executePerLayerPlan(plan)
  }

  // Update overview WMTS visibility
  setOverviewVisible(plan.overviewVisible)

  // Schedule LRU eviction check
  window.clearTimeout(evictTimer)
  evictTimer = window.setTimeout(runLruEviction, SMART_SUSPEND_EVICT_DELAY_MS)
}

/** Execute the per-layer attach/suspend/detach plan. */
function executePerLayerPlan(plan: ReturnType<typeof buildRenderPlan>) {
  // Phase 1 — detach (dispose + remove from all state sets)
  for (const id of plan.detach) {
    const runtime = runtimeLayers.value.find((r) => r.config.id === id)
    if (runtime) detachWmsLayer(runtime)
  }

  if (plan.suspend.length > 0) {
    const susAdd = new Set(suspendedLayerIds.value)
    const actDel = new Set(activeLayerIds.value)
    for (const id of plan.suspend) {
      const layer = wmsLayers.get(id)
      if (layer) layer.setVisible(false)
      susAdd.add(id)
      actDel.delete(id)
    }
    suspendedLayerIds.value = susAdd
    activeLayerIds.value = actDel
  }

  // Phase 3 — attach (create TileWMS, invisible initially)
  if (plan.attach.length > 0) {
    const warmAdd = new Set(warmingLayerIds.value)
    const now = Date.now()
    for (const id of plan.attach) {
      const runtime = runtimeLayers.value.find((r) => r.config.id === id)
      if (!runtime || attachedLayerIds.value.has(id)) continue
      const projExtent = transformLayerExtent(runtime.config.extent, currentCrs.value)
      attachWmsLayer(runtime, {
        extent: projExtent,
        minZoom: runtime.config.minZoom,
        maxZoom: runtime.config.maxZoom,
        visible: false,
      })
      warmAdd.add(id)
      layerWarmingStartTime.set(id, now)
      layerLastInViewportTime.set(id, now)
    }
    warmingLayerIds.value = warmAdd
  }

  // Phase 4 — activate (setVisible true)
  if (plan.activate.length > 0) {
    const actAdd = new Set(activeLayerIds.value)
    const susDel = new Set(suspendedLayerIds.value)
    const now = Date.now()
    for (const id of plan.activate) {
      const layer = wmsLayers.get(id)
      if (layer) layer.setVisible(true)
      actAdd.add(id)
      susDel.delete(id)
      layerLastInViewportTime.set(id, now)
    }
    activeLayerIds.value = actAdd
    suspendedLayerIds.value = susDel
  }
}

/** Execute a bundle-aware plan: create/destroy composite TileWMS layers. */
function executeBundlePlan(
  bundlePlan: BundleRenderPlan,
  plan: ReturnType<typeof buildRenderPlan>,
) {
  // Safety net: per-layer TileWMS leftovers for bundle-covered layers (e.g.
  // batch attach fallback when the plan fetch failed, or layers attached
  // before the bundle plan existed) would double-render next to bundles —
  // "bundles win", so detach them. The pre-fetch exclusion in the batch
  // path makes this the rare fallback, not the common path.
  for (const id of bundlePlan.bundledLayerIds) {
    const runtime = runtimeLayers.value.find((r) => r.config.id === id)
    if (runtime && wmsLayers.has(id)) {
      detachWmsLayer(runtime)
    }
  }

  // Detach removed bundles
  for (const bundleId of bundlePlan.detachBundles) {
    detachBundle(bundleId, map!)
  }

  // Suspend bundles (setVisible false)
  for (const bundleId of bundlePlan.suspendBundles) {
    setBundleVisible(bundleId, false)
  }

  // Attach new bundles
  for (const config of bundlePlan.attachBundles) {
    if (!map) continue
    attachBundle(
      config,
      map,
      createRetryTileLoadFunction(perfStats) as any,
      (_bundleId) => {
        // Bundle warming complete — no per-layer state to update
      },
      (_bundleId, _error) => {
        // Bundle failed — error is tracked in bundle runtime
      },
    )
  }

  // Activate bundles — only 'failed' / 'replacing' runtimes stay hidden.
  // Requiring 'active' here deadlocked suspended bundles: OpenLayers stops
  // requesting tiles from an invisible TileLayer, so a bundle suspended while
  // still 'warming' never reaches 'active' and could never be re-shown.
  // Warming bundles are re-shown (tile requests resume → tileloadend → active);
  // attach already shows in-viewport bundles immediately.
  for (const bundleId of bundlePlan.activateBundles) {
    const runtime = getBundleRuntime(bundleId)
    if (runtime && runtime.status !== 'failed' && runtime.status !== 'replacing') {
      setBundleVisible(bundleId, true)
    }
  }

  // Handle standalone layers through existing per-layer path
  executePerLayerPlan(plan)
}

function setOverviewVisible(visible: boolean) {
  // Toggle the polar_global_enc_overview basemap visibility.
  // The overview WMTS is registered as a configured basemap; locate its OL layer.
  if (!map) return
  const layers = map.getLayers().getArray()
  for (const bm of baseMaps.value) {
    if (bm.name.includes('全球海图概览') && bm.crs === currentCrs.value) {
      for (const l of layers) {
        if (l instanceof TileLayer && l.getClassName() === 'map-base-layer') {
          const src = l.getSource()
          if (src instanceof WMTS) {
            const urls = src.getUrls?.() ?? []
            if (urls.some((u) => u.includes('polar_global_enc_overview'))) {
              l.setVisible(visible)
              return
            }
          }
        }
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
  lastLoadProfile.value = profile  // remember for bundle plan API
  lastBundlePlanCacheKey = ''        // invalidate bundle cache on new batch
  lastBundlePlanCache = undefined
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
              renderTransport: rl.renderTransport,
              tileServiceUrl: rl.tileServiceUrl,
              cacheable: rl.cacheable,
              metadata: { s57: { loadProfile: rl.loadProfile } },
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

    // Mark resolved datasets as loaded so toggleDataset doesn't re-fetch API,
    // and the sidebar can show layers expanded immediately.
    for (const ds of response.datasets) {
      const runtimeDs = runtimeDatasets.value.find((d) => d.config.id === ds.datasetId)
      if (runtimeDs && ds.layers.length > 0) {
        runtimeDs.loaded = true
      }
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

    // Smart-mode dedup: pre-fetch the bundle plan for the projected
    // selection (selected ∪ candidates) so batch attach can skip
    // bundle-covered layers — they render via composite bundles and must
    // not get per-layer TileWMS sources. The cache key matches the one the
    // final reconcileRenderPlan() computes after attach → no duplicate
    // plan fetch. On failure bundleCoveredIds stays empty: the full merged
    // batch attach runs and executeBundlePlan's safety net detaches the
    // leftovers once the bundles exist.
    let bundleCoveredIds = new Set<string>()
    if (ENABLE_RENDER_BUNDLES && renderMode.value === 'smart' && map && candidates.length > 0) {
      const view = map.getView()
      const size = map.getSize()
      if (view && size) {
        const projected = new Set<string>([...selectedLayerIds.value, ...candidates.map((c) => c.id)])
        const planInput = await fetchBundlePlanInputFor(
          projected,
          currentCrs.value,
          view.calculateExtent(size) as number[],
          view.getZoom() ?? 4,
        )
        if (planInput) {
          for (const b of planInput.bundles) {
            for (const lid of b.layerIds) bundleCoveredIds.add(lid)
          }
        }
      }
    }
    await loadResolvedLayersInBatches(candidates, generation, bundleCoveredIds)

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
    // Populate smart-scheduler state sets (active/suspended/warming).
    // Batch load attaches layers directly without going through reconcile,
    // so all three sets are empty until the first reconcile runs.
    reconcileRenderPlan()
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
  bundleCoveredIds: ReadonlySet<string> = new Set(),
) {
  if (!map || !config.value) return

  // ── Smart-mode dedup: bundle-covered candidates render via composite
  // bundles (created by the final reconcileRenderPlan) — record them as
  // selected without creating per-layer OL sources, so they don't double
  // render next to their bundles.
  const toAttach: BulkResolvedLayer[] = []
  for (const candidate of candidates) {
    if (!bundleCoveredIds.has(candidate.id)) {
      toAttach.push(candidate)
      continue
    }
    const runtime = runtimeLayers.value.find((r) => r.config.id === candidate.id)
    if (!runtime) continue
    if (loadingLayerIds.value.has(candidate.id) || selectedLayerIds.value.has(candidate.id)) {
      if (bulkProgress.value) bulkProgress.value.skipped++
      continue
    }
    runtime.visible = true
    const selNext = new Set(selectedLayerIds.value)
    selNext.add(candidate.id)
    selectedLayerIds.value = selNext
    const attachNext = new Set(lastBulkAttachedLayerIds.value)
    attachNext.add(candidate.id)
    lastBulkAttachedLayerIds.value = attachNext
    if (bulkProgress.value) {
      bulkProgress.value.succeeded++
      bulkProgress.value.processed++
    }
  }

  // ── Pre-group candidates when merging is enabled ──────────────────
  // Groups share one TileWMS source with comma-separated LAYERS param,
  // drastically reducing HTTP request count for same-dataset layers.
  const groups = ENABLE_TILE_MERGING ? groupResolvedLayers(toAttach) : null
  // Pre-create shared sources and wire group-level tile events
  const groupSourceMap = new Map<string, TileWMS>() // groupKey → shared source
  if (groups) {
    const tileLoadFn = createRetryTileLoadFunction(perfStats)
    for (const group of groups) {
      const gid = group.layerIds.sort().join('|') // deterministic group id
      if (mergedGroupRuntimes.has(gid)) continue   // already attached
      const source = createMergedTileSource(group, TileWMS, tileLoadFn)
      groupSourceMap.set(gid, source)
      registerMergedGroup(gid, group, source)
    }
  }

  // ── Build the flat ordered list for batch iteration ──────────────
  // With merging: one "batch unit" = one group (creating 1 source + N layers).
  // Without merging: one "batch unit" = one candidate (original behaviour).
  type BatchItem =
    | { kind: 'merged'; group: MergeGroup; source: TileWMS }
    | { kind: 'single'; candidate: BulkResolvedLayer }

  const items: BatchItem[] = (() => {
    if (!groups || !groupSourceMap) {
      return toAttach.map((c) => ({ kind: 'single' as const, candidate: c }))
    }
    const result: BatchItem[] = []
    const seenLayerIds = new Set<string>()
    for (const group of groups) {
      const gid = group.layerIds.sort().join('|')
      const source = groupSourceMap.get(gid)
      if (!source) continue
      for (const lid of group.layerIds) seenLayerIds.add(lid)
      result.push({ kind: 'merged', group, source })
    }
    // Append any candidates not covered by any group (edge case)
    for (const c of toAttach) {
      if (!seenLayerIds.has(c.id)) {
        result.push({ kind: 'single', candidate: c })
      }
    }
    return result
  })()

  // ── Batch iteration ──────────────────────────────────────────────
  for (let i = 0; i < items.length; i += BULK_ATTACH_BATCH_SIZE) {
    if (bulkCancelled.value || bulkGeneration.value !== generation) break

    const batch = items.slice(i, i + BULK_ATTACH_BATCH_SIZE)
    for (const item of batch) {
      if (item.kind === 'merged') {
        // Attach all members of this group using the shared source
        for (const lid of item.group.layerIds) {
          const runtime = runtimeLayers.value.find((r) => r.config.id === lid)
          if (!runtime) continue
          if (loadingLayerIds.value.has(lid) || selectedLayerIds.value.has(lid)) {
            if (bulkProgress.value) bulkProgress.value.skipped++
            continue
          }

          const loadingNext = new Set(loadingLayerIds.value)
          loadingNext.add(lid)
          loadingLayerIds.value = loadingNext

          try {
            const resolved = candidates.find((c) => c.id === lid)
            const extent = resolved ? transformLayerExtent(resolved.extent, currentCrs.value) : undefined
            // Per-member zoom ranges: the shared source only carries
            // LAYERS/STYLES — each member's TileLayer gates its own range.
            const result = attachWmsLayer(runtime, {
              extent,
              minZoom: resolved?.minZoom ?? undefined,
              maxZoom: resolved?.maxZoom ?? undefined,
              visible: false,
            }, item.source)
            if (result === 'attached') {
              runtime.visible = true
              const selNext = new Set(selectedLayerIds.value)
              selNext.add(lid)
              selectedLayerIds.value = selNext
              const attachNext = new Set(lastBulkAttachedLayerIds.value)
              attachNext.add(lid)
              lastBulkAttachedLayerIds.value = attachNext
              if (bulkProgress.value) {
                bulkProgress.value.succeeded++
                bulkProgress.value.attachedLayerIds.push(lid)
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
                layerId: lid,
                layerName: runtime.config.name,
                message: err instanceof Error ? err.message : '加载失败',
              })
            }
            const failedNext = new Map(failedLayerIds.value)
            failedNext.set(lid, err instanceof Error ? err.message : '加载失败')
            failedLayerIds.value = failedNext
          } finally {
            const loadingFinal = new Set(loadingLayerIds.value)
            loadingFinal.delete(lid)
            loadingLayerIds.value = loadingFinal
            if (bulkProgress.value) bulkProgress.value.processed++
          }
        }
      } else {
        // Original per-layer path (merging disabled or edge case)
        const resolved = item.candidate
        const runtime = runtimeLayers.value.find((r) => r.config.id === resolved.id)
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
    }

    // Wait between batches (unless cancelled or generation changed)
    if (i + BULK_ATTACH_BATCH_SIZE < items.length) {
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
  // Selection change invalidates the bundle cache key — reconcile so
  // stale bundles are detached by the scheduler.
  reconcileRenderPlan()
  ElMessage.success('已卸载所选数据集的图层')
}

function unloadAllChartLayers() {
  // Only unload business chart layers (from runtimeLayers), leave base maps,
  // AIS, weather, measure, highlight layers untouched.
  for (const runtime of runtimeLayers.value) {
    detachWmsLayer(runtime)
  }
  if (map) disposeAllBundles(map)
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
  // Selection change invalidates the bundle cache key — reconcile so
  // stale bundles are detached by the scheduler.
  reconcileRenderPlan()
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
  // Selection change invalidates the bundle cache key — reconcile so
  // stale bundles are detached by the scheduler.
  reconcileRenderPlan()
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

/**
 * 记录测量真值并生成结果文本。
 * 文本一律由 WGS84 真值生成(与当前投影无关),因此切换投影后重算必然同值 ——
 * 不存在「旧投影几何配上新投影解释」的错值。
 */
function setMeasureDraft(draft: MeasureDraft | null) {
  measureDraft.value = draft
  measureText.value = draft ? formatMeasureResult(draft) : ''
}

/**
 * 按当前投影从真值重建测量显示几何。
 * 只在投影切换后调用:常规测量路径下 ol Draw 画出的要素本身就是当前投影的正确
 * 几何,不需要重建 —— 而且 drawend 是在 ol 把要素加入 source **之前**派发的
 * (ol/interaction/Draw.js finishDrawing),若在 drawend 里 clear source,
 * 会与 ol 随后的 addFeature 撞成重复图形。
 */
function rebuildMeasureGeometry() {
  measureSource.clear()
  const draft = measureDraft.value
  if (!draft) return
  const geometry = buildMeasureGeometry(draft, currentCrs.value)
  if (geometry) measureSource.addFeature(new Feature(geometry))
}

function activateMeasure(type: 'LineString' | 'Polygon') {
  if (!map) return
  routesStore.setInteractionMode('idle') // 互斥:结束航路绘制/编辑
  queryMode.value = false
  weatherMode.value = false
  closeRouteFlyout() // 测量期间不弹航路浮窗,也不误选航线
  if (measureInteraction) map.removeInteraction(measureInteraction)
  measureSource.clear()
  measureDraft.value = null // 开始新测量即作废旧结果
  measureText.value = '单击开始绘制，双击结束'
  measureInteraction = new Draw({ source: measureSource, type })
  measureMode.value = type
  measureInteraction.on('drawend', (event) => {
    const geometry = event.feature.getGeometry()
    // 先摘掉 Draw 再取真值,避免测量态残留阻塞 singleclick
    if (measureInteraction && map) map.removeInteraction(measureInteraction)
    measureInteraction = null
    measureMode.value = 'none'
    if (!geometry) return
    // 只落真值与文本;显示几何由 ol 随后加入 source(即用户实际画出的形状)
    setMeasureDraft(measureGeometryToDraft(geometry as LineString | Polygon, currentCrs.value))
  })
  map.addInteraction(measureInteraction)
}

function clearMeasure() {
  measureSource.clear()
  setMeasureDraft(null)
  if (measureInteraction && map) map.removeInteraction(measureInteraction)
  measureInteraction = null
  measureMode.value = 'none'
}

/**
 * 投影切换后的测量生命周期(与 reloadAisGeometry / reloadRouteGeometry 同范式)。
 *
 * 绘制进行中:结束 Draw 并提示重新测量 —— 绝不把旧 CRS 的草图坐标当作新 CRS
 * 几何参与计算。
 * 已完成:保留 WGS84 真值,按新投影重建显示几何,结果由同一组地理点重新生成,
 * 因此数值不随投影变化,同时不会留下「位置错误却看似有效」的旧图形。
 */
function syncMeasureForProjection() {
  if (measureMode.value !== 'none') {
    stopMeasureInteraction()
    measureSource.clear()
    setMeasureDraft(null)
    measureText.value = '投影已切换，请重新测量'
    ElMessage.warning('投影已切换，测量已取消，请重新测量')
    return
  }
  if (!measureDraft.value) return
  rebuildMeasureGeometry()
  setMeasureDraft(measureDraft.value)
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
  else if (command === 'ice') icePanelOpen.value = !icePanelOpen.value
  else if (command === 'environment') environmentPanelOpen.value = !environmentPanelOpen.value
  else if (command === 'bathymetry' || command === 'wind' || command === 'current' || command === 'wave') {
    environmentPanelOpen.value = true
    environmentOverlays.toggle(command)
  } else if (command === 'risk') {
    ElMessage.info('风险栅格需先完成一次规划或区域风险评估')
  }
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
    routesStore.ensureLoaded(config.value.project.id)
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
    routeDrawing.syncRoutesToMap()
    // 冰情:数据加载失败只降级为"无可用冰情数据",绝不影响地图
    void iceOverlay.loadInfo()
    startPerfPoll()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '项目地图加载失败'))
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  closeRouteFlyout()
  hideHover()
  hoverViewport?.removeEventListener('pointerleave', hideHover)
  hoverViewport?.removeEventListener('pointerleave', iceOverlay.clearHover)
  hoverViewport = null
  routeDrawing.dispose()
  iceOverlay.dispose()
  environmentOverlays.dispose()
  stopPerfPoll()
  bulkAbortController?.abort()
  for (const runtime of runtimeLayers.value) detachWmsLayer(runtime)
  tileRequestQueue.reset()
  tileCache.clear()
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
                  <small>{{ dataset.config.code }} · {{ dataset.config.memberLayerCount }} 个图层<span v-if="dataset.loaded"> · 已加载 {{ dataset.layers.filter(l => selectedLayerIds.has(l.config.id)).length }} 个</span></small>
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
      <!-- 冰情信息(独立环境叠加层,不进入海图图层体系) -->
      <IceLayerPanel v-if="icePanelOpen" :ice="iceOverlay" />
      <EnvironmentLayerPanel v-if="environmentPanelOpen" :env="environmentOverlays" />
      <div class="layer-panel-footer">
        <el-dropdown trigger="click" placement="top-start" @command="handleOverlayCommand">
          <button class="overlay-menu-trigger" type="button" aria-label="环境叠加">
            <el-icon><Operation /></el-icon><span>环境叠加</span><span class="overlay-menu-count">7</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu class="overlay-menu">
              <el-dropdown-item command="ais">
                <span class="demo-badge">演示</span><span>AIS 船位</span><span class="overlay-state">{{ aisVisible ? '已开启' : '未开启' }}</span>
              </el-dropdown-item>
              <el-dropdown-item command="ice">
                <span>冰情信息</span><span class="overlay-state">{{ iceOverlayState }}</span>
              </el-dropdown-item>
              <el-dropdown-item command="environment" divided>
                <span>环境图层</span><span class="overlay-state">{{ environmentPanelOpen ? '已展开' : '未展开' }}</span>
              </el-dropdown-item>
              <el-dropdown-item command="bathymetry">
                <span>水深</span><span class="overlay-state">{{ environmentOverlays.layers.bathymetry.visible ? '已开启' : '未开启' }}</span>
              </el-dropdown-item>
              <el-dropdown-item command="wind">
                <span>风场</span><span class="overlay-state">{{ environmentOverlays.layers.wind.visible ? '已开启' : '未开启' }}</span>
              </el-dropdown-item>
              <el-dropdown-item command="current">
                <span>海流</span><span class="overlay-state">{{ environmentOverlays.layers.current.visible ? '已开启' : '未开启' }}</span>
              </el-dropdown-item>
              <el-dropdown-item command="wave">
                <span>海浪</span><span class="overlay-state">{{ environmentOverlays.layers.wave.visible ? '已开启' : '未开启' }}</span>
              </el-dropdown-item>
              <el-dropdown-item command="risk" disabled>
                <span>风险评估</span><span class="overlay-state">需规划结果</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </aside>
    <div ref="mapTarget" class="map-canvas"></div>
    <!-- 地图内浮层容器:与 .map-canvas 同级同框(不放进 OpenLayers 的 target),
         容器本身 pointer-events:none,不吞地图指针事件;只有浮窗面板可交互 -->
    <div class="map-overlay-root">
      <div
        v-if="hover"
        class="map-hover-coord"
        :class="{ 'is-flip-x': hover.flipX, 'is-flip-y': hover.flipY }"
        :style="{ left: `${hover.x}px`, top: `${hover.y}px` }"
      >{{ hover.text }}</div>
      <RouteInfoFlyout
        v-if="routeFlyoutRoute"
        :route="routeFlyoutRoute"
        :pixel="routeFlyoutPixel"
        :segment-index="routeFlyoutSegmentIndex"
        :drawing="routeDrawing"
        @close="closeRouteFlyout"
      />
      <!-- 冰情值浮窗(只读,数据来自后端原始网格查询) -->
      <IceValueTooltip v-if="iceOverlay.hover.value" :hover="iceOverlay.hover.value" />
      <!-- 环境值浮窗(水深/风/流/浪,只读;数据质量随浮窗展示) -->
      <EnvironmentValueTooltip
        v-if="environmentOverlays.tooltip.value"
        :tooltip="environmentOverlays.tooltip.value"
      />
      <!-- 冰情时间轴:底部居中,左右让位随面板折叠状态自适应 -->
      <IceTimeline
        v-if="iceOverlay.timelineVisible.value"
        :dates="iceOverlay.dates.value"
        :current-index="iceOverlay.currentIndex.value"
        :left-offset="iceTimelineLeft"
        :right-offset="iceTimelineRight"
        @step="iceOverlay.stepDate($event)"
        @select="iceOverlay.setDate($event)"
      />
    </div>
    <div class="map-tools glass-panel">
      <el-tooltip content="要素识别" placement="left"><button :class="{ active: queryMode }" @click="toggleQueryMode"><el-icon><Location /></el-icon></button></el-tooltip>
      <el-tooltip content="点位气象演示" placement="left"><button :class="{ active: weatherMode }" @click="toggleWeatherMode"><el-icon><DataAnalysis /></el-icon></button></el-tooltip>
      <el-tooltip content="测量距离" placement="left"><button :class="{ active: measureMode === 'LineString' }" @click="activateMeasure('LineString')"><el-icon><MapLocation /></el-icon></button></el-tooltip>
      <el-tooltip content="测量面积" placement="left"><button :class="{ active: measureMode === 'Polygon' }" @click="activateMeasure('Polygon')"><el-icon><FullScreen /></el-icon></button></el-tooltip>
      <el-tooltip content="航路规划模拟 · 打开面板绘制/管理航路，地图上随时可点选航路查看详情" placement="left"><button :class="{ active: routePanelVisible }" @click="routePanelVisible = !routePanelVisible"><el-icon><Compass /></el-icon></button></el-tooltip>
      <el-tooltip content="地图截图" placement="left"><button @click="captureMap"><el-icon><Camera /></el-icon></button></el-tooltip>
      <el-tooltip content="打印地图" placement="left"><button @click="printMap"><el-icon><Printer /></el-icon></button></el-tooltip>
    </div>
    <div class="map-status">
      <span>{{ coordinateText }}</span><span>{{ currentCrs }}</span>
      <!-- 可发现性:有可见航路即提示点选入口(点选与面板是否打开无关) -->
      <span v-if="routesStore.routes.some((route) => route.visible)" class="route-select-hint">点击地图上的航路可查看详情</span>
      <span v-if="measureText" class="measure-result">{{ measureText }} <button @click="clearMeasure">清除</button></span>
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
    <RoutePlannerPanel v-model:visible="routePanelVisible" :drawing="routeDrawing" />
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
