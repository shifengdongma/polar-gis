/** Environment overlay geometry, arrow direction, and bathy tile helpers. */
import Feature from 'ol/Feature'
import MultiLineString from 'ol/geom/MultiLineString'
import { fromLonLat, toLonLat, transformExtent } from 'ol/proj'
import { createXYZ } from 'ol/tilegrid'
import type { Extent } from 'ol/extent'
import { Style, Stroke } from 'ol/style'
import type { EnvironmentField, VectorObservation } from '../types/navigation'
import { ICE_EXTENT_3413, ICE_EXTENT_3857 } from './mapIce'

export const ENVIRONMENT_Z_INDEX = {
  bathymetry: 50,
  wind: 64,
  current: 66,
  wave: 68,
} as const

export const BATHY_MAX_ZOOM = 8

export function bathyTileUrl(crs: string): string {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  return `${base}/navigation/environment/tiles/bathymetry/${crs}/{z}/{x}/{y}.png`
}

export function createBathyTileGrid(crs: string) {
  const extent: Extent = crs === 'EPSG:3413' ? ICE_EXTENT_3413 : ICE_EXTENT_3857
  return createXYZ({ extent, maxZoom: BATHY_MAX_ZOOM, tileSize: 256 })
}

/** Convert the current map extent to a WGS84 bbox for vector sampling. */
export function environmentBbox(extent: Extent, crs: string): [number, number, number, number] {
  const [minLon, minLat, maxLon, maxLat] = transformExtent(extent, crs, 'EPSG:4326')
  const west = Math.max(-180, Math.min(180, minLon))
  const east = Math.max(-180, Math.min(180, maxLon))
  const south = Math.max(-89.9, Math.min(89.9, minLat))
  const north = Math.max(-89.9, Math.min(89.9, maxLat))
  return [west, south, east, north]
}

export function arrowLengthForZoom(zoom: number): number {
  // Display-only length: longer arrows at coarse zoom, shorter when zoomed in.
  return Math.max(8_000, 260_000 / Math.pow(2, Math.max(0, zoom - 2)))
}

function arrowBearing(observation: VectorObservation): number | null {
  const from = observation.values.directionFromDeg
  const to = observation.values.directionToDeg
  if (observation.field === 'current') {
    return typeof to === 'number' ? to : null
  }
  if (typeof from === 'number') {
    // Wind/wave APIs expose meteorological/wave FROM; arrows point TO.
    return (from + 180) % 360
  }
  return null
}

export function buildArrowFeature(
  observation: VectorObservation,
  crs: string,
  zoom: number,
): Feature<MultiLineString> | null {
  if (!observation.available) return null
  const bearing = arrowBearing(observation)
  if (bearing === null) return null
  const startLonLat: [number, number] = [observation.longitude, observation.latitude]
  const length = arrowLengthForZoom(zoom)
  const endLonLat = destinationLonLat(startLonLat, length, (bearing * Math.PI) / 180)
  const head1 = destinationLonLat(endLonLat, length * 0.3, ((bearing + 150) * Math.PI) / 180)
  const head2 = destinationLonLat(endLonLat, length * 0.3, ((bearing - 150) * Math.PI) / 180)
  const start = fromLonLat(startLonLat, crs)
  const end = fromLonLat(endLonLat, crs)
  const feature = new Feature({
    geometry: new MultiLineString([
      [start, end],
      [end, fromLonLat(head1, crs)],
      [end, fromLonLat(head2, crs)],
    ]),
  })
  feature.setProperties({
    observationId: observation.id,
    field: observation.field,
    quality: observation.quality,
    source: observation.source,
    values: observation.values,
    matchedTime: observation.matchedTime,
  })
  return feature
}

function numeric(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function environmentMetric(observation: VectorObservation): number | null {
  if (observation.field === 'wave') return numeric(observation.values.heightM)
  return numeric(observation.values.speedMs)
}

export function environmentMetricLabel(observation: VectorObservation): string {
  const metric = environmentMetric(observation)
  if (metric === null) return '—'
  return observation.field === 'wave' ? `${metric.toFixed(1)} m` : `${metric.toFixed(1)} m/s`
}

export function environmentColor(field: EnvironmentField, observation: VectorObservation): string {
  const metric = environmentMetric(observation) ?? 0
  if (field === 'wind') {
    if (metric >= 16) return '#e5484d'
    if (metric >= 11) return '#f59e0b'
    if (metric >= 6) return '#35c3d6'
    return '#8fb8c9'
  }
  if (field === 'current') {
    if (metric >= 0.8) return '#e5484d'
    if (metric >= 0.4) return '#f59e0b'
    if (metric >= 0.15) return '#35c3d6'
    return '#8fb8c9'
  }
  if (metric >= 5) return '#e5484d'
  if (metric >= 3) return '#f59e0b'
  if (metric >= 1.5) return '#35c3d6'
  return '#8fb8c9'
}

export function arrowStyle(field: EnvironmentField): (feature: any) => Style {
  return (feature) => {
    const observation = {
      field,
      values: (feature.get('values') ?? {}) as Record<string, number | boolean | null>,
    } as VectorObservation
    const color = environmentColor(field, observation)
    return new Style({
      stroke: new Stroke({ color, width: 2.2, lineCap: 'round' }),
    })
  }
}

export function environmentValueText(observation: VectorObservation): string {
  const values = observation.values
  if (observation.field === 'wind') {
    return `风速 ${numeric(values.speedMs)?.toFixed(1) ?? '—'} m/s · 来向 ${numeric(values.directionFromDeg)?.toFixed(0) ?? '—'}°`
  }
  if (observation.field === 'current') {
    return `流速 ${numeric(values.speedMs)?.toFixed(2) ?? '—'} m/s · 去向 ${numeric(values.directionToDeg)?.toFixed(0) ?? '—'}°`
  }
  if (observation.field === 'wave') {
    return `浪高 ${numeric(values.heightM)?.toFixed(1) ?? '—'} m · 周期 ${numeric(values.periodS)?.toFixed(1) ?? '—'} s · 来向 ${numeric(values.directionFromDeg)?.toFixed(0) ?? '—'}°`
  }
  if (observation.field === 'bathymetry') {
    return `水深 ${numeric(values.depthM)?.toFixed(0) ?? '—'} m`
  }
  return '—'
}

export function toLonLatPair(coordinate: number[], crs: string): [number, number] {
  const [longitude, latitude] = toLonLat(coordinate, crs)
  return [longitude, latitude]
}

/** Spherical destination point; OL does not export a getDestination helper. */
function destinationLonLat(
  origin: [number, number],
  distanceMeters: number,
  bearingRad: number,
): [number, number] {
  const radius = 6_371_008.8
  const angular = distanceMeters / radius
  const lat1 = (origin[1] * Math.PI) / 180
  const lon1 = (origin[0] * Math.PI) / 180
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angular) +
      Math.cos(lat1) * Math.sin(angular) * Math.cos(bearingRad),
  )
  const lon2 =
    lon1 +
    Math.atan2(
      Math.sin(bearingRad) * Math.sin(angular) * Math.cos(lat1),
      Math.cos(angular) - Math.sin(lat1) * Math.sin(lat2),
    )
  return [((lon2 * 180) / Math.PI + 540) % 360 - 180, (lat2 * 180) / Math.PI]
}
