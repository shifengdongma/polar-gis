/**
 * TileWMS source merging for standard (per-layer) render mode.
 *
 * When many S-57 layers are loaded simultaneously, creating one TileWMS
 * source per layer generates excessive HTTP requests. This module groups
 * layers that can share a single TileWMS source with comma-separated
 * LAYERS / STYLES params — the same pattern used by bundle mode
 * (createBundleTileSource) — reducing request count proportionally.
 */

import TileWMS from 'ol/source/TileWMS'
import type { BulkResolvedLayer } from '../types'
import { browserGeoServerUrl } from './mapRenderBundles'

// ── Constants ─────────────────────────────────────────────────────────

/** Maximum layers per merged group before splitting (prevents URL length overflow). */
const MAX_LAYERS_PER_GROUP = 20

// ── Types ─────────────────────────────────────────────────────────────

/** Key that determines whether two layers can share a TileWMS source. */
export interface MergeGroupKey {
  /** Effective WMS endpoint URL (GWC or regular, already normalized). */
  serviceUrl: string
  /** 'wms' | 'gwc_wms' — determines VERSION param. */
  renderTransport: string
  /** GeoServer style name ('' = default). */
  styleName: string
  /** S-57 object class for z-index grouping ('' = unclassified). */
  objectClass: string
}

/** A group of layers that will share one TileWMS source. */
export interface MergeGroup {
  key: MergeGroupKey
  layerIds: string[]
  layerNames: string[]   // geoserver-qualified (e.g. "polar_gis:DEPARE")
  styles: string[]       // parallel to layerNames; "" = default
  minZoom: number | null
  maxZoom: number | null
}

// ── Helpers ───────────────────────────────────────────────────────────

const no = (v: string | null | undefined): string => (v ?? '')

/**
 * Get the effective WMS endpoint URL for a layer.
 * GWC-cacheable layers use the tileServiceUrl; others use serviceUrl.
 */
function effectiveServiceUrl(layer: BulkResolvedLayer): string {
  const transport = no(layer.renderTransport)
  if (transport === 'gwc_wms' && layer.tileServiceUrl) {
    return layer.tileServiceUrl
  }
  return layer.serviceUrl
}

// ── Key computation ───────────────────────────────────────────────────

/**
 * Compute a deterministic merge-group key from a resolved layer.
 * Layers with identical keys can share one TileWMS source.
 */
export function computeMergeKey(layer: BulkResolvedLayer): MergeGroupKey {
  return {
    serviceUrl: effectiveServiceUrl(layer),
    renderTransport: no(layer.renderTransport) || 'wms',
    styleName: no(layer.styleName),
    objectClass: no(layer.objectClass),
  }
}

// ── Grouping ──────────────────────────────────────────────────────────

/**
 * Partition a flat list of resolved layers into merge groups.
 *
 * Layers are grouped by (serviceUrl, renderTransport, styleName, objectClass).
 * Groups larger than MAX_LAYERS_PER_GROUP are split into sub-groups.
 */
export function groupResolvedLayers(candidates: BulkResolvedLayer[]): MergeGroup[] {
  // 1. Build map: serialized key → layers
  const buckets = new Map<string, BulkResolvedLayer[]>()

  for (const layer of candidates) {
    const key = computeMergeKey(layer)
    const serialized = `${key.serviceUrl}|${key.renderTransport}|${key.styleName}|${key.objectClass}`
    let bucket = buckets.get(serialized)
    if (!bucket) {
      bucket = []
      buckets.set(serialized, bucket)
    }
    bucket.push(layer)
  }

  // 2. Convert buckets to groups, splitting oversized ones
  const groups: MergeGroup[] = []

  for (const bucket of buckets.values()) {
    // Sort by sortOrder for stable layer ordering within a group
    bucket.sort((a, b) => (a.sortOrder ?? 999) - (b.sortOrder ?? 999))

    // Split large buckets into chunks of MAX_LAYERS_PER_GROUP
    for (let i = 0; i < bucket.length; i += MAX_LAYERS_PER_GROUP) {
      const chunk = bucket.slice(i, i + MAX_LAYERS_PER_GROUP)
      const first = chunk[0]
      const key = computeMergeKey(first)

      const layerIds: string[] = []
      const layerNames: string[] = []
      const styles: string[] = []
      let minZoom: number | null = null
      let maxZoom: number | null = null

      for (const layer of chunk) {
        layerIds.push(layer.id)
        layerNames.push(layer.geoserverLayerName ?? layer.code)
        styles.push(no(layer.styleName))
        // Union zooms: min = smallest min, max = largest max
        if (layer.minZoom !== null) {
          minZoom = minZoom === null ? layer.minZoom : Math.min(minZoom, layer.minZoom)
        }
        if (layer.maxZoom !== null) {
          maxZoom = maxZoom === null ? layer.maxZoom : Math.max(maxZoom, layer.maxZoom)
        }
      }

      groups.push({
        key,
        layerIds,
        layerNames,
        styles,
        minZoom,
        maxZoom,
      })
    }
  }

  // 3. Sort groups by zIndex (asc) for correct rendering order
  //    Lower zIndex draws first; higher zIndex draws on top.
  groups.sort((a, b) => {
    const za = layerZIndex(a.key.objectClass || null)
    const zb = layerZIndex(b.key.objectClass || null)
    return za - zb
  })

  return groups
}

// ── zIndex ────────────────────────────────────────────────────────────

/**
 * Compute a stable zIndex for WMS tile layers based on S-57 object class semantics.
 * Mirrors layerZIndex() in MapWorkspaceView.vue.
 */
function layerZIndex(objectClass: string | null | undefined): number {
  const code = (objectClass ?? '').toUpperCase()
  if (['DEPARE', 'LNDARE', 'ICEARE', 'SEAARE'].includes(code)) return 10
  if (['DEPCNT'].includes(code)) return 20
  if (['COALNE', 'NAVLNE', 'FAIRWY'].includes(code)) return 25
  if (['WRECKS', 'OBSTRN', 'UWTROC'].includes(code)) return 30
  if (['SOUNDG'].includes(code)) return 35
  if (['LIGHTS', 'BOYSPP', 'BOYLAT', 'BOYCAR', 'BCNSPP', 'BCNLAT', 'BCNCAR'].includes(code)) return 40
  return 15
}

// ── Source creation ───────────────────────────────────────────────────

/**
 * Create a shared TileWMS source for a merge group.
 *
 * Uses comma-separated LAYERS and STYLES params, mirroring the
 * createBundleTileSource() pattern in mapRenderBundles.ts.
 *
 * @param group       Merge group metadata
 * @param TileWMSCtor The ol/source/TileWMS class (passed by caller to avoid
 *                    coupling the merger to OpenLayers import specifics)
 * @param tileLoadFn  Shared tile load function (with retry + cache + queue)
 */
export function createMergedTileSource(
  group: MergeGroup,
  TileWMSCtor: typeof TileWMS,
  tileLoadFn: (tile: any, src: string) => void,
): TileWMS {
  const key = group.key
  const useGwc = key.renderTransport === 'gwc_wms'

  return new TileWMSCtor({
    url: browserGeoServerUrl(key.serviceUrl),
    params: {
      LAYERS: group.layerNames.join(','),
      TILED: true,
      STYLES: group.styles.join(','),
      ...(useGwc ? { VERSION: '1.1.1' } : {}),
    },
    crossOrigin: 'anonymous',
    transition: 0,
    tileLoadFunction: tileLoadFn,
  }) as TileWMS
}
