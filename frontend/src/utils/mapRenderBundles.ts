/**
 * Render bundle runtime — manages composite multi-layer TileWMS layers
 * that combine several logical S-57 layers into a single HTTP request.
 *
 * Phase 1: dynamic multi-layer WMS (comma-separated LAYERS / STYLES).
 * Used only in smart render mode when VITE_ENABLE_RENDER_BUNDLES is enabled.
 *
 * Key invariants:
 * - One TileLayer<TileWMS> per bundle (never per logical layer in smart mode)
 * - Atomic replacement: old bundle stays visible until the new bundle's first
 *   tile loads successfully
 * - Logical-layer opacity changes promote a layer out of its bundle (standalone)
 * - Bundle detach disposes the OL layer; standalone layers use per-layer path
 */

import TileLayer from 'ol/layer/Tile'
import TileWMS from 'ol/source/TileWMS'
import type { default as OlMap } from 'ol/Map'
import type { RenderBundleConfig } from '../types'

// ── Types ──────────────────────────────────────────────────────────────

export type BundleStatus = 'idle' | 'warming' | 'active' | 'failed' | 'replacing'

export interface BundleRuntime {
  config: RenderBundleConfig
  layer: TileLayer<TileWMS> | null
  status: BundleStatus
  generation: number
  pendingTiles: number
  loadStateTimer?: ReturnType<typeof window.setTimeout>
  /** When status === 'replacing', the new config we're warming up. */
  pendingReplacement?: BundleRuntime
  /** Error message when status === 'failed'. */
  errorMessage?: string
}

/** Signature for the retry-enabled tile load function (injected by consumer). */
export type TileLoadFunction = (tile: any, src: string) => void

// ── State ──────────────────────────────────────────────────────────────

const bundleRegistry = new Map<string, BundleRuntime>()

// ── Helpers ────────────────────────────────────────────────────────────

/** Build the browser-relative GeoServer URL from a serviceUrl. */
export function browserGeoServerUrl(serviceUrl: string): string {
  if (serviceUrl.startsWith('/')) return serviceUrl
  try {
    const parsed = new URL(serviceUrl, window.location.origin)
    const idx = parsed.pathname.indexOf('/geoserver')
    return idx >= 0 ? parsed.pathname.slice(idx) : serviceUrl
  } catch {
    return serviceUrl
  }
}

/** Create a TileWMS source for a multi-layer bundle. */
export function createBundleTileSource(
  config: RenderBundleConfig,
  tileLoadFunction: TileLoadFunction,
): TileWMS {
  return new TileWMS({
    url: browserGeoServerUrl(config.serviceUrl),
    params: {
      LAYERS: config.layerNames.join(','),
      TILED: true,
      STYLES: config.styles.join(','),
    },
    crossOrigin: 'anonymous',
    transition: 0,
    tileLoadFunction,
  })
}

/** Create a TileLayer for a bundle (source must be created separately). */
export function createBundleTileLayer(
  config: RenderBundleConfig,
  source: TileWMS,
): TileLayer<TileWMS> {
  return new TileLayer({
    source,
    opacity: config.opacity,
    zIndex: config.zIndex,
    extent: config.extent ?? undefined,
    minZoom: config.minZoom ?? undefined,
    maxZoom: config.maxZoom ?? undefined,
    visible: false, // start invisible until first tile loads
  })
}

// ── Lifecycle ──────────────────────────────────────────────────────────

/**
 * Attach a bundle to the map (creates OL layer, starts warming).
 * Returns the runtime. The bundle is NOT visible until the first tile loads.
 */
export function attachBundle(
  config: RenderBundleConfig,
  map: OlMap,
  tileLoadFunction: TileLoadFunction,
  onWarmingComplete: (bundleId: string) => void,
  onError: (bundleId: string, error: string) => void,
): BundleRuntime {
  // Already attached?
  const existing = bundleRegistry.get(config.bundleId)
  if (existing && existing.status !== 'failed') {
    return existing
  }

  const source = createBundleTileSource(config, tileLoadFunction)
  const tileLayer = createBundleTileLayer(config, source)

  const runtime: BundleRuntime = {
    config,
    layer: tileLayer,
    status: 'warming',
    generation: 0,
    pendingTiles: 0,
  }

  // Wire tile events for warming → active transition
  source.on('tileloadstart', () => {
    runtime.pendingTiles += 1
    window.clearTimeout(runtime.loadStateTimer)
    runtime.loadStateTimer = window.setTimeout(() => {
      if (runtime.pendingTiles > 0 && runtime.status === 'warming') {
        // Still warming
      }
    }, 300)
  })

  source.on('tileloadend', () => {
    runtime.pendingTiles = Math.max(0, runtime.pendingTiles - 1)
    if (runtime.pendingTiles === 0 && runtime.status === 'warming') {
      window.clearTimeout(runtime.loadStateTimer)
      runtime.status = 'active'
      tileLayer.setVisible(true)
      onWarmingComplete(config.bundleId)
    }
  })

  source.on('tileloaderror', () => {
    runtime.pendingTiles = Math.max(0, runtime.pendingTiles - 1)
    if (runtime.status === 'warming') {
      window.clearTimeout(runtime.loadStateTimer)
      runtime.status = 'failed'
      runtime.errorMessage = '瓦片加载失败'
      onError(config.bundleId, runtime.errorMessage)
    }
  })

  map.addLayer(tileLayer)
  bundleRegistry.set(config.bundleId, runtime)
  return runtime
}

/**
 * Detach and dispose a bundle from the map.
 */
export function detachBundle(bundleId: string, map: Map): void {
  const runtime = bundleRegistry.get(bundleId)
  if (!runtime) return

  if (runtime.layer) {
    map.removeLayer(runtime.layer)
    runtime.layer.dispose()
  }
  window.clearTimeout(runtime.loadStateTimer)
  bundleRegistry.delete(bundleId)
}

/** Set bundle visibility. */
export function setBundleVisible(bundleId: string, visible: boolean): void {
  const runtime = bundleRegistry.get(bundleId)
  if (!runtime?.layer) return
  runtime.layer.setVisible(visible)
}

/**
 * Atomically replace a bundle.
 *
 * The old bundle stays visible until the new bundle's first tile loads.
 * On failure the old bundle is preserved.
 */
export function replaceBundle(
  oldBundleId: string,
  newConfig: RenderBundleConfig,
  map: OlMap,
  tileLoadFunction: TileLoadFunction,
  onReplaced: (newBundleId: string) => void,
  onReplaceFailed: (newBundleId: string, error: string) => void,
): BundleRuntime | null {
  const oldRuntime = bundleRegistry.get(oldBundleId)
  if (!oldRuntime) {
    // No old bundle — just attach
    return attachBundle(newConfig, map, tileLoadFunction, onReplaced, onReplaceFailed)
  }

  const source = createBundleTileSource(newConfig, tileLoadFunction)
  const tileLayer = createBundleTileLayer(newConfig, source)

  const newRuntime: BundleRuntime = {
    config: newConfig,
    layer: tileLayer,
    status: 'warming',
    generation: (oldRuntime.generation || 0) + 1,
    pendingTiles: 0,
  }

  oldRuntime.status = 'replacing'
  oldRuntime.pendingReplacement = newRuntime

  map.addLayer(tileLayer)
  // New bundle starts invisible; old bundle stays visible

  source.on('tileloadend', () => {
    newRuntime.pendingTiles = Math.max(0, newRuntime.pendingTiles - 1)
    if (newRuntime.pendingTiles === 0 && newRuntime.status === 'warming') {
      window.clearTimeout(newRuntime.loadStateTimer)
      newRuntime.status = 'active'
      // Atomic swap: remove old, show new
      if (oldRuntime.layer) {
        map.removeLayer(oldRuntime.layer)
        oldRuntime.layer.dispose()
      }
      window.clearTimeout(oldRuntime.loadStateTimer)
      bundleRegistry.delete(oldBundleId)
      tileLayer.setVisible(true)
      bundleRegistry.set(newConfig.bundleId, newRuntime)
      onReplaced(newConfig.bundleId)
    }
  })

  source.on('tileloaderror', () => {
    newRuntime.pendingTiles = Math.max(0, newRuntime.pendingTiles - 1)
    if (newRuntime.status === 'warming') {
      window.clearTimeout(newRuntime.loadStateTimer)
      newRuntime.status = 'failed'
      // Restore old bundle
      if (newRuntime.layer) {
        map.removeLayer(newRuntime.layer)
        newRuntime.layer.dispose()
      }
      oldRuntime.status = 'active'
      oldRuntime.pendingReplacement = undefined
      onReplaceFailed(newConfig.bundleId, '瓦片加载失败')
    }
  })

  bundleRegistry.set(newConfig.bundleId, newRuntime)
  return newRuntime
}

// ── Queries ────────────────────────────────────────────────────────────

export function getBundleRuntime(bundleId: string): BundleRuntime | undefined {
  return bundleRegistry.get(bundleId)
}

export function getAllBundleRuntimes(): BundleRuntime[] {
  return Array.from(bundleRegistry.values())
}

export function getActiveBundles(): BundleRuntime[] {
  return Array.from(bundleRegistry.values()).filter((r) => r.status === 'active')
}

export function getWarmingBundles(): BundleRuntime[] {
  return Array.from(bundleRegistry.values()).filter((r) => r.status === 'warming')
}

export function getFailedBundles(): BundleRuntime[] {
  return Array.from(bundleRegistry.values()).filter((r) => r.status === 'failed')
}

/** Find which bundle a logical layer belongs to. */
export function findBundleByLogicalLayer(layerId: string): BundleRuntime | undefined {
  for (const runtime of bundleRegistry.values()) {
    if (runtime.config.layerIds.includes(layerId)) {
      return runtime
    }
  }
  return undefined
}

/** Get logical layer IDs for a bundle. */
export function getBundleLogicalLayerIds(bundleId: string): string[] {
  const runtime = bundleRegistry.get(bundleId)
  return runtime ? [...runtime.config.layerIds] : []
}

/** Check if a logical layer is covered by any active or warming bundle. */
export function isLayerCoveredByBundle(layerId: string): boolean {
  for (const runtime of bundleRegistry.values()) {
    if (
      runtime.config.layerIds.includes(layerId) &&
      (runtime.status === 'active' || runtime.status === 'warming' || runtime.status === 'replacing')
    ) {
      return true
    }
  }
  return false
}

// ── Teardown ───────────────────────────────────────────────────────────

/** Dispose all bundles (e.g. on projection switch or project unload). */
export function disposeAllBundles(map: OlMap): void {
  for (const [, runtime] of bundleRegistry) {
    if (runtime.layer) {
      map.removeLayer(runtime.layer)
      runtime.layer.dispose()
    }
    window.clearTimeout(runtime.loadStateTimer)
  }
  bundleRegistry.clear()
}
