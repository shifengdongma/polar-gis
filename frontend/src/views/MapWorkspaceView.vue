<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  Camera,
  CaretBottom,
  CaretRight,
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
import WeatherChart from '../components/WeatherChart.vue'
import { useProjectsStore } from '../stores/projects'
import type { BaseMapRecord, LayerRecord, MapConfig, MapDatasetConfig, MapLayerConfig } from '../types'
import { parseWgs84Extent } from '../utils/mapExtent'
import { s57LayerTitle } from '../utils/s57ObjectNames'

interface RuntimeLayer {
  config: MapLayerConfig
  visible: boolean
  opacity: number
  loadState: 'idle' | 'loading' | 'loaded' | 'error'
  pendingTiles: number
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
const identifyVisible = ref(false)
const identifyItems = ref<Record<string, unknown>[]>([])
const metadataVisible = ref(false)
const metadataLayer = ref<LayerRecord | null>(null)
const legendUrl = ref('')

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

const filteredGroups = computed(() => {
  const keyword = layerSearch.value.trim().toLocaleLowerCase()
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
    if (runtime.visible) attachWmsLayer(runtime)
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
}

function attachWmsLayer(runtime: RuntimeLayer) {
  if (!map || wmsLayers.has(runtime.config.id)) return
  const source = new TileWMS({
    url: browserGeoServerUrl(runtime.config.serviceUrl),
    params: { LAYERS: runtime.config.serviceLayerName, TILED: true, STYLES: runtime.config.styleName || '' },
    crossOrigin: 'anonymous',
  })
  source.on('tileloadstart', () => {
    if (runtime.pendingTiles === 0) runtime.loadState = 'loading'
    runtime.pendingTiles += 1
  })
  source.on('tileloadend', () => {
    runtime.pendingTiles = Math.max(0, runtime.pendingTiles - 1)
    if (runtime.pendingTiles === 0 && runtime.loadState !== 'error') runtime.loadState = 'loaded'
  })
  source.on('tileloaderror', () => {
    runtime.pendingTiles = Math.max(0, runtime.pendingTiles - 1)
    runtime.loadState = 'error'
  })
  const tileLayer = new TileLayer({ source, opacity: runtime.opacity, zIndex: 10 })
  wmsLayers.set(runtime.config.id, tileLayer)
  map.addLayer(tileLayer)
}

function detachWmsLayer(runtime: RuntimeLayer) {
  const tileLayer = wmsLayers.get(runtime.config.id)
  if (!tileLayer || !map) return
  map.removeLayer(tileLayer)
  tileLayer.dispose()
  wmsLayers.delete(runtime.config.id)
  runtime.pendingTiles = 0
  runtime.loadState = 'idle'
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
      loadState: 'idle',
      pendingTiles: 0,
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
  if (runtime.visible) attachWmsLayer(runtime)
  else detachWmsLayer(runtime)
}

function updateOpacity(runtime: RuntimeLayer) {
  wmsLayers.get(runtime.config.id)?.setOpacity(runtime.opacity)
}

function switchProjection(crs: string) {
  if (!map || crs === currentCrs.value) return
  currentCrs.value = crs
  applyBaseMapVisibility()
  map.setView(createView(crs))
  fitProjectInitialExtent()
  reloadAisGeometry()
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
  attributeLoading.value = true
  try {
    const filters = attributeFilterField.value && attributeFilterValue.value
      ? [{ field: attributeFilterField.value, operator: 'contains', value: attributeFilterValue.value }]
      : []
    const response = await api.post(`/layers/${attributeLayer.value.id}/features/search`, {
      page: attributePage.value,
      pageSize: 15,
      filters,
    })
    attributeRows.value = response.data.items
    attributeTotal.value = response.data.total
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '属性表加载失败'))
  } finally {
    attributeLoading.value = false
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
  try {
    const response = await api.post(`/layers/${layer.config.id}/identify`, { coordinate, crs: 'EPSG:4326', tolerance: 12 })
    identifyItems.value = response.data.items
    identifyVisible.value = true
  } catch (error) {
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
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '项目地图加载失败'))
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
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
      </div>
      <div class="layer-groups">
        <template v-if="hasFilteredLayers">
          <section v-for="[groupName, datasets] in filteredGroups" :key="groupName" class="layer-group">
            <div class="layer-group-title">{{ groupName }}<span>{{ datasets.length }}</span></div>
            <div v-for="dataset in datasets" :key="dataset.config.id" class="layer-dataset">
              <div class="dataset-summary">
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
                    <small><span :class="['layer-state', runtime.loadState]"></span>{{ runtime.config.queryable ? '可查询' : '仅显示' }}<span v-if="runtime.loadState === 'error'"> · 加载失败</span></small>
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
    <div class="map-status"><span>{{ coordinateText }}</span><span>{{ currentCrs }}</span><span v-if="measureText" class="measure-result">{{ measureText }} <button @click="clearMeasure">清除</button></span></div>
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
