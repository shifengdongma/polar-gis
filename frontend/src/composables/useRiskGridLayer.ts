/** Planning risk grid as a WGS84 GeoJSON vector layer. */
import { shallowRef, toRaw } from 'vue'
import type OlMap from 'ol/Map'
import Feature from 'ol/Feature'
import GeoJSON from 'ol/format/GeoJSON'
import VectorLayer from 'ol/layer/Vector'
import VectorSource from 'ol/source/Vector'
import { Fill, Stroke, Style } from 'ol/style'
import type { RiskGridCollection } from '../types/navigation'

export const PLANNING_RISK_Z_INDEX = 70

export interface RiskGridLayerOptions {
  getMap: () => OlMap | null
  getCrs: () => string
}

export function useRiskGridLayer(options: RiskGridLayerOptions) {
  const source = new VectorSource()
  const layer = new VectorLayer({
    source,
    zIndex: PLANNING_RISK_Z_INDEX,
    style: (feature) => riskStyle(feature as Feature),
  })
  const collection = shallowRef<RiskGridCollection | null>(null)
  const selectedCellId = shallowRef<string | null>(null)
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

  function setGrid(next: RiskGridCollection | null) {
    collection.value = next
    layer.setVisible(Boolean(next))
    rebuild()
  }

  function setSelected(cellId: string | null) {
    selectedCellId.value = cellId
    layer.changed()
  }

  function reloadForProjection() {
    rebuild()
  }

  function clear() {
    collection.value = null
    selectedCellId.value = null
    source.clear()
  }

  function rebuild() {
    source.clear()
    const grid = collection.value ? toRaw(collection.value) : null
    if (!grid) return
    const features = new GeoJSON().readFeatures(grid, {
      dataProjection: 'EPSG:4326',
      featureProjection: options.getCrs(),
    })
    source.addFeatures(features)
    layer.changed()
  }

  function pickCellAtPixel(pixel: number[]): string | null {
    const map = options.getMap()
    if (!map) return null
    let hit: string | null = null
    map.forEachFeatureAtPixel(
      pixel,
      (feature) => {
        const cellId = feature.get('cellId')
        if (typeof cellId === 'string') hit = cellId
        return true
      },
      { layerFilter: (candidate) => candidate === layer, hitTolerance: 3 },
    )
    return hit
  }

  function riskStyle(feature: Feature): Style {
    const cellId = String(feature.get('cellId') ?? '')
    const selected = cellId === selectedCellId.value
    const traversable = feature.get('traversable')
    const rawValue = feature.get('value')
    const value = typeof rawValue === 'number' && Number.isFinite(rawValue) ? rawValue : null
    const fill = riskColor(value, traversable)
    return new Style({
      fill: new Fill({ color: fill }),
      stroke: new Stroke({
        color: selected ? '#ffd166' : 'rgba(7, 17, 29, 0.28)',
        width: selected ? 2.5 : 0.6,
      }),
      zIndex: selected ? 20 : 0,
    })
  }

  return {
    layer,
    collection,
    selectedCellId,
    attach,
    dispose,
    setGrid,
    setSelected,
    reloadForProjection,
    pickCellAtPixel,
    clear,
  }
}

function riskColor(value: number | null, traversable: unknown): string {
  if (traversable === false) return 'rgba(90, 100, 110, 0.42)'
  if (value === null) return 'rgba(138, 148, 166, 0.30)'
  const clamped = Math.max(0, Math.min(1, value))
  if (clamped < 0.25) return 'rgba(53, 195, 214, 0.42)'
  if (clamped < 0.5) return 'rgba(143, 184, 201, 0.48)'
  if (clamped < 0.75) return 'rgba(232, 155, 39, 0.52)'
  return 'rgba(229, 72, 77, 0.58)'
}
