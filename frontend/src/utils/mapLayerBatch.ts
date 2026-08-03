import { transformExtent } from 'ol/proj'
import type { BulkResolvedLayer, MapTilePerformanceStats } from '../types'

// ── Constants ───────────────────────────────────────────────────────

/** Number of WMS layers created in each batch. */
export const BULK_ATTACH_BATCH_SIZE = 5

/** Delay in milliseconds between consecutive batches. */
export const BULK_ATTACH_INTERVAL_MS = 200

/** Threshold at which a confirmation dialog is shown before loading. */
export const BULK_CONFIRM_THRESHOLD = 40

/** Hard limit — loading is refused beyond this count. */
export const BULK_HARD_LIMIT = 160

// ── Smart render mode constants ─────────────────────────────────────

/** Maximum number of concurrently active (tile-requesting) WMS layers in smart mode. */
export const SMART_MAX_ACTIVE_WMS_LAYERS = 30

/** Maximum number of layers entering the warming (first-tile) phase simultaneously. */
export const SMART_MAX_WARMING_LAYERS = 10

/** Maximum number of attached (in-memory) WMS layer objects in smart mode. */
export const SMART_MAX_ATTACHED_WMS_LAYERS = 60

/** Delay before a suspended layer is eligible for LRU eviction. */
export const SMART_SUSPEND_EVICT_DELAY_MS = 30_000

/** Debounce interval for the reconcileRenderPlan() scheduler on moveend. */
export const SMART_RECONCILE_DEBOUNCE_MS = 150

/** Zoom threshold below which the overview WMTS is preferred in smart mode. */
export const SMART_OVERVIEW_ZOOM_THRESHOLD = 6

/** Maximum tile retry attempts for recoverable errors (429, 502, 503, 504, network). */
export const TILE_RETRY_MAX_ATTEMPTS = 2

/** Base backoff delay for tile retries (exponential: 300ms, 600ms). */
export const TILE_RETRY_BASE_DELAY_MS = 300

/** Timeout for a layer to produce its first tile before it exits the warming phase. */
export const TILE_WARMING_TIMEOUT_MS = 15_000

/** Timeout for the projection switch double-buffer to force-complete. */
export const PROJECTION_DOUBLE_BUFFER_TIMEOUT_MS = 10_000

// ── Pure helpers ────────────────────────────────────────────────────

/**
 * Filter and sort resolved layers ready for attach.
 * - Removes non-loadable items.
 * - Removes already-loaded IDs.
 * - Deduplicates by ID.
 * - Sorts by (displayPriority, objectClass, id).
 */
export function prepareAttachCandidates(
  resolved: BulkResolvedLayer[],
  loadedLayerIds: ReadonlySet<string>,
): { candidates: BulkResolvedLayer[]; skipped: number; nonLoadable: number } {
  const seen = new Set<string>()
  const candidates: BulkResolvedLayer[] = []
  let nonLoadable = 0
  let skipped = 0

  for (const layer of resolved) {
    if (seen.has(layer.id)) continue
    seen.add(layer.id)

    if (!layer.loadable) {
      nonLoadable++
      continue
    }
    if (loadedLayerIds.has(layer.id)) {
      skipped++
      continue
    }
    candidates.push(layer)
  }

  candidates.sort((a, b) => {
    const pa = a.displayPriority ?? 900
    const pb = b.displayPriority ?? 900
    if (pa !== pb) return pa - pb
    const ca = (a.objectClass ?? '').localeCompare(b.objectClass ?? '')
    if (ca !== 0) return ca
    return (a.id).localeCompare(b.id)
  })

  return { candidates, skipped, nonLoadable }
}

/**
 * Check whether the candidate count exceeds hard limit or confirmation threshold.
 * Returns `blocked` (hard limit exceeded) or `needsConfirm` (over threshold).
 */
export function evaluateBulkThreshold(
  candidateCount: number,
): { blocked: boolean; needsConfirm: boolean } {
  return {
    blocked: candidateCount > BULK_HARD_LIMIT,
    needsConfirm: candidateCount > BULK_CONFIRM_THRESHOLD,
  }
}

/**
 * Convert an EPSG:4326 extent array to the target projection.
 * Returns `undefined` when the input is invalid.
 */
export function transformLayerExtent(
  extent: number[] | null | undefined,
  targetCrs: string,
): number[] | undefined {
  if (!Array.isArray(extent) || extent.length !== 4) return undefined
  try {
    const [minLon, minLat, maxLon, maxLat] = extent.map(Number)
    if ([minLon, minLat, maxLon, maxLat].some((v) => !Number.isFinite(v))) return undefined
    return transformExtent([minLon, minLat, maxLon, maxLat], 'EPSG:4326', targetCrs) as
      | number[]
      | undefined
  } catch {
    return undefined
  }
}

/**
 * Returns a promise that resolves after `ms` milliseconds,
 * or rejects immediately if the signal is aborted or the generation changed.
 */
export function waitForBulkInterval(
  ms: number,
  signal: AbortSignal,
  generation: number,
  currentGeneration: () => number,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted || currentGeneration() !== generation) {
      reject(new DOMException('Bulk load cancelled', 'AbortError'))
      return
    }
    const timer = window.setTimeout(() => {
      if (signal.aborted || currentGeneration() !== generation) {
        reject(new DOMException('Bulk load cancelled', 'AbortError'))
      } else {
        resolve()
      }
    }, ms)
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer)
      reject(new DOMException('Bulk load cancelled', 'AbortError'))
    }, { once: true })
  })
}

// ── Performance stats manager ───────────────────────────────────────

export class PerLayerStatsManager {
  private tileStartTimes = new Map<string, number>()
  private durations: number[] = [] // ring buffer, max 200
  private failures: number[] = [] // timestamps, max 500
  retryCount = 0

  recordTileStart(layerId: string): void {
    this.tileStartTimes.set(layerId, performance.now())
  }

  recordTileEnd(layerId: string): void {
    const start = this.tileStartTimes.get(layerId)
    if (start) {
      this.durations.push(performance.now() - start)
      if (this.durations.length > 200) this.durations.shift()
      this.tileStartTimes.delete(layerId)
    }
  }

  recordTileError(layerId: string): void {
    this.failures.push(Date.now())
    if (this.failures.length > 500) this.failures.shift()
    this.tileStartTimes.delete(layerId)
  }

  recordRetry(): void {
    this.retryCount += 1
  }

  get pendingTileCount(): number {
    return this.tileStartTimes.size
  }

  get loadedTileCount(): number {
    return this.durations.length
  }

  get failedTileCount(): number {
    return this.failures.length
  }

  get averageTileDurationMs(): number {
    if (this.durations.length === 0) return 0
    const sum = this.durations.reduce((a, b) => a + b, 0)
    return Math.round(sum / this.durations.length)
  }

  get p95TileDurationMs(): number {
    if (this.durations.length === 0) return 0
    const sorted = [...this.durations].sort((a, b) => a - b)
    const idx = Math.ceil(sorted.length * 0.95) - 1
    return Math.round(sorted[Math.max(0, idx)])
  }

  /** Returns a snapshot for the current moment. Callers supply layer counts. */
  snapshot(
    activeLayerCount: number,
    attachedLayerCount: number,
    suspendedLayerCount: number,
    currentGeneration: number,
  ): MapTilePerformanceStats {
    // Prune failures older than 60s
    const cutoff = Date.now() - 60_000
    while (this.failures.length > 0 && this.failures[0] < cutoff) this.failures.shift()

    return {
      activeLayerCount,
      attachedLayerCount,
      suspendedLayerCount,
      pendingTileCount: this.pendingTileCount,
      loadedTileCount: this.loadedTileCount,
      failedTileCount: this.failures.length,
      retriedTileCount: this.retryCount,
      averageTileDurationMs: this.averageTileDurationMs,
      p95TileDurationMs: this.p95TileDurationMs,
      currentGeneration,
    }
  }

  reset(): void {
    this.tileStartTimes.clear()
    this.durations.length = 0
    this.failures.length = 0
    this.retryCount = 0
  }
}
