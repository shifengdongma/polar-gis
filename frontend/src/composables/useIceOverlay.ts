/**
 * 冰情叠加 —— 状态与 OpenLayers 生命周期。
 *
 * 与 S-57 渲染体系彻底解耦:两个独立 TileLayer(密集度/厚度)+ 一个调试
 * VectorLayer,直接挂到既有地图;绝不进入 runtimeLayers / selectedLayerIds /
 * Render Bundle / mapRenderScheduler / TileRequestQueue —— 冰情 XYZ 由
 * OpenLayers 自行管理请求。
 *
 * 硬性约束:
 * - attach() 幂等;dispose() 必须彻底(removeLayer + dispose + 中止在飞请求);
 * - 日期/可用性/投影变化一律只替换 XYZ Source(setSource),绝不重建 Layer
 *   (连续切换日期后地图上永远只有 1 个密集度 + 1 个厚度 TileLayer);
 * - 瓦片 URL 携带日期;transition:0(时间轴切换无淡入残影);
 *   crossOrigin:'anonymous'(截图 canvas 合成需要);
 * - hover:100ms debounce + AbortController + 请求代次号,旧响应绝不覆盖新位置;
 *   值与瓦片同源于后端原始网格(绝不从 PNG 颜色反推);
 * - 不自行注册 map 事件:由 MapWorkspaceView 唯一的 pointermove 分发进来。
 */
import { computed, ref, shallowRef, watch } from 'vue'
import type OlMap from 'ol/Map'
import GeoJSON from 'ol/format/GeoJSON'
import TileLayer from 'ol/layer/Tile'
import VectorLayer from 'ol/layer/Vector'
import XYZ from 'ol/source/XYZ'
import VectorSource from 'ol/source/Vector'
import { Circle as CircleStyle, Fill, Style, Stroke } from 'ol/style'
import TileState from 'ol/TileState'
import { apiErrorMessage } from '../api/client'
import { fetchIceAlignment, fetchIceInfo, fetchIceValue } from '../api/ice'
import type { IceFieldId, IceInfo } from '../types'
import { TILE_RETRY_BASE_DELAY_MS, TILE_RETRY_MAX_ATTEMPTS } from '../utils/mapLayerBatch'
import type { LRUTileCache } from '../utils/tileCache'
import type { TileRequestQueue } from '../utils/tileRequestQueue'
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
  /** 与海图瓦片共享的限流请求队列(全局限并发,丢弃即中止) */
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

/** 悬停查询 debounce(毫秒) */
const ICE_HOVER_DEBOUNCE_MS = 100
/** hover 浮窗翻转阈值(与既有坐标提示同一思路,按地图视口尺寸推导) */
const HOVER_FLIP_X_RATIO = 0.62
const HOVER_FLIP_Y_RATIO = 0.6

export function useIceOverlay(options: IceOverlayOptions) {
  const info = shallowRef<IceInfo | null>(null)
  const loading = ref(false)
  const error = ref('')
  const selectedDate = ref<string | null>(null)
  const concentrationVisible = ref(false)
  const thicknessVisible = ref(false)
  const concentrationOpacity = ref(0.72)
  const thicknessOpacity = ref(0.72)
  const hover = ref<IceHoverState | null>(null)
  const debugAlignment = ref(false)

  let concentrationLayer: TileLayer<XYZ> | null = null
  let thicknessLayer: TileLayer<XYZ> | null = null
  let alignmentLayer: VectorLayer<VectorSource> | null = null
  let attached = false
  let hoverTimer = 0
  let hoverRequestId = 0
  let hoverController: AbortController | null = null
  let alignmentController: AbortController | null = null
  let lastHoverPixel: number[] | null = null

  // ── 瓦片请求管线(限流队列 + 共享 LRU 缓存 + 代次中止) ──────────────
  // 会话 #26.1:此前用 OL 默认 <img> 加载器 —— 无并发上限、丢弃不中止,
  // 打开"海冰密集度"时视口瓦片同时发射、时间轴切换后旧请求仍占用连接与
  // 后端线程(实测后端惊群每张 6.6s),表现为请求堆积、地图空白与
  // "日期切换无法重新加载"。现复用海图同款做法并加代次中止。
  let tileGeneration = 0
  const tileControllers = new Set<AbortController>()

  /** 使上一代瓦片请求全部失效并中止(日期/投影/开关切换前调用)。 */
  function abortStaleTileLoads() {
    tileGeneration += 1
    for (const controller of tileControllers) controller.abort()
    tileControllers.clear()
  }

  /**
   * 冰情瓦片加载器 —— 复用 S-57 已验证的做法(参照 MapWorkspaceView 的
   * createRetryTileLoadFunction):共享 LRU 缓存 → 全局限流队列 fetch → blob;
   * 瓦片被 OpenLayers 释放时(ol10 中 release()/dispose() 置 TileState.EMPTY)
   * 或所属代次过期 → 立即中止在飞请求;可恢复错误指数退避重试。
   */
  function createIceTileLoadFunction(
    tileCache: LRUTileCache,
    tileRequestQueue: TileRequestQueue,
  ): (tile: any, src: string) => void {
    return (tile, src) => {
      const generation = tileGeneration
      const image = tile.getImage() as HTMLImageElement
      const controller = new AbortController()
      tileControllers.add(controller)
      const release = () => tileControllers.delete(controller)
      let attempts = 0

      const isAborted = () => controller.signal.aborted || generation !== tileGeneration

      // 瓦片被 OL 释放/销毁(平移缩放、投影切换、渲染缓存过期)→ 中止在飞请求
      tile.addEventListener('change', () => {
        if ((tile as any).getState?.() === TileState.EMPTY) {
          controller.abort()
        }
      })

      const tryLoad = () => {
        if (isAborted()) {
          release()
          return
        }
        attempts++
        // 1. LRU 缓存优先(开关切换、回 pan、重复日期零网络请求)
        const cached = tileCache.get(src)
        if (cached) {
          release()
          const objectUrl = URL.createObjectURL(cached)
          image.onload = () => URL.revokeObjectURL(objectUrl)
          image.src = objectUrl
          return
        }
        // 2. 走全局限流队列(与海图瓦片共享并发上限,防止请求堆积)
        tileRequestQueue.fetch(src, controller.signal)
          .then((response) => {
            if (response.ok) return response.blob()
            // 可恢复错误(429/502/503/504)指数退避重试;其余标记错误
            if (
              [429, 502, 503, 504].includes(response.status) &&
              attempts < TILE_RETRY_MAX_ATTEMPTS
            ) {
              window.setTimeout(tryLoad, TILE_RETRY_BASE_DELAY_MS * Math.pow(2, attempts - 1))
              return null
            }
            release()
            tile.setState(TileState.ERROR)
            return null
          })
          .then((blob) => {
            if (!blob || isAborted()) {
              release()
              return
            }
            tileCache.set(src, blob)
            release()
            const objectUrl = URL.createObjectURL(blob)
            image.onload = () => URL.revokeObjectURL(objectUrl)
            image.src = objectUrl
          })
          .catch((error) => {
            if (isAborted()) {
              release()
              return
            }
            if (error instanceof TypeError && attempts < TILE_RETRY_MAX_ATTEMPTS) {
              window.setTimeout(tryLoad, TILE_RETRY_BASE_DELAY_MS * Math.pow(2, attempts - 1))
            } else {
              release()
              tile.setState(TileState.ERROR)
            }
          })
      }
      tryLoad()
    }
  }

  const loadIceTile = createIceTileLoadFunction(options.tileCache, options.tileRequestQueue)

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
    loading.value = true
    error.value = ''
    try {
      const data = await fetchIceInfo()
      info.value = data
      if (!selectedDate.value || !data.dates.includes(selectedDate.value)) {
        selectedDate.value = data.defaultDate ?? data.dates[0] ?? null
      }
      if (data.dates.length === 0) {
        concentrationVisible.value = false
        thicknessVisible.value = false
      }
    } catch (caught) {
      // 降级原则:冰情失败 != 地图失败
      info.value = null
      error.value = apiErrorMessage(caught, '冰情数据加载失败')
    } finally {
      loading.value = false
      refreshLayers()
    }
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
  }

  function dispose() {
    clearHover()
    abortStaleTileLoads()
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

  /** 当前字段的 XYZ 源(日期/投影/可用性任一变化都会生成新源)。 */
  function tileSourceFor(field: IceFieldId): XYZ | null {
    const date = selectedDate.value
    if (!date || !iceFieldAvailable(info.value, field, date)) return null
    const crs = options.getCrs()
    return new XYZ({
      url: buildIceTileUrl(field, crs, date),
      projection: crs,
      tileGrid: createIceTileGrid(crs),
      maxZoom: ICE_MAX_ZOOM,
      crossOrigin: 'anonymous',
      transition: 0,
      // 复用海图同款瓦片请求管线:限流队列 + 共享 LRU 缓存 + 丢弃即中止
      tileLoadFunction: loadIceTile,
    })
  }

  /** 只替换 Source 与可见性,绝不重建 Layer(时间轴连切不累积图层)。 */
  function refreshLayers() {
    // 先使上一代瓦片请求全部失效并中止:日期/投影/开关切换后,旧请求
    // 立即让出队列名额与后端线程,新瓦片可即时进入加载(修复切换堆积)
    abortStaleTileLoads()
    if (concentrationLayer) {
      const usable = concentrationVisible.value && concentrationAvailable.value
      concentrationLayer.setSource(usable ? tileSourceFor('concentration') : null)
      concentrationLayer.setVisible(usable)
      concentrationLayer.setOpacity(concentrationOpacity.value)
    }
    if (thicknessLayer) {
      const usable = thicknessVisible.value && thicknessAvailable.value
      thicknessLayer.setSource(usable ? tileSourceFor('thickness') : null)
      thicknessLayer.setVisible(usable)
      thicknessLayer.setOpacity(thicknessOpacity.value)
    }
  }

  /** 投影切换:保留日期/可见性/透明度,只重建 Source 与 TileGrid。 */
  function reloadForProjection() {
    clearHover()
    refreshLayers()
    void loadAlignment()
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
    refreshLayers()
    void loadAlignment()
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
    alignmentController?.abort()
    alignmentController = new AbortController()
    try {
      const geojson = await fetchIceAlignment(
        { date: selectedDate.value, projection: options.getCrs() },
        alignmentController.signal,
      )
      const crs = options.getCrs()
      const features = new GeoJSON().readFeatures(geojson, {
        dataProjection: crs,
        featureProjection: crs,
      })
      layer.getSource()?.clear()
      layer.getSource()?.addFeatures(features)
      layer.setVisible(true)
    } catch {
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

  function handlePointerMove(event: IcePointerEvent) {
    if (
      event.dragging ||
      !concentrationVisible.value ||
      !concentrationAvailable.value ||
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
      void queryValue(coordinate, requestId)
    }, ICE_HOVER_DEBOUNCE_MS)
  }

  async function queryValue(coordinate: number[], requestId: number) {
    const date = selectedDate.value
    if (!date) return
    hoverController?.abort()
    hoverController = new AbortController()
    try {
      const result = await fetchIceValue(
        { date, x: coordinate[0] ?? 0, y: coordinate[1] ?? 0, projection: options.getCrs() },
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
        field: result.field ?? 'concentration',
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
    hover,
    debugAlignment,
    timelineVisible,
    loadInfo,
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
    fitIceExtent,
    loadAlignment,
    setDebugAlignment,
    clearHover,
    handlePointerMove,
  }
}

export type IceOverlayApi = ReturnType<typeof useIceOverlay>
