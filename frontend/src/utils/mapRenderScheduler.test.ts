import { describe, it, expect, vi } from 'vitest'
import {
  buildRenderPlan,
  isLayerInViewport,
  isLayerInScaleRange,
  sortRenderCandidates,
  resolutionToScaleDenom,
  scaleDenomToResolution,
  type ResolvedLayerMeta,
  type RenderPlanInput,
} from './mapRenderScheduler'
import type { RenderBundleConfig } from '../types'
import {
  SMART_MAX_ACTIVE_WMS_LAYERS,
  SMART_MAX_WARMING_LAYERS,
} from './mapLayerBatch'

// Mock ol/proj (transformExtent) and ol/extent (intersects)
vi.mock('ol/proj', () => ({
  transformExtent: vi.fn((extent: number[], _src: string, _dst: string) => {
    // Simplified: treat input as already in target projection
    return [...extent]
  }),
}))

vi.mock('ol/extent', () => ({
  intersects: vi.fn((extent1: number[], extent2: number[]) => {
    const [aMinX, aMinY, aMaxX, aMaxY] = extent1
    const [bMinX, bMinY, bMaxX, bMaxY] = extent2
    return !(aMaxX < bMinX || aMinX > bMaxX || aMaxY < bMinY || aMinY > bMaxY)
  }),
}))

// ── Helpers ────────────────────────────────────────────────────────────

const EPSG_3857 = 'EPSG:3857'

function makeMeta(overrides: Partial<ResolvedLayerMeta> = {}): ResolvedLayerMeta {
  return {
    id: overrides.id ?? 'layer-1',
    extent: overrides.extent ?? null,
    minZoom: overrides.minZoom ?? null,
    maxZoom: overrides.maxZoom ?? null,
    displayPriority: overrides.displayPriority ?? 10,
    objectClass: overrides.objectClass ?? 'DEPARE',
    loadProfile: overrides.loadProfile ?? 'core_chart',
    minScaleDenominator: overrides.minScaleDenominator ?? null,
    maxScaleDenominator: overrides.maxScaleDenominator ?? null,
    renderCost: overrides.renderCost ?? null,
  }
}

function makeInput(
  overrides: Partial<RenderPlanInput> & { layers: ResolvedLayerMeta[] },
): RenderPlanInput {
  return {
    selectedLayerIds: overrides.selectedLayerIds ?? new Set(overrides.layers.map((l) => l.id)),
    attachedLayerIds: overrides.attachedLayerIds ?? new Set(),
    activeLayerIds: overrides.activeLayerIds ?? new Set(),
    warmingLayerIds: overrides.warmingLayerIds ?? new Set(),
    manuallyForcedLayerIds: overrides.manuallyForcedLayerIds ?? new Set(),
    layers: overrides.layers,
    currentProjection: overrides.currentProjection ?? EPSG_3857,
    viewExtent: overrides.viewExtent ?? [-2000, -2000, 2000, 2000],
    zoom: overrides.zoom ?? 8,
    resolution: overrides.resolution ?? 1000,
    renderMode: overrides.renderMode ?? 'smart',
    overviewAvailable: overrides.overviewAvailable ?? true,
    bundlePlanInput: overrides.bundlePlanInput,
    attachedBundleIds: overrides.attachedBundleIds,
  }
}

function makeBundle(overrides: Partial<RenderBundleConfig> = {}): RenderBundleConfig {
  return {
    bundleId: overrides.bundleId ?? 'bundle-1',
    bucket: overrides.bucket ?? 'bucket-a',
    layerIds: overrides.layerIds ?? ['l1', 'l2'],
    layerNames: overrides.layerNames ?? ['wms_layer_1', 'wms_layer_2'],
    styles: overrides.styles ?? ['style_1', 'style_2'],
    zIndex: overrides.zIndex ?? 10,
    opacity: overrides.opacity ?? 1,
    extent: overrides.extent ?? [10, 45, 20, 55], // inside default viewport [-2000..2000]
    minZoom: overrides.minZoom ?? null,
    maxZoom: overrides.maxZoom ?? null,
    transport: overrides.transport ?? 'wms',
    serviceUrl: overrides.serviceUrl ?? 'http://localhost:8080/geoserver/wms',
    cacheKey: overrides.cacheKey ?? 'cache-1',
  }
}

// ── Viewport tests ─────────────────────────────────────────────────────

describe('isLayerInViewport', () => {
  const viewExtent3857 = [100, 500, 200, 600] // compatible with mocked transform (passthrough)

  it('1: returns true for null extent (conservative)', () => {
    expect(isLayerInViewport(null, viewExtent3857, EPSG_3857)).toBe(true)
  })

  it('2: returns true for extent intersecting viewport', () => {
    // With the mocked transformExtent (passthrough), use viewport in "degree" coords
    const degViewport = [10, 40, 30, 60]
    const layerExtent = [15, 45, 25, 55] // clearly inside
    expect(isLayerInViewport(layerExtent, degViewport, EPSG_3857)).toBe(true)
  })

  it('3: respects buffer ratio — layer just outside but within buffer should still intersect', () => {
    const layerExtent = [210, 500, 220, 600] // just right of viewport (maxX=200)
    // With 20% buffer on width 100 = 20: buffered maxX = 200 + 20 = 220 → intersects
    expect(isLayerInViewport(layerExtent, viewExtent3857, EPSG_3857, 0.2)).toBe(true)
    // Without buffer: no intersect
    expect(isLayerInViewport(layerExtent, viewExtent3857, EPSG_3857, 0.0)).toBe(false)
  })

  it('4: layer completely outside viewport returns false', () => {
    const layerExtent = [500, 500, 600, 600] // far right
    expect(isLayerInViewport(layerExtent, viewExtent3857, EPSG_3857, 0.0)).toBe(false)
  })

  it('5: returns true for invalid array length (conservative)', () => {
    expect(isLayerInViewport([1, 2], viewExtent3857, EPSG_3857)).toBe(true)
  })
})

// ── Scale range tests ──────────────────────────────────────────────────

describe('isLayerInScaleRange', () => {
  it('6: respects explicit minZoom', () => {
    expect(isLayerInScaleRange(5, 8, null, 1000, null, null, 'DEPARE')).toBe(false)
    expect(isLayerInScaleRange(10, 8, null, 1000, null, null, 'DEPARE')).toBe(true)
  })

  it('7: respects explicit maxZoom', () => {
    expect(isLayerInScaleRange(15, null, 12, 1000, null, null, 'DEPARE')).toBe(false)
    expect(isLayerInScaleRange(10, null, 12, 1000, null, null, 'DEPARE')).toBe(true)
  })

  it('8: SOUNDG hidden at low zoom (uses DEFAULT_SCALE_HINTS)', () => {
    // At zoom 5, resolution is large → currentScale is large → SOUNDG minScaleDenom 25000 means
    // "don't show if scale > 25000" → at zoom 5, scale is massive → hidden
    const resAtZoom5 = 40000 // meters/pixel at zoom ~5 for 3857
    expect(isLayerInScaleRange(5, null, null, resAtZoom5, null, null, 'SOUNDG')).toBe(false)
  })

  it('9: SOUNDG visible at high zoom', () => {
    const resAtZoom15 = 4 // meters/pixel at zoom ~15
    expect(isLayerInScaleRange(15, null, null, resAtZoom15, null, null, 'SOUNDG')).toBe(true)
  })

  it('10: COALNE always visible (no min scale)', () => {
    expect(isLayerInScaleRange(5, null, null, 40000, null, null, 'COALNE')).toBe(true)
  })

  it('11: explicit minScaleDenominator overrides defaults', () => {
    // DEPCNT default minScale is 500000 (hidden at zoom 5 with res=40000 → scale ~142M)
    // Explicit minScaleDenom=null removes the default restriction
    expect(isLayerInScaleRange(5, null, null, 40000, null, null, 'DEPCNT')).toBe(false) // default restricts
    // At zoom 18 (res≈1), scale ≈ 3571 < explicit 5000 → visible
    expect(isLayerInScaleRange(18, null, null, 1, 5_000, null, 'DEPCNT')).toBe(true)
    // Verify default blocks at small scale (large zoom out)
    expect(isLayerInScaleRange(5, null, null, 40000, 10_000, null, 'DEPCNT')).toBe(false) // scale ~142M > 10K
  })

  it('12: unknown object class falls through with no scale restriction', () => {
    expect(isLayerInScaleRange(5, null, null, 40000, null, null, 'UNKNOWN_OBJ')).toBe(true)
  })
})

// ── Sorting tests ──────────────────────────────────────────────────────

describe('sortRenderCandidates', () => {
  it('13: manually forced layers come first', () => {
    const layers = [
      makeMeta({ id: 'a', displayPriority: 50 }),
      makeMeta({ id: 'b', displayPriority: 10 }),
      makeMeta({ id: 'c', displayPriority: 30 }),
    ]
    const forced = new Set(['a'])
    const sorted = sortRenderCandidates(layers, forced)
    expect(sorted.map((l) => l.id)).toEqual(['a', 'b', 'c'])
  })

  it('14: sorts by displayPriority, then objectClass, then id', () => {
    const layers = [
      makeMeta({ id: 'z', objectClass: 'ZZZ', displayPriority: 50 }),
      makeMeta({ id: 'a', objectClass: 'AAA', displayPriority: 10 }),
      makeMeta({ id: 'b', objectClass: 'AAA', displayPriority: 10 }),
    ]
    const sorted = sortRenderCandidates(layers, new Set())
    expect(sorted.map((l) => l.id)).toEqual(['a', 'b', 'z'])
  })
})

// ── RenderPlan mode tests ──────────────────────────────────────────────

describe('buildRenderPlan — modes', () => {
  const baseAttrs: Partial<ResolvedLayerMeta> = {
    extent: [10, 45, 20, 55],
    displayPriority: 10,
    objectClass: 'DEPARE',
    loadProfile: 'core_chart',
  }

  it('15: overview mode returns suspend all, overviewVisible=true, no attach/activate', () => {
    const layers = [
      makeMeta({ ...baseAttrs, id: 'l1' }),
      makeMeta({ ...baseAttrs, id: 'l2' }),
    ]
    const input = makeInput({
      layers,
      renderMode: 'overview',
      activeLayerIds: new Set(['l1']),
      attachedLayerIds: new Set(['l1', 'l2']),
    })
    const plan = buildRenderPlan(input)
    expect(plan.overviewVisible).toBe(true)
    expect(plan.activate).toEqual([])
    expect(plan.attach).toEqual([])
    expect(plan.suspend).toContain('l1')
    expect(plan.detach).toContain('l2')
  })

  it('16: standard mode attaches all selected, no viewport culling', () => {
    const layers = [
      makeMeta({ ...baseAttrs, id: 'l1', extent: [5100, 4500, 5200, 4600] }), // far outside viewport
      makeMeta({ ...baseAttrs, id: 'l2', extent: [10, 45, 20, 55] }),
    ]
    const input = makeInput({
      layers,
      renderMode: 'standard',
      viewExtent: [-2000, -2000, 2000, 2000],
    })
    const plan = buildRenderPlan(input)
    expect(plan.overviewVisible).toBe(false)
    // Both selected layers should be in the attach list (neither attached)
    expect(plan.attach).toContain('l1')
    expect(plan.attach).toContain('l2')
    // Standard mode does not suspend
    expect(plan.suspend).toEqual([])
  })

  it('17: standard mode keeps old semantics — no auto-suspend', () => {
    const layers = [makeMeta({ ...baseAttrs, id: 'l1' })]
    const input = makeInput({
      layers,
      renderMode: 'standard',
      activeLayerIds: new Set(['l1']),
      attachedLayerIds: new Set(['l1']),
    })
    const plan = buildRenderPlan(input)
    expect(plan.suspend).toEqual([])
    expect(plan.remainActive).toContain('l1')
  })
})

// ── Smart mode: viewport + scale ───────────────────────────────────────

describe('buildRenderPlan — smart mode filtering', () => {
  const inViewExtent: number[] = [10, 45, 20, 55] // overlaps default viewport [-2000,-2000,2000,2000]
  const outViewExtent: number[] = [5100, 4500, 5200, 4600] // clearly outside [-2000,2000]

  it('18: layer out of viewport is suspended', () => {
    const l1 = makeMeta({ id: 'l1', extent: outViewExtent, displayPriority: 10, objectClass: 'DEPARE' })
    const input = makeInput({
      layers: [l1],
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
      activeLayerIds: new Set(['l1']),
      attachedLayerIds: new Set(['l1']),
    })
    const plan = buildRenderPlan(input)
    expect(plan.suspend).toContain('l1')
  })

  it('19: layer entering viewport is activated', () => {
    const l1 = makeMeta({ id: 'l1', extent: inViewExtent, displayPriority: 10, objectClass: 'DEPARE' })
    const input = makeInput({
      layers: [l1],
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
      attachedLayerIds: new Set(['l1']),
    })
    const plan = buildRenderPlan(input)
    expect(plan.activate).toContain('l1')
  })

  it('20: layer outside scale range is suspended', () => {
    // SOUNDG at low resolution (zoomed out) should be suspended
    const l1 = makeMeta({
      id: 'l1',
      extent: inViewExtent,
      objectClass: 'SOUNDG',
      displayPriority: 30,
    })
    const input = makeInput({
      layers: [l1],
      renderMode: 'smart',
      zoom: 5,
      resolution: 40000, // very zoomed out
      activeLayerIds: new Set(['l1']),
      attachedLayerIds: new Set(['l1']),
    })
    const plan = buildRenderPlan(input)
    expect(plan.suspend).toContain('l1')
  })

  it('21: manually forced layer stays active even outside viewport', () => {
    const l1 = makeMeta({ id: 'l1', extent: outViewExtent, displayPriority: 10, objectClass: 'DEPARE' })
    const input = makeInput({
      layers: [l1],
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
      manuallyForcedLayerIds: new Set(['l1']),
      activeLayerIds: new Set(['l1']),
      attachedLayerIds: new Set(['l1']),
    })
    const plan = buildRenderPlan(input)
    // Forced layer should NOT be suspended
    expect(plan.suspend).not.toContain('l1')
  })

  it('22: overview WMTS visible at low zoom', () => {
    const layers = [makeMeta({ id: 'l1', extent: inViewExtent })]
    const input = makeInput({
      layers,
      renderMode: 'smart',
      zoom: 3,
      resolution: 100000,
    })
    const plan = buildRenderPlan(input)
    expect(plan.overviewVisible).toBe(true)
  })

  it('23: overview WMTS hidden at high zoom', () => {
    const layers = [makeMeta({ id: 'l1', extent: inViewExtent })]
    const input = makeInput({
      layers,
      renderMode: 'smart',
      zoom: 10,
      resolution: 150,
    })
    const plan = buildRenderPlan(input)
    expect(plan.overviewVisible).toBe(false)
  })
})

// ── Warming budget ─────────────────────────────────────────────────────

describe('buildRenderPlan — warming budget', () => {
  const inExtent: number[] = [10, 45, 20, 55]

  it('24: at most SMART_MAX_WARMING_LAYERS enter warming simultaneously', () => {
    const layers = Array.from({ length: 10 }, (_, i) =>
      makeMeta({ id: `l${i}`, extent: inExtent, displayPriority: 10 + i }),
    )
    const input = makeInput({
      layers,
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
    })
    const plan = buildRenderPlan(input)
    expect(plan.attach.length).toBeLessThanOrEqual(SMART_MAX_WARMING_LAYERS)
    expect(plan.warming.length).toBeLessThanOrEqual(SMART_MAX_WARMING_LAYERS)
  })

  it('25: respects active layer budget (SMART_MAX_ACTIVE_WMS_LAYERS)', () => {
    const layers = Array.from({ length: 50 }, (_, i) =>
      makeMeta({ id: `l${i}`, extent: inExtent, displayPriority: 10 + i }),
    )
    const input = makeInput({
      layers,
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
    })
    const plan = buildRenderPlan(input)
    // activate + attach should not exceed maxActive
    const totalNewActive = plan.activate.length + plan.attach.length
    expect(totalNewActive).toBeLessThanOrEqual(SMART_MAX_ACTIVE_WMS_LAYERS)
  })

  it('26: high priority layers get activated first when budget is tight', () => {
    const layers = Array.from({ length: 30 }, (_, i) =>
      makeMeta({ id: `l${i}`, extent: inExtent, displayPriority: i < 3 ? 10 : 900 }),
    )
    const input = makeInput({
      layers,
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
    })
    const plan = buildRenderPlan(input)
    // First 3 (priority 10) should appear before any priority 900 layer
    // in the combined attach + activate output
    const earlyIds = new Set(['l0', 'l1', 'l2'])
    let seenLate = false
    for (const id of [...plan.attach, ...plan.activate]) {
      if (!earlyIds.has(id)) seenLate = true
      else if (seenLate) {
        // A high-priority layer appeared after a low-priority one — wrong
        expect('high-priority layer after low-priority').toBe('unexpected ordering')
      }
    }
    // At minimum, the first 3 attach/activate slots should be high-priority
    const first3 = [...plan.attach, ...plan.activate].slice(0, 3)
    expect(first3.every((id) => earlyIds.has(id))).toBe(true)
  })
})

// ── LRU eviction ───────────────────────────────────────────────────────

describe('buildRenderPlan — LRU eviction', () => {
  it('27: does not evict basemap-protected layers (not in S-57 layer list)', () => {
    // LRU only operates on layers passed in the input. If no layers match
    // eviction criteria, nothing is evicted.
    const layers = [makeMeta({ id: 'l1', extent: [10, 45, 20, 55], displayPriority: 10 })]
    const input = makeInput({
      layers,
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
      selectedLayerIds: new Set(['l1']),
      attachedLayerIds: new Set(['l1']),
      activeLayerIds: new Set(['l1']),
    })
    const plan = buildRenderPlan(input)
    expect(plan.detach).toEqual([])
  })

  it('28: renders plan with reasonByLayerId populated', () => {
    const layers = [makeMeta({ id: 'l1', extent: [10, 45, 20, 55], displayPriority: 10 })]
    const input = makeInput({
      layers,
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
    })
    const plan = buildRenderPlan(input)
    // Attached layer should have a reason
    expect(plan.reasonByLayerId.has('l1')).toBe(true)
  })
})

// ── Edge cases ─────────────────────────────────────────────────────────

describe('buildRenderPlan — edge cases', () => {
  it('29: empty selected layers returns empty plan', () => {
    const input = makeInput({
      layers: [],
      renderMode: 'smart',
      selectedLayerIds: new Set(),
    })
    const plan = buildRenderPlan(input)
    expect(plan.activate).toEqual([])
    expect(plan.attach).toEqual([])
    expect(plan.suspend).toEqual([])
    expect(plan.detach).toEqual([])
  })

  it('30: extent-missing layer not permanently hidden', () => {
    // Layer with null extent should be treated as "always in viewport" (conservative)
    const l1 = makeMeta({ id: 'l1', extent: null, displayPriority: 10, objectClass: 'DEPARE' })
    const input = makeInput({
      layers: [l1],
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
      viewExtent: [0, 0, 1000, 1000], // tiny viewport
    })
    const plan = buildRenderPlan(input)
    // Should be in attach (null extent = always in viewport)
    expect(plan.attach).toContain('l1')
    expect(plan.suspend).not.toContain('l1')
  })

  it('31: layer with non-finite extent values treated as in viewport (conservative)', () => {
    const l1 = makeMeta({
      id: 'l1',
      extent: [NaN, 45, 20, 55],
      displayPriority: 10,
      objectClass: 'DEPARE',
    })
    const input = makeInput({
      layers: [l1],
      renderMode: 'smart',
      zoom: 8,
      resolution: 1000,
    })
    const plan = buildRenderPlan(input)
    // Conservative: null/invalid extent → in viewport → attach
    expect(plan.attach).toContain('l1')
  })
})

// ── Bundle branch (smart mode with composite bundles) ────────────────

describe('buildRenderPlan — bundle branch', () => {
  const inViewExtent: number[] = [10, 45, 20, 55] // inside default viewport [-2000..2000]
  const outViewExtent: number[] = [5100, 4500, 5200, 4600] // clearly outside

  it('33: new bundle in viewport (not attached) → attachBundles, activate empty', () => {
    const bundle = makeBundle({ bundleId: 'b1', extent: inViewExtent })
    const input = makeInput({
      layers: [],
      renderMode: 'smart',
      bundlePlanInput: { bundles: [bundle], standaloneLayerIds: [] },
    })
    const plan = buildRenderPlan(input)
    expect(plan.bundlePlan?.attachBundles.map((b) => b.bundleId)).toContain('b1')
    expect(plan.bundlePlan?.activateBundles).toEqual([])
    expect(plan.bundlePlan?.suspendBundles).toEqual([])
    expect(plan.bundlePlan?.bundledLayerIds).toEqual(['l1', 'l2'])
  })

  it('34: attached + in viewport → activate only, no re-attach', () => {
    const bundle = makeBundle({ bundleId: 'b1', extent: inViewExtent })
    const input = makeInput({
      layers: [],
      renderMode: 'smart',
      attachedBundleIds: new Set(['b1']),
      bundlePlanInput: { bundles: [bundle], standaloneLayerIds: [] },
    })
    const plan = buildRenderPlan(input)
    expect(plan.bundlePlan?.activateBundles).toContain('b1')
    expect(plan.bundlePlan?.attachBundles).toEqual([])
    expect(plan.bundlePlan?.detachBundles).not.toContain('b1')
  })

  it('35: attached + out of viewport → suspendBundles', () => {
    const bundle = makeBundle({ bundleId: 'b1', extent: outViewExtent })
    const input = makeInput({
      layers: [],
      renderMode: 'smart',
      attachedBundleIds: new Set(['b1']),
      bundlePlanInput: { bundles: [bundle], standaloneLayerIds: [] },
    })
    const plan = buildRenderPlan(input)
    expect(plan.bundlePlan?.suspendBundles).toContain('b1')
    expect(plan.bundlePlan?.attachBundles).toEqual([])
    expect(plan.bundlePlan?.activateBundles).toEqual([])
  })

  it('36: attached but absent from new plan → detachBundles (leak fix)', () => {
    const bundle = makeBundle({ bundleId: 'b1', extent: inViewExtent })
    const input = makeInput({
      layers: [],
      renderMode: 'smart',
      attachedBundleIds: new Set(['b1', 'b2']),
      bundlePlanInput: { bundles: [bundle], standaloneLayerIds: [] },
    })
    const plan = buildRenderPlan(input)
    expect(plan.bundlePlan?.detachBundles).toContain('b2')
    expect(plan.bundlePlan?.detachBundles).not.toContain('b1')
  })

  it('37: no attachedBundleIds (legacy callers) → all in-viewport bundles attach', () => {
    const bundles = [
      makeBundle({ bundleId: 'b1', extent: inViewExtent }),
      makeBundle({ bundleId: 'b2', extent: inViewExtent, layerIds: ['l3'] }),
    ]
    const input = makeInput({
      layers: [],
      renderMode: 'smart',
      bundlePlanInput: { bundles, standaloneLayerIds: [] },
    })
    const plan = buildRenderPlan(input)
    expect(plan.bundlePlan?.attachBundles.map((b) => b.bundleId)).toEqual(['b1', 'b2'])
    expect(plan.bundlePlan?.activateBundles).toEqual([])
    expect(plan.bundlePlan?.suspendBundles).toEqual([])
    expect(plan.bundlePlan?.detachBundles).toEqual([])
    // Union of member layer IDs across bundles — safety net input for the view
    expect(plan.bundlePlan?.bundledLayerIds).toEqual(['l1', 'l2', 'l3'])
  })

  it('38: empty bundle plan with attached bundles → all detached (detach fallback)', () => {
    const l1 = makeMeta({ id: 'l1', extent: inViewExtent, displayPriority: 10, objectClass: 'DEPARE' })
    const input = makeInput({
      layers: [l1],
      renderMode: 'smart',
      attachedBundleIds: new Set(['b1', 'b2']),
      bundlePlanInput: { bundles: [], standaloneLayerIds: ['l1'] },
    })
    const plan = buildRenderPlan(input)
    // Detach fallback: every previously mounted bundle is removed when the
    // plan contains no bundles (API returned none / all layers standalone).
    expect([...(plan.bundlePlan?.detachBundles ?? [])].sort()).toEqual(['b1', 'b2'])
    expect(plan.bundlePlan?.attachBundles).toEqual([])
    expect(plan.bundlePlan?.activateBundles).toEqual([])
    expect(plan.bundlePlan?.bundledLayerIds).toEqual([])
    // Standalone layers still flow through the per-layer path — no loss.
    expect(plan.attach).toContain('l1')
  })
})

// ── Resolution ↔ Scale conversion ─────────────────────────────────────

describe('resolution ↔ scale denominator', () => {
  it('32: round-trips correctly', () => {
    const res = 100
    const scale = resolutionToScaleDenom(res)
    const res2 = scaleDenomToResolution(scale)
    expect(res2).toBeCloseTo(res, 0)
  })
})
