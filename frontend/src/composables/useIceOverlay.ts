/**
 * 冰情叠加 —— 状态与 OpenLayers 生命周期。
 *
 * 与 S-57 渲染体系彻底解耦:两个独立 TileLayer(密集度/厚度)+ 一个调试
 * VectorLayer,直接挂到既有地图;绝不进入 runtimeLayers / selectedLayerIds /
 * Render Bundle / mapRenderScheduler。
 *
 * 瓦片请求复用通用 TileRequestQueue + LRUTileCache，并由
 * utils/tileLoader.ts 的 per-source TileLoadLifecycle 管理:
 * - 日期/投影/可见性变化只替换**发生变化字段**的 Source；
 * - 取消/源替换使用 TileState.EMPTY，绝不把瓦片留在 LOADING；
 * - 有界重试、超时、Content-Type/解码校验、objectURL revoke、错误诊断；
 * - 快速拖动时间轴有 120ms debounce，避免每个 input 事件触发一次冷加载。
 *
 * hover:100ms debounce + AbortController + 请求代次号,旧响应绝不覆盖新位置;
 * 值与瓦片同源于后端原始网格(绝不从 PNG 颜色反推);
 * 不自行注册 map 事件:由 MapWorkspaceView 唯一的 pointermove 分发进来。
 */
import { computed, ref, shallowRef, watch } from 'vue'
import type OlMap from 'ol/Map'
import GeoJSON from 'ol/format/GeoJSON'
import TileLayer from 'ol/layer/Tile'
import VectorLayer from 'ol/layer/Vector'
import XYZ from 'ol/source/XYZ'
import VectorSource from 'ol/source/Vector'
import { Circle as CircleStyle, Fill, Style, Stroke } from 'ol/style'
import { apiErrorMessage } from '../api/client'
import { fetchIceAlignment, fetchIceInfo, fetchIceValue } from '../api/ice'
import type { IceFieldId, IceInfo } from '../types'
import type { LRUTileCache } from '../utils/tileCache'
import type { TileRequestQueue } from '../utils/tileRequestQueue'
import { tileDiagnostics } from '../utils/tileDiagnostics'
import {
  createQueuedTileLoadFunction,
  createTileLoadLifecycle,
  deactivateTileLoadLifecycle,
  type TileLoadLifecycle,
} from '../utils/tileLoader'
import {
  ICE_ALIGNMENT_Z_INDEX,
  ICE_LAYER_Z_INDEX,
  ICE_MAX_ZOOM,
  buildIceTileUrl,
  createIceTileGrid,
  iceFieldAvailable,
  iceTimelineIndex,
  isIceValueValid,
  projectIceExtent,
  stepIceDate,
} from '../utils/mapIce'

export interface IceOverlayOptions {
  getMap: () => OlMap | null
  getCrs: () => string
  /** 与海图瓦片共享的 LRU 瓦片缓存(开关切换/回pan/重复日期零请求) */
  tileCache: LRUTileCache
  /** 与海图瓦片共享的限流请求队列(冰情使用 high 优先级) */
  tileRequestQueue: TileRequestQueue
  /** 其他地图交互(测量/识别/气象/航路绘制编辑/航路浮窗)进行中 → 暂停冰情 hover */
  canQueryValue: () => boolean
}

export interface IceHoverState {
  x: number
  y: number
  flipX: boolean
  flipY: boolean
  value: number
  units: string
  date: string
  field: string
  longitude: number
  latitude: number
}

interface IcePointerEvent {
  pixel: number[]
  coordinate: number[]
  dragging: boolean
}

interface IceSourceState {
  key: string
  lifecycle: TileLoadLifecycle
  source: XYZ
  field: IceFieldId
}

/** 悬停查询 debounce(毫秒) */
const ICE_HOVER_DEBOUNCE_MS = 100
/** 时间轴快速拖动时合并源替换，避免每个 input 事件触发一次冷加载 */
const ICE_DATE_DEBOUNCE_MS = 120
/** hover 浮窗翻转阈值(与既有坐标提示同一思路,按地图视口尺寸推导) */
const HOVER_FLIP_X_RATIO = 0.62
const HOVER_FLIP_Y_RATIO = 0.6

export function useIceOverlay(options: IceOverlayOptions) {
  const info = shallowRef<IceInfo | null>(null)
  const loading = ref(false)
  /** True once the first /ice/info request has settled (success or failure). */
  const infoLoaded = ref(false)
  const error = ref('')
  const selectedDate = ref<string | null>(null)
  const concentrationVisible = ref(false)
  const thicknessVisible = ref(false)
  const concentrationOpacity = ref(0.72)
  const thicknessOpacity = ref(0.72)
  const hover = ref<IceHoverState | null>(null)
  const debugAlignment = ref(false)
  /** Final tile failures since the last source rebuild (not retries). */
  const tileErrorCount = ref(0)
  const lastTileError = ref('')

  let concentrationLayer: TileLayer<XYZ> | null = null
  let thicknessLayer: TileLayer<XYZ> | null = null
  let alignmentLayer: VectorLayer<VectorSource> | null = null
  let attached = false
  let hoverTimer = 0
  let hoverRequestId = 0
  let hoverController: AbortController | null = null
  let alignmentController: AbortController | null = null
  let alignmentRequestId = 0
  let lastHoverPixel: number[] | null = null
  let refreshTimer = 0
  let infoController: AbortController | null = null
  let infoRequestId = 0
  let generationSeq = 0

  /** Per-field current source lifecycle. */
  const sourceStates: Partial<Record<IceFieldId, IceSourceState>> = {}

  function layerForField(field: IceFieldId): TileLayer<XYZ> | null {
    return field === 'concentration' ? concentrationLayer : thicknessLayer
  }

  function fieldVisible(field: IceFieldId): boolean {
    return field === 'concentration' ? concentrationVisible.value : thicknessVisible.value
  }

  function fieldAvailable(field: IceFieldId): boolean {
    return iceFieldAvailable(info.value, field, selectedDate.value)
  }

  function fieldOpacity(field: IceFieldId): number {
    return field === 'concentration' ? concentrationOpacity.value : thicknessOpacity.value
  }

  function sourceKeyFor(field: IceFieldId, date: string, crs: string, visible: boolean): string {
    return `${field}|${date}|${crs}|${visible ? 'on' : 'off'}`
  }

  function deactivateSource(field: IceFieldId) {
    const state = sourceStates[field]
    if (!state) return
    deactivateTileLoadLifecycle(state.lifecycle)
    delete sourceStates[field]
  }

  function deactivateAllSources() {
    deactivateSource('concentration')
    deactivateSource('thickness')
  }

  /** 当前字段的 XYZ 源；key 不变时复用，绝不 abort 另一字段。 */
  function ensureSource(field: IceFieldId): XYZ | null {
    const date = selectedDate.value
    const visible = fieldVisible(field)
    const available = fieldAvailable(field)
    if (!date || !visible || !available) {
      deactivateSource(field)
      return null
    }
    const crs = options.getCrs()
    const key = sourceKeyFor(field, date, crs, visible)
    const existing = sourceStates[field]
    if (existing && existing.key === key) return existing.source

    deactivateSource(field)
    tileErrorCount.value = 0
    lastTileError.value = ''
    const lifecycle = createTileLoadLifecycle(
      `ice:${field}:${date}:${crs}`,
      ++generationSeq,
    )
    const load = createQueuedTileLoadFunction({
      cache: options.tileCache,
      queue: options.tileRequestQueue,
      lifecycle,
      layer: `ice:${field}`,
      date,
      projection: crs,
      priority: 'high',
      retry: {
        maxAttempts: 4,
        classifyStatus: (status) => (status === 404 || status === 204 ? 'empty' : 'retry'),
      },
      diagnostics: tileDiagnostics,
      onRetry: () => {
        lastTileError.value = `${field} 瓦片重试中`
      },
      onFailure: (caught) => {
        tileErrorCount.value += 1
        lastTileError.value = caught instanceof Error ? caught.message : '冰情瓦片加载失败'
      },
    })
    const source = new XYZ({
      url: buildIceTileUrl(field, crs, date),
      projection: crs,
      tileGrid: createIceTileGrid(crs),
      maxZoom: ICE_MAX_ZOOM,
      crossOrigin: 'anonymous',
      transition: 0,
      tileLoadFunction: load as never,
    })
    sourceStates[field] = { key, lifecycle, source, field }
    return source
  }

  /** 只替换发生变化的 Source 与可见性,绝不重建 Layer(时间轴连切不累积图层)。 */
  function refreshLayers() {
    if (refreshTimer) {
      window.clearTimeout(refreshTimer)
      refreshTimer = 0
    }
    for (const field of ['concentration', 'thickness'] as IceFieldId[]) {
      const layer = layerForField(field)
      if (!layer) continue
      const source = ensureSource(field)
      layer.setSource(source)
      layer.setVisible(Boolean(source))
      layer.setOpacity(fieldOpacity(field))
    }
  }

  function scheduleRefresh() {
    if (refreshTimer) window.clearTimeout(refreshTimer)
    refreshTimer = window.setTimeout(() => {
      refreshTimer = 0
      refreshLayers()
      void loadAlignment()
    }, ICE_DATE_DEBOUNCE_MS)
  }

  const dates = computed(() => info.value?.dates ?? [])
  const currentIndex = computed(() => iceTimelineIndex(dates.value, selectedDate.value))
  const concentrationAvailable = computed(() =>
    iceFieldAvailable(info.value, 'concentration', selectedDate.value),
  )
  const thicknessAvailable = computed(() =>
    iceFieldAvailable(info.value, 'thickness', selectedDate.value),
  )
  /** 时间轴显示条件:任一字段开启且存在实际日期 */
  const timelineVisible = computed(
    () => (concentrationVisible.value || thicknessVisible.value) && dates.value.length > 0,
  )

  // ── 数据加载 ────────────────────────────────────────────────────────

  async function loadInfo() {
    if (loading.value) return
    infoController?.abort()
    const controller = new AbortController()
    infoController = controller
    const requestId = ++infoRequestId
    loading.value = true
    error.value = ''
    try {
      const data = await fetchIceInfo(controller.signal)
      if (controller.signal.aborted || requestId !== infoRequestId) return
      info.value = data
      if (!selectedDate.value || !data.dates.includes(selectedDate.value)) {
        selectedDate.value = data.defaultDate ?? data.dates[0] ?? null
      }
      if (data.dates.length === 0) {
        concentrationVisible.value = false
        thicknessVisible.value = false
      }
    } catch (caught) {
      if (controller.signal.aborted) return
      // 降级原则:冰情失败 != 地图失败；保留上一次可用元数据，避免瞬时失败
      // 把正在工作的图层隐藏。
      error.value = apiErrorMessage(caught, '冰情数据加载失败')
    } finally {
      if (requestId === infoRequestId) {
        loading.value = false
        infoLoaded.value = true
        refreshLayers()
      }
    }
  }

  /** Explicit retry exposed by the panel: metadata first when absent/failed. */
  async function retry() {
    if (!info.value || error.value) {
      await loadInfo()
      return
    }
    retryVisibleLayers()
  }

  // ── 图层生命周期 ────────────────────────────────────────────────────

  function attach() {
    const map = options.getMap()
    if (!map || attached) return
    concentrationLayer = new TileLayer({
      zIndex: ICE_LAYER_Z_INDEX.concentration,
      visible: false,
      opacity: concentrationOpacity.value,
    })
    thicknessLayer = new TileLayer({
      zIndex: ICE_LAYER_Z_INDEX.thickness,
      visible: false,
      opacity: thicknessOpacity.value,
    })
    alignmentLayer = new VectorLayer({
      source: new VectorSource(),
      zIndex: ICE_ALIGNMENT_Z_INDEX,
      visible: false,
      style: new Style({
        image: new CircleStyle({
          radius: 5,
          fill: new Fill({ color: '#ffdf63' }),
          stroke: new Stroke({ color: '#07111d', width: 1.5 }),
        }),
      }),
    })
    map.addLayer(thicknessLayer)
    map.addLayer(concentrationLayer)
    map.addLayer(alignmentLayer)
    attached = true
    refreshLayers()
    if (!infoLoaded.value && !loading.value) void loadInfo()
  }

  function dispose() {
    if (refreshTimer) {
      window.clearTimeout(refreshTimer)
      refreshTimer = 0
    }
    clearHover()
    infoController?.abort()
    infoController = null
    deactivateAllSources()
    alignmentController?.abort()
    alignmentController = null
    const map = options.getMap()
    for (const layer of [concentrationLayer, thicknessLayer, alignmentLayer]) {
      if (!layer) continue
      if (map) map.removeLayer(layer)
      layer.dispose()
    }
    concentrationLayer = null
    thicknessLayer = null
    alignmentLayer = null
    attached = false
  }

  /** 投影切换:保留日期/可见性/透明度,只重建 Source 与 TileGrid。 */
  function reloadForProjection() {
    clearHover()
    deactivateAllSources()
    refreshLayers()
    void loadAlignment()
  }

  /** Rebuild the current visible field sources without touching the map/view. */
  function retryVisibleLayers() {
    tileErrorCount.value = 0
    lastTileError.value = ''
    for (const field of ['concentration', 'thickness'] as IceFieldId[]) {
      deactivateSource(field)
    }
    refreshLayers()
  }

  // ── 日期与开关 ──────────────────────────────────────────────────────

  function setDate(date: string) {
    if (!dates.value.includes(date)) return
    selectedDate.value = date
  }

  function stepDate(delta: number) {
    const next = stepIceDate(dates.value, selectedDate.value, delta)
    if (next) setDate(next)
  }

  function toggleConcentration(next?: boolean) {
    const target = next ?? !concentrationVisible.value
    if (target && !concentrationAvailable.value) return
    concentrationVisible.value = target
    if (!target) clearHover()
    refreshLayers()
  }

  function toggleThickness(next?: boolean) {
    const target = next ?? !thicknessVisible.value
    if (target && !thicknessAvailable.value) return
    thicknessVisible.value = target
    refreshLayers()
  }

  function setConcentrationOpacity(value: number) {
    concentrationOpacity.value = Math.min(Math.max(value, 0), 1)
    concentrationLayer?.setOpacity(concentrationOpacity.value)
  }

  function setThicknessOpacity(value: number) {
    thicknessOpacity.value = Math.min(Math.max(value, 0), 1)
    thicknessLayer?.setOpacity(thicknessOpacity.value)
  }

  watch(selectedDate, () => {
    clearHover()
    // Abort the previous date's in-flight tile requests immediately. The old
    // source stays attached for the 120 ms debounce window (already-loaded
    // tiles remain visible), then is replaced by the new date source.
    deactivateSource('concentration')
    deactivateSource('thickness')
    scheduleRefresh()
  })

  // ── 定位与调试对齐 ──────────────────────────────────────────────────

  function fitIceExtent() {
    const map = options.getMap()
    const extent = projectIceExtent(info.value?.extent ?? null, options.getCrs())
    if (!map || !extent) return
    map.getView().fit(extent, { padding: [60, 80, 80, 60], maxZoom: 4, duration: 400 })
  }

  async function loadAlignment() {
    const layer = alignmentLayer
    if (!layer) return
    if (!debugAlignment.value || !selectedDate.value) {
      layer.getSource()?.clear()
      layer.setVisible(false)
      return
    }
    const requestId = ++alignmentRequestId
    alignmentController?.abort()
    const controller = new AbortController()
    alignmentController = controller
    try {
      const geojson = await fetchIceAlignment(
        { date: selectedDate.value, projection: options.getCrs() },
        controller.signal,
      )
      if (controller.signal.aborted || requestId !== alignmentRequestId) return
      const crs = options.getCrs()
      const features = new GeoJSON().readFeatures(geojson, {
        dataProjection: crs,
        featureProjection: crs,
      })
      layer.getSource()?.clear()
      layer.getSource()?.addFeatures(features)
      layer.setVisible(true)
    } catch {
      if (controller.signal.aborted || requestId !== alignmentRequestId) return
      layer.getSource()?.clear()
      layer.setVisible(false)
    }
  }

  function setDebugAlignment(value: boolean) {
    debugAlignment.value = value
    void loadAlignment()
  }

  // ── hover(原始值查询,绝不从瓦片颜色反推) ───────────────────────────

  function buildHoverPosition(pixel: number[]): Pick<IceHoverState, 'x' | 'y' | 'flipX' | 'flipY'> {
    const size = options.getMap()?.getSize() ?? [0, 0]
    return {
      x: pixel[0] ?? 0,
      y: pixel[1] ?? 0,
      flipX: (pixel[0] ?? 0) > size[0] * HOVER_FLIP_X_RATIO,
      flipY: (pixel[1] ?? 0) > size[1] * HOVER_FLIP_Y_RATIO,
    }
  }

  /** 指针是否落在冰情数据范围内(近似预筛,范围外不发请求)。 */
  function pointerInIceExtent(coordinate: number[]): boolean {
    const extent = projectIceExtent(info.value?.extent ?? null, options.getCrs())
    if (!extent) return false
    const [x, y] = coordinate
    return x >= extent[0] && y >= extent[1] && x <= extent[2] && y <= extent[3]
  }

  function clearHover() {
    hoverRequestId += 1
    if (hoverTimer) {
      window.clearTimeout(hoverTimer)
      hoverTimer = 0
    }
    hoverController?.abort()
    hoverController = null
    lastHoverPixel = null
    hover.value = null
  }

  function activeHoverField(): IceFieldId | null {
    if (concentrationVisible.value && concentrationAvailable.value) return 'concentration'
    if (thicknessVisible.value && thicknessAvailable.value) return 'thickness'
    return null
  }

  function handlePointerMove(event: IcePointerEvent) {
    const field = activeHoverField()
    if (
      event.dragging ||
      !field ||
      !selectedDate.value ||
      !options.canQueryValue() ||
      !pointerInIceExtent(event.coordinate)
    ) {
      clearHover()
      return
    }
    const pixel = [...event.pixel]
    const coordinate = [...event.coordinate]
    lastHoverPixel = pixel
    if (hover.value) {
      // 位置立即跟随指针,数值经 debounce + 代次校验后更新
      hover.value = { ...hover.value, ...buildHoverPosition(pixel) }
    }
    if (hoverTimer) window.clearTimeout(hoverTimer)
    const requestId = ++hoverRequestId
    hoverTimer = window.setTimeout(() => {
      hoverTimer = 0
      void queryValue(coordinate, requestId, field)
    }, ICE_HOVER_DEBOUNCE_MS)
  }

  async function queryValue(coordinate: number[], requestId: number, field: IceFieldId) {
    const date = selectedDate.value
    if (!date) return
    hoverController?.abort()
    hoverController = new AbortController()
    try {
      const result = await fetchIceValue(
        {
          date,
          x: coordinate[0] ?? 0,
          y: coordinate[1] ?? 0,
          projection: options.getCrs(),
          field,
        },
        hoverController.signal,
      )
      if (requestId !== hoverRequestId) return // 旧响应绝不覆盖新位置
      if (!isIceValueValid(result.value) || !lastHoverPixel) {
        hover.value = null // NoData → 冰情浮窗不显示,经纬度提示回退生效
        return
      }
      hover.value = {
        ...buildHoverPosition(lastHoverPixel),
        value: result.value,
        units: result.units ?? '%',
        date: result.date ?? date,
        field: result.field ?? field,
        longitude: result.longitude ?? Number.NaN,
        latitude: result.latitude ?? Number.NaN,
      }
    } catch {
      if (requestId === hoverRequestId) hover.value = null
    }
  }

  return {
    info,
    loading,
    infoLoaded,
    error,
    selectedDate,
    dates,
    currentIndex,
    concentrationVisible,
    thicknessVisible,
    concentrationOpacity,
    thicknessOpacity,
    concentrationAvailable,
    thicknessAvailable,
    tileErrorCount,
    lastTileError,
    hover,
    debugAlignment,
    timelineVisible,
    loadInfo,
    retry,
    attach,
    dispose,
    setDate,
    stepDate,
    toggleConcentration,
    toggleThickness,
    setConcentrationOpacity,
    setThicknessOpacity,
    refreshLayers,
    reloadForProjection,
    retryVisibleLayers,
    fitIceExtent,
    loadAlignment,
    setDebugAlignment,
    clearHover,
    handlePointerMove,
  }
}

export type IceOverlayApi = ReturnType<typeof useIceOverlay>
