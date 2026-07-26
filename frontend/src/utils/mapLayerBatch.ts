import { transformExtent } from 'ol/proj'
import type { BulkResolvedLayer } from '../types'

// ── Constants ───────────────────────────────────────────────────────

/** Number of WMS layers created in each batch. */
export const BULK_ATTACH_BATCH_SIZE = 5

/** Delay in milliseconds between consecutive batches. */
export const BULK_ATTACH_INTERVAL_MS = 200

/** Threshold at which a confirmation dialog is shown before loading. */
export const BULK_CONFIRM_THRESHOLD = 40

/** Hard limit — loading is refused beyond this count. */
export const BULK_HARD_LIMIT = 120

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
