/**
 * Pure-function render scheduler for smart-mode layer management.
 * No side effects, no OpenLayers map dependencies beyond extent utilities.
 *
 * Phase 2 implements: viewport culling, scale range filtering,
 * RenderPlan computation, warming budget, LRU eviction selection.
 */

import type { RenderBundleConfig } from '../types'
import { transformExtent } from 'ol/proj'
import { intersects } from 'ol/extent'
import {
  SMART_MAX_ACTIVE_WMS_LAYERS,
  SMART_MAX_WARMING_LAYERS,
  SMART_MAX_ATTACHED_WMS_LAYERS,
  SMART_SUSPEND_EVICT_DELAY_MS,
  SMART_RECONCILE_DEBOUNCE_MS,
  TILE_WARMING_TIMEOUT_MS,
} from './mapLayerBatch'

// Re-export for consumers that want a single import path
export {
  SMART_MAX_ACTIVE_WMS_LAYERS,
  SMART_MAX_WARMING_LAYERS,
  SMART_MAX_ATTACHED_WMS_LAYERS,
  SMART_SUSPEND_EVICT_DELAY_MS,
  SMART_RECONCILE_DEBOUNCE_MS,
  TILE_WARMING_TIMEOUT_MS,
}

// ── Local constants ──────────────────────────────────────────────────

export const VIEWPORT_BUFFER_RATIO = 0.2

/** Zoom threshold below which the overview WMTS is preferred in smart mode. */
export const SMART_OVERVIEW_ZOOM_THRESHOLD = 6

/** Convert OpenLayers resolution (m/px) to OGC scale denominator. */
export function resolutionToScaleDenom(resolution: number, dpi: number = 90.7): number {
  // scale = resolution * dpi * 39.37 (inches → meters) / (m/inch)
  return resolution * dpi * 39.37
}

/** Convert OGC scale denominator to approximate OpenLayers resolution. */
export function scaleDenomToResolution(scaleDenom: number, dpi: number = 90.7): number {
  return scaleDenom / (dpi * 39.37)
}

// ── Types ─────────────────────────────────────────────────────────────

export type ChartRenderMode = 'standard' | 'smart' | 'overview'

export interface ResolvedLayerMeta {
  id: string
  extent: number[] | null // EPSG:4326 [minLon, minLat, maxLon, maxLat]
  minZoom: number | null
  maxZoom: number | null
  displayPriority: number
  objectClass: string | null
  loadProfile: string
  minScaleDenominator?: number | null
  maxScaleDenominator?: number | null
  renderCost?: number | null
}

export interface RenderPlanInput {
  selectedLayerIds: ReadonlySet<string>
  attachedLayerIds: ReadonlySet<string>
  activeLayerIds: ReadonlySet<string>
  warmingLayerIds: ReadonlySet<string>
  manuallyForcedLayerIds: ReadonlySet<string>
  layers: ResolvedLayerMeta[]
  currentProjection: string
  viewExtent: number[] // [minX, minY, maxX, maxY] in current projection
  zoom: number
  resolution: number
  renderMode: ChartRenderMode
  overviewAvailable: boolean
  /** Pre-fetched bundle plan from the render plan API (smart mode with bundles). */
  bundlePlanInput?: {
    bundles: RenderBundleConfig[]
    standaloneLayerIds: string[]
  }
}

export interface RenderPlan {
  activate: string[] // suspended → active (setVisible(true))
  attach: string[] // not attached → create TileLayer
  suspend: string[] // active → suspended (setVisible(false))
  detach: string[] // suspended → remove (layer.dispose())
  remainActive: string[] // no change needed
  overviewVisible: boolean // show/hide global overview WMTS
  warming: string[] // new layers entering warming queue
  reasonByLayerId: Map<string, string>
  /** Composite bundle plan — only set in smart mode with bundles enabled. */
  bundlePlan?: BundleRenderPlan
}

/** Feature flag: enable composite render bundles in smart mode. */
export const ENABLE_RENDER_BUNDLES: boolean =
  typeof import.meta !== 'undefined' &&
  (import.meta as any).env?.VITE_ENABLE_RENDER_BUNDLES !== 'false'


// ── Bundle render plan (Phase 1) ─────────────────────────────────────

/** Operations to maintain bundle layers in smart mode. */
export interface BundleRenderPlan {
  /** New bundle configs to create (via TileWMS with comma-separated LAYERS). */
  attachBundles: RenderBundleConfig[]
  /** Bundle IDs that should be removed and disposed. */
  detachBundles: string[]
  /** Bundle IDs to setVisible(true). */
  activateBundles: string[]
  /** Bundle IDs to setVisible(false). */
  suspendBundles: string[]
  /** Standalone layer IDs that continue through the per-layer path. */
  standaloneLayerIds: string[]
}

// ── Viewport intersection ─────────────────────────────────────────────

/**
 * Checks whether a layer's EPSG:4326 extent intersects the current viewport
 * in the target projection.  Uses a configurable buffer to prevent
 * rapid activate/suspend cycling on small pans.
 *
 * Returns `true` when extent is null/undefined (conservative fallback).
 */
export function isLayerInViewport(
  layerExtent4326: number[] | null | undefined,
  viewExtent: number[],
  targetProjection: string,
  bufferRatio: number = VIEWPORT_BUFFER_RATIO,
): boolean {
  // Conservatively allow layers without extent metadata
  if (!layerExtent4326 || layerExtent4326.length !== 4) return true
  for (let i = 0; i < 4; i++) {
    if (typeof layerExtent4326[i] !== 'number' || !isFinite(layerExtent4326[i])) return true
  }

  try {
    const projected = transformExtent(
      layerExtent4326 as [number, number, number, number],
      'EPSG:4326',
      targetProjection,
    )
    if (!projected || projected.length !== 4) return true

    // Expand viewport by buffer
    const [vMinX, vMinY, vMaxX, vMaxY] = viewExtent
    const bufX = (vMaxX - vMinX) * bufferRatio
    const bufY = (vMaxY - vMinY) * bufferRatio
    const buffered: number[] = [
      vMinX - bufX,
      vMinY - bufY,
      vMaxX + bufX,
      vMaxY + bufY,
    ]

    return intersects(projected, buffered)
  } catch {
    // Transform failure → conservatively allow
    return true
  }
}

// ── Scale range ───────────────────────────────────────────────────────

/**
 * Per-object-class scale defaults — single source of truth shared between
 * frontend scheduler and backend SLD generation (s57_styles.py).
 */
export const DEFAULT_SCALE_HINTS: Record<string, { minScaleDenom: number | null; renderCost: number }> = {
  // Always visible reference layers
  COALNE: { minScaleDenom: null, renderCost: 1 },
  LNDARE: { minScaleDenom: null, renderCost: 1 },
  DEPARE: { minScaleDenom: null, renderCost: 1 },
  SEAARE: { minScaleDenom: null, renderCost: 1 },
  ICEARE: { minScaleDenom: null, renderCost: 1 },
  // Contours — hide fine lines at small scales
  DEPCNT: { minScaleDenom: 500_000, renderCost: 2 },
  // High-density point layers — only at large scales
  SOUNDG: { minScaleDenom: 25_000, renderCost: 4 },
  // Navigation aids — medium+ scales
  LIGHTS: { minScaleDenom: 50_000, renderCost: 3 },
  FOGSIG: { minScaleDenom: 50_000, renderCost: 3 },
  BOYCAR: { minScaleDenom: 50_000, renderCost: 3 },
  BOYINB: { minScaleDenom: 50_000, renderCost: 3 },
  BOYISD: { minScaleDenom: 50_000, renderCost: 3 },
  BOYLAT: { minScaleDenom: 50_000, renderCost: 3 },
  BOYSAW: { minScaleDenom: 50_000, renderCost: 3 },
  BOYSPP: { minScaleDenom: 50_000, renderCost: 3 },
  BCNCAR: { minScaleDenom: 50_000, renderCost: 3 },
  BCNISD: { minScaleDenom: 50_000, renderCost: 3 },
  BCNLAT: { minScaleDenom: 50_000, renderCost: 3 },
  BCNSAW: { minScaleDenom: 50_000, renderCost: 3 },
  BCNSPP: { minScaleDenom: 50_000, renderCost: 3 },
  TOPMAR: { minScaleDenom: 50_000, renderCost: 3 },
  // Danger objects — medium+ scales
  WRECKS: { minScaleDenom: 100_000, renderCost: 2 },
  OBSTRN: { minScaleDenom: 100_000, renderCost: 2 },
  UWTROC: { minScaleDenom: 100_000, renderCost: 2 },
  // Mid-zoom layers
  UNSARE: { minScaleDenom: 200_000, renderCost: 2 },
  CTNARE: { minScaleDenom: 200_000, renderCost: 2 },
  RESARE: { minScaleDenom: 200_000, renderCost: 2 },
  HRBARE: { minScaleDenom: 200_000, renderCost: 2 },
  SLCONS: { minScaleDenom: 200_000, renderCost: 2 },
}

/**
 * Determines whether a layer should be visible at the current zoom/scale.
 * Considers explicit `minZoom`/`maxZoom`, explicit `minScaleDenominator`/`maxScaleDenominator`,
 * and falls back to per-object-class defaults in `DEFAULT_SCALE_HINTS`.
 */
export function isLayerInScaleRange(
  zoom: number,
  minZoom: number | null | undefined,
  maxZoom: number | null | undefined,
  resolution: number,
  minScaleDenominator: number | null | undefined,
  maxScaleDenominator: number | null | undefined,
  objectClass?: string | null,
): boolean {
  // 1. Explicit zoom bounds
  if (minZoom != null && zoom < minZoom) return false
  if (maxZoom != null && zoom > maxZoom) return false

  // 2. Resolve effective min scale denom (explicit → default → null)
  let effectiveMinScale = minScaleDenominator ?? null
  if (effectiveMinScale === null || effectiveMinScale === undefined) {
    const code = (objectClass ?? '').toUpperCase()
    effectiveMinScale = DEFAULT_SCALE_HINTS[code]?.minScaleDenom ?? null
  }

  // 3. Resolve effective max scale denom
  const effectiveMaxScale = maxScaleDenominator ?? null

  // 4. Compare against current resolution
  const currentScale = resolutionToScaleDenom(resolution)

  // MinScaleDenominator means: "don't show if scale is larger (more zoomed-out) than this"
  if (effectiveMinScale !== null && currentScale > effectiveMinScale) return false

  // MaxScaleDenominator means: "don't show if scale is smaller (more zoomed-in) than this"
  if (effectiveMaxScale !== null && currentScale < effectiveMaxScale) return false

  return true
}

/** Get the render cost for a layer (from metadata or defaults). */
export function getLayerRenderCost(
  objectClass: string | null | undefined,
  explicitCost: number | null | undefined,
): number {
  if (explicitCost != null) return explicitCost
  const code = (objectClass ?? '').toUpperCase()
  return DEFAULT_SCALE_HINTS[code]?.renderCost ?? 1
}

// ── Sorting ───────────────────────────────────────────────────────────

/**
 * Stable sort: manually forced first → displayPriority ASC →
 * objectClass alphabetical → id alphabetical.
 */
export function sortRenderCandidates(
  layers: ResolvedLayerMeta[],
  manuallyForcedIds: ReadonlySet<string>,
): ResolvedLayerMeta[] {
  return [...layers].sort((a, b) => {
    const aForced = manuallyForcedIds.has(a.id) ? 0 : 1
    const bForced = manuallyForcedIds.has(b.id) ? 0 : 1
    if (aForced !== bForced) return aForced - bForced

    const pa = a.displayPriority ?? 900
    const pb = b.displayPriority ?? 900
    if (pa !== pb) return pa - pb

    const ca = (a.objectClass ?? '').localeCompare(b.objectClass ?? '')
    if (ca !== 0) return ca

    return a.id.localeCompare(b.id)
  })
}

// ── Render plan construction ──────────────────────────────────────────

/**
 * Builds the complete RenderPlan for the current map state.
 *
 * This is the core orchestrator — it takes a snapshot of the map state
 * (selected/attached/active/warming layers, viewport, zoom) and returns
 * a plan with explicit activate/attach/suspend/detach lists.
 *
 * The caller executes the plan on the OpenLayers map.
 */
export function buildRenderPlan(input: RenderPlanInput): RenderPlan {
  const {
    selectedLayerIds,
    attachedLayerIds,
    activeLayerIds,
    warmingLayerIds,
    manuallyForcedLayerIds,
    layers,
    currentProjection,
    viewExtent,
    zoom,
    resolution,
    renderMode,
    overviewAvailable,
    bundlePlanInput,
  } = input

  const reason = new Map<string, string>()

  // ── Overview mode ─────────────────────────────────────────────────
  if (renderMode === 'overview') {
    const suspend: string[] = []
    const detach: string[] = []
    for (const l of layers) {
      if (activeLayerIds.has(l.id)) {
        suspend.push(l.id)
        reason.set(l.id, 'overview_mode')
      }
      if (attachedLayerIds.has(l.id) && !activeLayerIds.has(l.id)) {
        detach.push(l.id)
        reason.set(l.id, 'overview_mode_detach')
      }
    }
    return {
      activate: [],
      attach: [],
      suspend,
      detach,
      remainActive: [],
      overviewVisible: true,
      warming: [],
      reasonByLayerId: reason,
    }
  }

  // ── Standard mode ─────────────────────────────────────────────────
  if (renderMode === 'standard') {
    const attach: string[] = []
    const remainActive: string[] = []
    for (const l of layers) {
      if (!selectedLayerIds.has(l.id)) continue
      if (!attachedLayerIds.has(l.id)) {
        attach.push(l.id)
        reason.set(l.id, 'standard_attach')
      } else if (activeLayerIds.has(l.id)) {
        remainActive.push(l.id)
      }
      // In standard mode, everything that is selected and attached stays active
    }
    // Also reactivate any attached-but-not-active selected layers
    const activate: string[] = []
    for (const l of layers) {
      if (selectedLayerIds.has(l.id) && attachedLayerIds.has(l.id) && !activeLayerIds.has(l.id)) {
        activate.push(l.id)
        reason.set(l.id, 'standard_activate')
      }
    }
    return {
      activate,
      attach,
      suspend: [],
      detach: [],
      remainActive,
      overviewVisible: false,
      warming: attach, // all attachments go through warming
      reasonByLayerId: reason,
    }
  }

  // ── Smart mode ────────────────────────────────────────────────────

  // Phase 1: bundle-aware smart mode — composite multi-layer WMS
  if (ENABLE_RENDER_BUNDLES && bundlePlanInput) {
    const { bundles, standaloneLayerIds: standaloneIds } = bundlePlanInput
    const standaloneSet = new Set(standaloneIds)
    const bundledLayerIds = new Set(bundles.flatMap((b) => b.layerIds))

    // Per-bundle viewport/scale check using union extents + permissive zoom
    const inRangeBundleIds = new Set<string>()
    for (const b of bundles) {
      const inVp = isLayerInViewport(b.extent, viewExtent, currentProjection)
      if (!inVp) continue
      inRangeBundleIds.add(b.bundleId)
    }

    // Determine bundle operations
    const attachBundles: RenderBundleConfig[] = []
    const detachBundles: string[] = []
    const activateBundles: string[] = []
    const suspendBundles: string[] = []

    for (const b of bundles) {
      if (!inRangeBundleIds.has(b.bundleId)) {
        // Out of viewport — suspend if active, detach if attached
        if (false /* TODO: track attached bundles */) {
          suspendBundles.push(b.bundleId)
        }
        continue
      }
      // In range — attach new, activate existing
      attachBundles.push(b)
    }

    // Per-layer management: only standalone layers go through existing path
    const inViewportAndScale = new Set<string>()
    const outOfViewport = new Map<string, string>()
    const outOfScale = new Map<string, string>()

    for (const layer of layers) {
      if (!selectedLayerIds.has(layer.id)) continue
      // Skip bundled layers — handled by bundle plan
      if (bundledLayerIds.has(layer.id)) continue
      const forced = manuallyForcedLayerIds.has(layer.id)

      const inVp = forced || isLayerInViewport(layer.extent, viewExtent, currentProjection)
      const inScale =
        forced ||
        isLayerInScaleRange(
          zoom, layer.minZoom, layer.maxZoom, resolution,
          layer.minScaleDenominator, layer.maxScaleDenominator, layer.objectClass,
        )

      if (inVp && inScale) {
        inViewportAndScale.add(layer.id)
      } else {
        if (!inVp && !forced) outOfViewport.set(layer.id, '视口外休眠')
        if (!inScale && !forced) outOfScale.set(layer.id, '比例尺外休眠')
      }
    }

    // Sort standalone candidates
    const candidates = sortRenderCandidates(
      layers.filter((l) => inViewportAndScale.has(l.id)),
      manuallyForcedLayerIds,
    )

    const maxActive = SMART_MAX_ACTIVE_WMS_LAYERS
    const maxWarming = SMART_MAX_WARMING_LAYERS
    const currentWarmingCount = warmingLayerIds.size

    const toAttach: string[] = []
    const toActivate: string[] = []
    const toSuspend: string[] = []
    const warming: string[] = []

    let queuedForActive = 0
    for (const l of layers) {
      if (activeLayerIds.has(l.id) && inViewportAndScale.has(l.id)) {
        queuedForActive++
      }
    }

    for (const layer of candidates) {
      const lid = layer.id
      if (attachedLayerIds.has(lid)) {
        if (!activeLayerIds.has(lid)) {
          if (queuedForActive < maxActive) {
            toActivate.push(lid)
            reason.set(lid, '进入视口')
            queuedForActive++
          } else {
            toSuspend.push(lid)
            reason.set(lid, '等待加载 (活动预算已满)')
          }
        }
      } else {
        if (warming.length + currentWarmingCount < maxWarming && queuedForActive < maxActive) {
          toAttach.push(lid)
          warming.push(lid)
          queuedForActive++
          reason.set(lid, '正在加载')
        }
      }
    }

    // Suspend standalone layers out of viewport/scale
    for (const layer of layers) {
      if (!activeLayerIds.has(layer.id)) continue
      if (outOfViewport.has(layer.id)) {
        toSuspend.push(layer.id)
        reason.set(layer.id, outOfViewport.get(layer.id)!)
      } else if (outOfScale.has(layer.id)) {
        toSuspend.push(layer.id)
        reason.set(layer.id, outOfScale.get(layer.id)!)
      }
    }

    // LRU eviction (unchanged from per-layer path)
    const toDetach: string[] = []
    const totalAttached = attachedLayerIds.size + toAttach.length
    if (totalAttached > SMART_MAX_ATTACHED_WMS_LAYERS) {
      const excess = totalAttached - SMART_MAX_ATTACHED_WMS_LAYERS
      const evictable = layers
        .filter(
          (l) =>
            attachedLayerIds.has(l.id) &&
            !activeLayerIds.has(l.id) &&
            !manuallyForcedLayerIds.has(l.id) &&
            !selectedLayerIds.has(l.id),
        )
        .sort((a, b) => (a.displayPriority ?? 900) - (b.displayPriority ?? 900))
      for (let i = 0; i < Math.min(excess, evictable.length); i++) {
        toDetach.push(evictable[i].id)
        reason.set(evictable[i].id, 'LRU卸载')
      }
    }

    const overviewVisible = overviewAvailable && zoom < SMART_OVERVIEW_ZOOM_THRESHOLD

    const remainActive: string[] = []
    const planChangeIds = new Set([...toAttach, ...toActivate, ...toSuspend, ...toDetach])
    for (const layer of layers) {
      if (activeLayerIds.has(layer.id) && !planChangeIds.has(layer.id)) {
        remainActive.push(layer.id)
      }
    }

    return {
      activate: toActivate,
      attach: toAttach,
      suspend: toSuspend,
      detach: toDetach,
      remainActive,
      overviewVisible,
      warming,
      reasonByLayerId: reason,
      bundlePlan: {
        attachBundles,
        detachBundles,
        activateBundles,
        suspendBundles,
        standaloneLayerIds: standaloneIds,
      },
    }
  }

  // Per-layer smart mode (existing logic, unchanged)
  const inViewportAndScale = new Set<string>()
  const outOfViewport = new Map<string, string>()
  const outOfScale = new Map<string, string>()

  for (const layer of layers) {
    if (!selectedLayerIds.has(layer.id)) continue
    const forced = manuallyForcedLayerIds.has(layer.id)

    // For manually forced layers, skip viewport/scale checks
    const inVp = forced || isLayerInViewport(layer.extent, viewExtent, currentProjection)
    const inScale =
      forced ||
      isLayerInScaleRange(
        zoom,
        layer.minZoom,
        layer.maxZoom,
        resolution,
        layer.minScaleDenominator,
        layer.maxScaleDenominator,
        layer.objectClass,
      )

    if (inVp && inScale) {
      inViewportAndScale.add(layer.id)
    } else {
      if (!inVp && !forced) {
        outOfViewport.set(layer.id, '视口外休眠')
      }
      if (!inScale && !forced) {
        outOfScale.set(layer.id, '比例尺外休眠')
      }
    }
  }

  // Sort candidates by priority
  const candidates = sortRenderCandidates(
    layers.filter((l) => inViewportAndScale.has(l.id)),
    manuallyForcedLayerIds,
  )

  const maxActive = SMART_MAX_ACTIVE_WMS_LAYERS
  const maxWarming = SMART_MAX_WARMING_LAYERS
  const currentWarmingCount = warmingLayerIds.size

  const toAttach: string[] = []
  const toActivate: string[] = []
  const toSuspend: string[] = []
  const warming: string[] = []

  let queuedForActive = 0
  // Count currently active layers that are staying active
  for (const l of layers) {
    if (activeLayerIds.has(l.id) && inViewportAndScale.has(l.id)) {
      queuedForActive++
    }
  }

  for (const layer of candidates) {
    const lid = layer.id

    if (attachedLayerIds.has(lid)) {
      // Already has OL object
      if (!activeLayerIds.has(lid)) {
        if (queuedForActive < maxActive) {
          toActivate.push(lid)
          reason.set(lid, '进入视口')
          queuedForActive++
        } else {
          toSuspend.push(lid)
          reason.set(lid, '等待加载 (活动预算已满)')
        }
      }
      // else: already active, no change
    } else {
      // Not yet attached — need to create OL object + warm
      if (warming.length + currentWarmingCount < maxWarming && queuedForActive < maxActive) {
        toAttach.push(lid)
        warming.push(lid)
        queuedForActive++
        reason.set(lid, '正在加载')
      }
      // else: will remain unattached (queued behind warming limit)
    }
  }

  // Suspend layers that are active but out of viewport/scale
  for (const layer of layers) {
    if (!activeLayerIds.has(layer.id)) continue
    if (outOfViewport.has(layer.id)) {
      toSuspend.push(layer.id)
      reason.set(layer.id, outOfViewport.get(layer.id)!)
    } else if (outOfScale.has(layer.id)) {
      toSuspend.push(layer.id)
      reason.set(layer.id, outOfScale.get(layer.id)!)
    } else if (
      inViewportAndScale.has(layer.id) &&
      !toActivate.includes(layer.id) &&
      queuedForActive > maxActive
    ) {
      // Not yet in this batch's activate list but budget is exceeded
      // (handled above in candidate loop)
    }
  }

  // ── LRU eviction ─────────────────────────────────────────────────
  const toDetach: string[] = []
  const totalAttached = attachedLayerIds.size + toAttach.length - 0 // snapshot
  if (totalAttached > SMART_MAX_ATTACHED_WMS_LAYERS) {
    const excess = totalAttached - SMART_MAX_ATTACHED_WMS_LAYERS
    // Find suspended layers that are not forced and not recently selected
    const evictable = layers
      .filter(
        (l) =>
          attachedLayerIds.has(l.id) &&
          !activeLayerIds.has(l.id) &&
          !manuallyForcedLayerIds.has(l.id) &&
          !selectedLayerIds.has(l.id),
      )
      .sort((a, b) => (a.displayPriority ?? 900) - (b.displayPriority ?? 900))

    for (let i = 0; i < Math.min(excess, evictable.length); i++) {
      toDetach.push(evictable[i].id)
      reason.set(evictable[i].id, 'LRU卸载')
    }
  }

  // ── Overview visibility ───────────────────────────────────────────
  const overviewVisible = overviewAvailable && zoom < SMART_OVERVIEW_ZOOM_THRESHOLD

  // ── Remain active (no change) ─────────────────────────────────────
  const remainActive: string[] = []
  const planChangeIds = new Set([...toAttach, ...toActivate, ...toSuspend, ...toDetach])
  for (const layer of layers) {
    if (activeLayerIds.has(layer.id) && !planChangeIds.has(layer.id)) {
      remainActive.push(layer.id)
    }
  }

  return {
    activate: toActivate,
    attach: toAttach,
    suspend: toSuspend,
    detach: toDetach,
    remainActive,
    overviewVisible,
    warming,
    reasonByLayerId: reason,
  }
}
