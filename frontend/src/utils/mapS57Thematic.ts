/**
 * Pure map helpers for the S-57 depth/hazard thematic sample overlay.
 * This is a display-only sample; it never loads a full thematic export.
 */
import Feature from 'ol/Feature'
import type Geometry from 'ol/geom/Geometry'
import GeoJSON from 'ol/format/GeoJSON'
import { createEmpty, extend, getCenter } from 'ol/extent'
import { Circle as CircleStyle, Fill, Style, Stroke } from 'ol/style'

export const THEMATIC_OVERLAY_Z_INDEX = 79

const CATEGORY_COLORS: Record<string, { stroke: string; fill: string }> = {
  depth: { stroke: '#38bdf8', fill: 'rgba(56, 189, 248, 0.22)' },
  depth_supplement: { stroke: '#2dd4bf', fill: 'rgba(45, 212, 191, 0.16)' },
  hazards: { stroke: '#fb7185', fill: 'rgba(251, 113, 133, 0.18)' },
  other: { stroke: '#c4b5fd', fill: 'rgba(196, 181, 253, 0.14)' },
}

export function thematicCategoryColor(category: string | null | undefined): string {
  return (CATEGORY_COLORS[String(category ?? 'other')] ?? CATEGORY_COLORS.other).stroke
}

function geometryKind(geometry: Geometry | undefined): 'point' | 'line' | 'area' {
  const type = geometry?.getType() ?? ''
  if (type.includes('Point')) return 'point'
  if (type.includes('Polygon')) return 'area'
  return 'line'
}

export function thematicStyleForFeature(
  feature: Feature<Geometry>,
  cache?: Map<string, Style>,
  resolution?: number,
): Style {
  const category = String(feature.get('category') ?? 'other')
  const colors = CATEGORY_COLORS[category] ?? CATEGORY_COLORS.other
  const kind = geometryKind(feature.getGeometry())
  const lowZoom = resolution !== undefined && Number.isFinite(resolution) && resolution > 10_000
  const key = `${category}|${kind}|${lowZoom ? 'low' : 'high'}`
  const cached = cache?.get(key)
  if (cached) return cached
  const style =
    kind === 'point'
      ? new Style({
          image: new CircleStyle({
            radius: lowZoom ? 3.5 : 5,
            fill: new Fill({ color: colors.fill }),
            stroke: new Stroke({ color: colors.stroke, width: lowZoom ? 1 : 1.5 }),
          }),
        })
      : new Style({
          fill: kind === 'area' ? new Fill({ color: colors.fill }) : undefined,
          stroke: new Stroke({ color: colors.stroke, width: lowZoom ? 1 : 1.8 }),
        })
  cache?.set(key, style)
  return style
}

export interface ThematicPreviewFeature {
  type: 'Feature'
  geometry: Record<string, unknown> | null
  properties: Record<string, unknown>
}

export function thematicPreviewExtent(
  features: ThematicPreviewFeature[],
  crs: string,
): [number, number, number, number] | null {
  const format = new GeoJSON()
  const extent = createEmpty()
  let has = false
  for (const item of features) {
    if (!item.geometry) continue
    try {
      const feature = format.readFeature(
        { type: 'Feature', geometry: item.geometry, properties: item.properties },
        { dataProjection: 'EPSG:4326', featureProjection: crs },
      )
      const geometry = (feature as Feature<Geometry>).getGeometry()
      if (!geometry) continue
      const itemExtent = geometry.getExtent() as [number, number, number, number]
      if (itemExtent[0] === itemExtent[2] && itemExtent[1] === itemExtent[3]) {
        const [x, y] = getCenter(itemExtent)
        extend(extent, [x - 1500, y - 1500, x + 1500, y + 1500])
      } else {
        extend(extent, itemExtent)
      }
      has = true
    } catch {
      // Ignore a malformed sample feature; the manifest remains authoritative.
    }
  }
  return has ? (extent as [number, number, number, number]) : null
}
