/**
 * S-57 waterway thematic state, API and independent map overlay.
 *
 * - Uses the project-scoped waterway API; never queries one HTTP request per
 *   chart layer from the browser.
 * - The overlay is a separate VectorLayer (z=78), never enters runtimeLayers /
 *   selectedLayerIds / render bundles / route stores.
 * - Picking is invoked by the view's single `singleclick` handler only while
 *   the thematic panel and "地图点选" mode are active.
 */
import { computed, ref, shallowRef } from 'vue'
import type OlMap from 'ol/Map'
import Feature from 'ol/Feature'
import VectorLayer from 'ol/layer/Vector'
import VectorSource from 'ol/source/Vector'
import type Geometry from 'ol/geom/Geometry'
import type Style from 'ol/style/Style'
import { apiErrorMessage } from '../api/client'
import {
  fetchWaterwayCatalog,
  fetchWaterwayDetail,
  searchWaterways,
} from '../api/s57Waterways'
import type {
  S57WaterwayCatalog,
  S57WaterwayDetail,
  S57WaterwaySearchItem,
  S57WaterwaySearchRequest,
} from '../types/s57Waterways'
import {
  WATERWAY_OVERLAY_Z_INDEX,
  waterwayExtent,
  waterwayFeatureFromItem,
  waterwayStyleForFeature,
} from '../utils/mapS57Waterway'

export interface S57WaterwaysOptions {
  getProjectId: () => string
  getMap: () => OlMap | null
  getCrs: () => string
  getViewportBbox?: () => [number, number, number, number] | null
  getFitPadding?: () => [number, number, number, number]
}

const PAGE_SIZE = 20

export function useS57Waterways(options: S57WaterwaysOptions) {
  const catalog = shallowRef<S57WaterwayCatalog | null>(null)
  const catalogLoading = ref(false)
  const catalogError = ref('')

  const results = shallowRef<S57WaterwaySearchItem[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(PAGE_SIZE)
  const keyword = ref('')
  const selectedClasses = ref<Set<string>>(new Set())
  const includeAuxiliary = ref(false)
  const viewportOnly = ref(false)
  const searching = ref(false)
  const searchError = ref('')
  const warnings = shallowRef<string[]>([])

  const detail = shallowRef<S57WaterwayDetail | null>(null)
  const detailLoading = ref(false)
  const detailError = ref('')
  const selectionMode = ref(false)
  const selectedId = ref<string | null>(null)
  const displayed = shallowRef<Map<string, S57WaterwaySearchItem>>(new Map())

  let layer: VectorLayer<VectorSource> | null = null
  let source: VectorSource | null = null
  let attached = false
  let catalogController: AbortController | null = null
  let searchController: AbortController | null = null
  let detailController: AbortController | null = null
  let searchGeneration = 0
  const styleCache = new Map<string, Style>()

  const hasWaterwayData = computed(() =>
    Boolean(catalog.value?.classes.some((item) => item.layerCount > 0)),
  )
  const availableClassCount = computed(
    () => catalog.value?.classes.filter((item) => item.layerCount > 0).length ?? 0,
  )
  const canSearch = computed(() => selectedClasses.value.size > 0 && !searching.value)
  const pageCount = computed(() =>
    Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))),
  )
  const displayedCount = computed(() => displayed.value.size)

  function defaultSelectedClasses(data: S57WaterwayCatalog): Set<string> {
    return new Set(
      data.classes
        .filter((item) => !item.auxiliary && item.defaultSelected && item.layerCount > 0)
        .map((item) => item.code),
    )
  }

  async function loadCatalog() {
    if (catalogLoading.value) return
    catalogController?.abort()
    catalogController = new AbortController()
    catalogLoading.value = true
    catalogError.value = ''
    try {
      const data = await fetchWaterwayCatalog(
        options.getProjectId(),
        catalogController.signal,
      )
      catalog.value = data
      if (selectedClasses.value.size === 0) {
        selectedClasses.value = defaultSelectedClasses(data)
      }
    } catch (caught) {
      if (!catalogController.signal.aborted) {
        catalogError.value = apiErrorMessage(caught, '航道专题目录加载失败')
      }
    } finally {
      catalogLoading.value = false
    }
  }

  function toggleClass(code: string, checked: boolean) {
    const next = new Set(selectedClasses.value)
    if (checked) next.add(code)
    else next.delete(code)
    selectedClasses.value = next
    const rule = catalog.value?.classes.find((item) => item.code === code)
    if (rule?.auxiliary && checked) includeAuxiliary.value = true
  }

  function setClasses(codes: string[]) {
    selectedClasses.value = new Set(codes)
    const auxiliary = catalog.value?.classes.some(
      (item) => item.auxiliary && codes.includes(item.code),
    )
    includeAuxiliary.value = Boolean(auxiliary)
  }

  function setIncludeAuxiliary(value: boolean) {
    includeAuxiliary.value = value
    if (!value) {
      const auxiliaryCodes = new Set(
        catalog.value?.classes.filter((item) => item.auxiliary).map((item) => item.code) ?? [],
      )
      selectedClasses.value = new Set(
        [...selectedClasses.value].filter((code) => !auxiliaryCodes.has(code)),
      )
    }
  }

  async function runSearch(targetPage = 1) {
    if (selectedClasses.value.size === 0) {
      searchError.value = '请至少选择一个航道对象类别'
      return
    }
    const bbox = viewportOnly.value ? options.getViewportBbox?.() ?? null : null
    if (viewportOnly.value && !bbox) {
      searchError.value = '当前视口暂不可用，请关闭“当前视口”后搜索'
      return
    }
    searchController?.abort()
    searchController = new AbortController()
    const generation = ++searchGeneration
    searching.value = true
    searchError.value = ''
    const payload: S57WaterwaySearchRequest = {
      keyword: keyword.value.trim() || null,
      objectClasses: [...selectedClasses.value],
      includeAuxiliary: includeAuxiliary.value,
      bbox,
      page: targetPage,
      pageSize: pageSize.value,
    }
    try {
      const response = await searchWaterways(
        options.getProjectId(),
        payload,
        searchController.signal,
      )
      if (generation !== searchGeneration) return
      results.value = response.items
      total.value = response.total
      page.value = response.page
      warnings.value = response.warnings
    } catch (caught) {
      if (generation !== searchGeneration) return
      if (!searchController.signal.aborted) {
        searchError.value = apiErrorMessage(caught, '航道专题查询失败')
      }
    } finally {
      if (generation === searchGeneration) searching.value = false
    }
  }

  function setPage(nextPage: number) {
    if (nextPage < 1 || nextPage === page.value || searching.value) return
    void runSearch(nextPage)
  }

  function clearFilters() {
    keyword.value = ''
    viewportOnly.value = false
    includeAuxiliary.value = false
    selectedClasses.value = catalog.value ? defaultSelectedClasses(catalog.value) : new Set()
    results.value = []
    total.value = 0
    page.value = 1
    warnings.value = []
    searchError.value = ''
  }

  function rebuildSource() {
    if (!source || !layer) return
    source.clear()
    const crs = options.getCrs()
    for (const item of displayed.value.values()) {
      const feature = waterwayFeatureFromItem(item, crs)
      if (feature) source.addFeature(feature)
    }
    layer.setVisible(source.getFeatures().length > 0)
    layer.changed()
  }

  function isItemShown(id: string): boolean {
    return displayed.value.has(id)
  }

  function showItem(item: S57WaterwaySearchItem, show = true): boolean {
    if (show && !item.geometry) return false
    const next = new Map(displayed.value)
    if (show) next.set(item.id, item)
    else next.delete(item.id)
    displayed.value = next
    if (!show && selectedId.value === item.id) selectedId.value = null
    rebuildSource()
    return true
  }

  function clearDisplay() {
    displayed.value = new Map()
    selectedId.value = null
    detail.value = null
    rebuildSource()
  }

  function selectFeature(id: string | null) {
    selectedId.value = id
    layer?.changed()
  }

  function locate(item: S57WaterwaySearchItem): boolean {
    const map = options.getMap()
    if (!map || !item.geometry) return false
    if (!isItemShown(item.id)) showItem(item, true)
    const extent = waterwayExtent(item, options.getCrs())
    if (!extent) return false
    selectFeature(item.id)
    map.getView().fit(extent, {
      padding: options.getFitPadding?.() ?? [90, 90, 90, 420],
      maxZoom: 11,
      duration: 450,
    })
    return true
  }

  function pickAtPixel(pixel: number[]): boolean {
    const map = options.getMap()
    if (!map || !layer || !selectionMode.value) return false
    const picked: Feature<Geometry>[] = []
    map.forEachFeatureAtPixel(
      pixel,
      (feature) => {
        picked.push(feature as Feature<Geometry>)
        return true
      },
      {
        hitTolerance: 6,
        layerFilter: (candidate) => candidate === layer,
      },
    )
    const id = picked[0]?.get('waterwayId') as string | undefined
    if (!id) return false
    selectFeature(id)
    void openDetail(id)
    return true
  }

  async function openDetail(id: string) {
    detailController?.abort()
    detailController = new AbortController()
    detailLoading.value = true
    detailError.value = ''
    try {
      const response = await fetchWaterwayDetail(
        options.getProjectId(),
        id,
        detailController.signal,
      )
      detail.value = response
    } catch (caught) {
      if (!detailController.signal.aborted) {
        detailError.value = apiErrorMessage(caught, '航道要素详情加载失败')
      }
    } finally {
      detailLoading.value = false
    }
  }

  function closeDetail() {
    detailController?.abort()
    detailController = null
    detail.value = null
    detailError.value = ''
  }

  function setSelectionMode(value: boolean) {
    selectionMode.value = value
  }

  function attach() {
    const map = options.getMap()
    if (!map || attached) return
    source = new VectorSource()
    layer = new VectorLayer({
      source,
      zIndex: WATERWAY_OVERLAY_Z_INDEX,
      visible: false,
      style: (feature) =>
        waterwayStyleForFeature(
          feature as Feature<Geometry>,
          (feature.get('waterwayId') as string | undefined) === selectedId.value,
          styleCache,
        ),
    })
    map.addLayer(layer)
    attached = true
  }

  function reloadForProjection() {
    rebuildSource()
  }

  function deactivate() {
    selectionMode.value = false
    closeDetail()
    displayed.value = new Map()
    selectedId.value = null
    rebuildSource()
  }

  function dispose() {
    catalogController?.abort()
    searchController?.abort()
    detailController?.abort()
    catalogController = null
    searchController = null
    detailController = null
    const map = options.getMap()
    if (layer) {
      if (map) map.removeLayer(layer)
      layer.dispose()
    }
    layer = null
    source = null
    attached = false
    selectionMode.value = false
    displayed.value = new Map()
    selectedId.value = null
    detail.value = null
    styleCache.clear()
  }

  return {
    catalog,
    catalogLoading,
    catalogError,
    results,
    total,
    page,
    pageSize,
    keyword,
    selectedClasses,
    includeAuxiliary,
    viewportOnly,
    searching,
    searchError,
    warnings,
    detail,
    detailLoading,
    detailError,
    selectionMode,
    selectedId,
    displayed,
    hasWaterwayData,
    availableClassCount,
    canSearch,
    pageCount,
    displayedCount,
    loadCatalog,
    toggleClass,
    setClasses,
    setIncludeAuxiliary,
    runSearch,
    setPage,
    clearFilters,
    showItem,
    isItemShown,
    clearDisplay,
    selectFeature,
    locate,
    pickAtPixel,
    openDetail,
    closeDetail,
    setSelectionMode,
    attach,
    reloadForProjection,
    deactivate,
    dispose,
  }
}

export type S57WaterwaysApi = ReturnType<typeof useS57Waterways>
