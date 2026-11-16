/**
 * Small, display-only S-57 thematic sample overlay.
 *
 * It loads at most the backend's preview.geojson sample (a few hundred
 * features), never a full depth/hazard export. It is isolated from the
 * waterway overlay, route drawing, planning and measurement.
 */
import { ref } from 'vue'
import type OlMap from 'ol/Map'
import Feature from 'ol/Feature'
import type Geometry from 'ol/geom/Geometry'
import GeoJSON from 'ol/format/GeoJSON'
import VectorLayer from 'ol/layer/Vector'
import VectorSource from 'ol/source/Vector'
import type Style from 'ol/style/Style'
import {
  THEMATIC_OVERLAY_Z_INDEX,
  thematicStyleForFeature,
} from '../utils/mapS57Thematic'

export interface S57ThematicPreviewOptions {
  getMap: () => OlMap | null
  getCrs: () => string
  getFitPadding?: () => [number, number, number, number]
}

export function useS57ThematicPreview(options: S57ThematicPreviewOptions) {
  const visible = ref(false)
  const featureCount = ref(0)
  const error = ref('')
  const exportId = ref<string | null>(null)

  let layer: VectorLayer<VectorSource> | null = null
  let source: VectorSource | null = null
  let attached = false
  let collection: Record<string, unknown> | null = null
  const styleCache = new Map<string, Style>()

  function rebuild(fit = false) {
    if (!source || !layer) return
    source.clear()
    error.value = ''
    featureCount.value = 0
    if (!collection) {
      layer.setVisible(false)
      visible.value = false
      layer.changed()
      return
    }
    try {
      const features = new GeoJSON().readFeatures(collection, {
        dataProjection: 'EPSG:4326',
        featureProjection: options.getCrs(),
      }) as Feature<Geometry>[]
      for (const feature of features) source.addFeature(feature)
      featureCount.value = features.length
      layer.setVisible(features.length > 0)
      visible.value = features.length > 0
      layer.changed()
      const map = options.getMap()
      if (fit && map && features.length > 0) {
        const extent = source.getExtent()
        if (extent && extent.every((value) => Number.isFinite(value))) {
          map.getView().fit(extent, {
            padding: options.getFitPadding?.() ?? [90, 90, 90, 420],
            maxZoom: 10,
            duration: 450,
          })
        }
      }
    } catch {
      error.value = '专题样例预览解析失败'
      layer.setVisible(false)
      visible.value = false
    }
  }

  function showPreview(
    collectionValue: Record<string, unknown>,
    sourceExportId: string,
    fit = true,
  ) {
    collection = collectionValue
    exportId.value = sourceExportId
    rebuild(fit)
  }

  function clear() {
    collection = null
    exportId.value = null
    error.value = ''
    featureCount.value = 0
    rebuild(false)
  }

  function attach() {
    const map = options.getMap()
    if (!map || attached) return
    source = new VectorSource()
    layer = new VectorLayer({
      source,
      zIndex: THEMATIC_OVERLAY_Z_INDEX,
      visible: false,
      style: (feature, resolution) =>
        thematicStyleForFeature(
          feature as Feature<Geometry>,
          styleCache,
          resolution,
        ),
    })
    map.addLayer(layer)
    attached = true
  }

  function reloadForProjection() {
    rebuild(false)
  }

  function dispose() {
    const map = options.getMap()
    if (layer) {
      if (map) map.removeLayer(layer)
      layer.dispose()
    }
    layer = null
    source = null
    attached = false
    collection = null
    styleCache.clear()
    visible.value = false
    featureCount.value = 0
  }

  return {
    visible,
    featureCount,
    error,
    exportId,
    attach,
    showPreview,
    clear,
    reloadForProjection,
    dispose,
  }
}
