/**
 * Per-layer S-57 legend request with a module-level cache.
 *
 * The request is made only when the user expands a layer's inline legend.
 * Cache keys include style/object-class so a style change naturally misses;
 * repeating the same expanded row does not hit GeoServer again.
 */
import { api } from '../api/client'
import type { MapLayerConfig } from '../types'

export interface S57LegendFallback {
  geometry: string
  color: string
  fillColor: string | null
  opacity: number
  label: string
}

export interface S57LegendPayload {
  url: string
  objectClass: string | null
  geometryType: string | null
  fallback: S57LegendFallback | null
}

const legendCache = new Map<string, Promise<S57LegendPayload>>()

export function legendCacheKey(layer: MapLayerConfig): string {
  return `${layer.id}:${layer.styleName ?? ''}:${layer.objectClass ?? ''}`
}

export async function fetchLayerLegend(layer: MapLayerConfig): Promise<S57LegendPayload> {
  const key = legendCacheKey(layer)
  let request = legendCache.get(key)
  if (!request) {
    request = api
      .get<S57LegendPayload>(`/layers/${layer.id}/legend`, { timeout: 20_000 })
      .then((response) => response.data)
    legendCache.set(key, request)
    request.catch(() => {
      if (legendCache.get(key) === request) legendCache.delete(key)
    })
  }
  return request
}

export function invalidateLayerLegend(layer: MapLayerConfig) {
  legendCache.delete(legendCacheKey(layer))
}

export function clearLayerLegendCache() {
  legendCache.clear()
}
