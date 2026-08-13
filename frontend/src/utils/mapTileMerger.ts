/**
 * TileWMS source merging for standard (per-layer) render mode.
 *
 * When many S-57 layers are loaded simultaneously, creating one TileWMS
 * source per layer generates excessive HTTP requests. This module groups
 * layers that can share a single TileWMS source with comma-separated
 * LAYERS / STYLES params — the same pattern used by bundle mode
 * (createBundleTileSource) — reducing request count proportionally.
 *
 * Merge key is (serviceUrl, renderTransport) only: layers merge across
 * styles and object classes, with per-layer comma-joined STYLES (empty
 * slot = GeoServer default style, proven by bundle mode). Multi-layer
 * groups force the plain WMS endpoint — GWC WMS-C rejects comma-separated
 * LAYERS — while single-layer GWC groups keep the GWC tile endpoint.
 */

import TileWMS from 'ol/source/TileWMS'
import type { MapLayerConfig } from '../types'
import { browserGeoServerUrl } from './mapRenderBundles'
import { ENABLE_GWC_TILES } from './mapLayerBatch'

// ── Constants ─────────────────────────────────────────────────────────

/** Maximum layers per merged group before splitting (prevents URL length overflow). */
const MAX_LAYERS_PER_GROUP = 20

// ── Types ─────────────────────────────────────────────────────────────

/**
 * Minimal shape needed to merge a layer into a shared TileWMS source.
 * BulkResolvedLayer satisfies it structurally; MapLayerConfig is adapted
 * via toMergeableLayer().
 */
export interface MergeableLayer {
  id: string
  code: string
  serviceUrl: string
  tileServiceUrl?: string
  renderTransport?: string
  styleName?: string | null
  objectClass?: string | null
  sortOrder?: number
  minZoom?: number | null
  maxZoom?: number | null
  geoserverLayerName?: string | null
}

/** Key that determines whether two layers can share a TileWMS source. */
export interface MergeGroupKey {
  /** Effective WMS endpoint URL (GWC or regular, already normalized). */
  serviceUrl: string
  /** 'wms' | 'gwc_wms' — determines VERSION param. */
  renderTransport: string
}

/** A group of layers that will share one TileWMS source. */
export interface MergeGroup {
  key: MergeGroupKey
  layerIds: string[]
  layerNames: string[]   // geoserver-qualified (e.g. "polar_gis:DEPARE")
  styles: string[]       // parallel to layerNames; "" = default
  minZoom: number | null
  maxZoom: number | null
  /** Minimum zIndex across members — group ordering for map insertion. */
  zIndex: number
  /** Fallback regular WMS URL (always from layer.serviceUrl, never GWC).
   *  Used for multi-layer groups since GWC WMS-C rejects comma-separated LAYERS. */
  regularServiceUrl: string
}

// ── Helpers ───────────────────────────────────────────────────────────

const no = (v: string | null | undefined): string => (v ?? '')

/**
 * Get the effective WMS endpoint URL for a layer.
 * GWC-cacheable layers use the tileServiceUrl; others use serviceUrl.
 * Respects the ENABLE_GWC_TILES flag (same gate as attachWmsLayer).
 */
function effectiveServiceUrl(layer: MergeableLayer): string {
  const transport = no(layer.renderTransport)
  if (ENABLE_GWC_TILES && transport === 'gwc_wms' && layer.tileServiceUrl) {
    return layer.tileServiceUrl
  }
  return layer.serviceUrl
}

/**
 * Adapt a MapLayerConfig into the minimal MergeableLayer shape so the
 * runtime-config paths (buildMap, projection switch) can share
 * groupResolvedLayers with the bulk-resolve path.
 */
export function toMergeableLayer(config: MapLayerConfig): MergeableLayer {
  return {
    id: config.id,
    code: config.code,
    serviceUrl: config.serviceUrl,
    tileServiceUrl: config.tileServiceUrl,
    renderTransport: config.renderTransport,
    styleName: config.styleName,
    objectClass: config.objectClass,
    sortOrder: config.sortOrder,
    minZoom: config.minZoom,
    maxZoom: config.maxZoom,
    geoserverLayerName: config.serviceLayerName,
  }
}

// ── Key computation ───────────────────────────────────────────────────

/**
 * Compute a deterministic merge-group key from a layer.
 * Layers with identical keys can share one TileWMS source.
 */
export function computeMergeKey(layer: MergeableLayer): MergeGroupKey {
  return {
    serviceUrl: effectiveServiceUrl(layer),
    renderTransport: no(layer.renderTransport) || 'wms',
  }
}

// ── Grouping ──────────────────────────────────────────────────────────

/**
 * Partition a flat list of layers into merge groups.
 *
 * Layers are grouped by (serviceUrl, renderTransport). Groups larger than
 * MAX_LAYERS_PER_GROUP are split into sub-groups. Members are ordered by
 * (zIndex, sortOrder, id) because GeoServer paints comma-separated LAYERS
 * bottom-to-top — the order must mirror client-side zIndex stacking.
 */
export function groupResolvedLayers(candidates: MergeableLayer[]): MergeGroup[] {
  // 1. Build map: serialized key → layers
  const buckets = new Map<string, MergeableLayer[]>()

  for (const layer of candidates) {
    const key = computeMergeKey(layer)
    const serialized = `${key.serviceUrl}|${key.renderTransport}`
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
    // Order by zIndex then sortOrder then id: GeoServer draws comma-separated
    // LAYERS sequentially (first = bottom), mirroring client-side stacking.
    bucket.sort((a, b) => {
      const dz = layerZIndex(a.objectClass) - layerZIndex(b.objectClass)
      if (dz !== 0) return dz
      const ds = (a.sortOrder ?? 999) - (b.sortOrder ?? 999)
      if (ds !== 0) return ds
      return a.id.localeCompare(b.id)
    })

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
        if (layer.minZoom !== null && layer.minZoom !== undefined) {
          minZoom = minZoom === null ? layer.minZoom : Math.min(minZoom, layer.minZoom)
        }
        if (layer.maxZoom !== null && layer.maxZoom !== undefined) {
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
        // Chunk is zIndex-sorted ascending → first member carries the min zIndex
        zIndex: layerZIndex(first.objectClass),
        regularServiceUrl: first.serviceUrl,
      })
    }
  }

  // 3. Sort groups by zIndex (asc) for correct rendering order
  //    Lower zIndex draws first; higher zIndex draws on top.
  groups.sort((a, b) => a.zIndex - b.zIndex)

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

// ── Params helpers ────────────────────────────────────────────────────

/** Comma-join LAYERS and STYLES with positional '' for default styles. */
export function joinLayerParams(
  layerNames: string[],
  styles: Array<string | null | undefined>,
): { LAYERS: string; STYLES: string } {
  return { LAYERS: layerNames.join(','), STYLES: styles.map((s) => s ?? '').join(',') }
}

/**
 * '/geoserver/<ws>/wms' → '/geoserver/wms': the global WMS endpoint
 * resolves workspace-qualified layer names of any workspace, so multi-layer
 * groups spanning workspaces don't 400 on the first member's workspace
 * endpoint. Non-matching URLs are returned unchanged.
 */
export function globalWmsUrl(serviceUrl: string): string {
  const m = serviceUrl.match(/^(.*\/geoserver)\/[^/]+\/wms/)
  return m ? `${m[1]}/wms` : serviceUrl
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
  const isMultiLayer = group.layerNames.length > 1

  // GWC WMS-C does NOT support comma-separated multi-layer requests.
  // Multi-layer groups must route through the regular WMS endpoint
  // (global /geoserver/wms — resolves qualified names across workspaces).
  // Single-layer GWC groups can still use the GWC tile endpoint.
  const useGwc = !isMultiLayer && key.renderTransport === 'gwc_wms'

  const url = isMultiLayer
    ? browserGeoServerUrl(globalWmsUrl(group.regularServiceUrl))
    : browserGeoServerUrl(key.serviceUrl)

  return new TileWMSCtor({
    url,
    params: {
      ...joinLayerParams(group.layerNames, group.styles),
      TILED: true,
      ...(useGwc ? { VERSION: '1.1.1' } : {}),
    },
    crossOrigin: 'anonymous',
    transition: 0,
    tileLoadFunction: tileLoadFn,
  }) as TileWMS
}
