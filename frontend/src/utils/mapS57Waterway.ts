/**
 * Pure map helpers for the S-57 waterway thematic overlay.
 *
 * The overlay is a separate VectorLayer; features carry only their opaque API
 * id/class/name. Nothing here imports route stores or draw interactions.
 */
import Feature from 'ol/Feature'
import type Geometry from 'ol/geom/Geometry'
import GeoJSON from 'ol/format/GeoJSON'
import { getCenter } from 'ol/extent'
import { Circle as CircleStyle, Fill, Style, Stroke } from 'ol/style'
import type { S57WaterwaySearchItem, WaterwayGroup } from '../types/s57Waterways'

export const WATERWAY_OVERLAY_Z_INDEX = 78

const GROUP_COLORS: Record<
  WaterwayGroup,
  { stroke: string; fill: string; dash?: number[] }
> = {
  fairway_route: { stroke: '#22d3ee', fill: 'rgba(34, 211, 238, 0.20)' },
  traffic_separation: { stroke: '#f59e0b', fill: 'rgba(245, 158, 11, 0.16)' },
  restriction: { stroke: '#ef4444', fill: 'rgba(239, 68, 68, 0.14)', dash: [6, 4] },
  waterway_environment: { stroke: '#a78bfa', fill: 'rgba(167, 139, 250, 0.14)' },
}

const AUXILIARY_COLOR = { stroke: '#94a3b8', fill: 'rgba(148, 163, 184, 0.12)', dash: [3, 4] }
const SELECTED_COLOR = '#fde047'

/** Group color used by both the map overlay and the panel legend. */
export function waterwayGroupColor(group: WaterwayGroup | string, auxiliary = false): string {
  if (auxiliary) return AUXILIARY_COLOR.stroke
  return GROUP_COLORS[group as WaterwayGroup]?.stroke ?? GROUP_COLORS.fairway_route.stroke
}

export function waterwayDisplayName(item: Pick<S57WaterwaySearchItem, 'name'>): string {
  const name = item.name?.trim()
  return name || '未命名航道要素'
}

export function waterwaySourceLabel(
  item: Pick<S57WaterwaySearchItem, 'datasetName' | 'sourceCell' | 'versionNo'>,
): string {
  const source = item.sourceCell || item.datasetName
  return item.versionNo > 1 ? `${source} · v${item.versionNo}` : source
}

function geometryKind(geometry: Geometry | undefined): 'point' | 'line' | 'area' {
  const type = geometry?.getType() ?? ''
  if (type.includes('Point')) return 'point'
  if (type.includes('Polygon')) return 'area'
  return 'line'
}

export function waterwayStyleForFeature(
  feature: Feature<Geometry>,
  selected: boolean,
  cache?: Map<string, Style>,
): Style {
  const group = (feature.get('group') as WaterwayGroup) ?? 'fairway_route'
  const auxiliary = Boolean(feature.get('auxiliary'))
  const kind = geometryKind(feature.getGeometry())
  const key = `${group}|${auxiliary ? 'aux' : 'main'}|${kind}|${selected ? 'selected' : 'normal'}`
  const cached = cache?.get(key)
  if (cached) return cached

  const colors = auxiliary ? AUXILIARY_COLOR : GROUP_COLORS[group] ?? GROUP_COLORS.fairway_route
  const stroke = selected ? SELECTED_COLOR : colors.stroke
  const width = selected ? 3.5 : 2
  const style =
    kind === 'point'
      ? new Style({
          image: new CircleStyle({
            radius: selected ? 8 : 5,
            fill: new Fill({ color: colors.fill }),
            stroke: new Stroke({ color: stroke, width }),
          }),
        })
      : new Style({
          fill: kind === 'area' ? new Fill({ color: colors.fill }) : undefined,
          stroke: new Stroke({
            color: stroke,
            width,
            lineDash: selected ? undefined : colors.dash,
          }),
        })
  cache?.set(key, style)
  return style
}

export function waterwayFeatureFromItem(
  item: S57WaterwaySearchItem,
  crs: string,
): Feature<Geometry> | null {
  if (!item.geometry) return null
  try {
    const feature = new GeoJSON().readFeature(item.geometry, {
      dataProjection: 'EPSG:4326',
      featureProjection: crs,
    }) as Feature<Geometry>
    feature.setProperties(
      {
        waterwayId: item.id,
        objectClass: item.objectClass,
        objectNameZh: item.objectNameZh,
        group: item.group,
        auxiliary: item.auxiliary,
        name: item.name,
        renderable: item.renderable,
      },
      true,
    )
    return feature
  } catch {
    return null
  }
}

export function waterwayExtent(
  item: S57WaterwaySearchItem,
  crs: string,
): [number, number, number, number] | null {
  const feature = waterwayFeatureFromItem(item, crs)
  const geometry = feature?.getGeometry()
  if (!geometry) return null
  const extent = geometry.getExtent() as [number, number, number, number]
  if (extent[0] === extent[2] && extent[1] === extent[3]) {
    const [x, y] = getCenter(extent)
    const pad = 2000
    return [x - pad, y - pad, x + pad, y + pad]
  }
  return extent
}
