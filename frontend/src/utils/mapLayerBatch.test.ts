import { describe, it, expect } from 'vitest'
import {
  BULK_ATTACH_BATCH_SIZE,
  BULK_ATTACH_INTERVAL_MS,
  BULK_CONFIRM_THRESHOLD,
  BULK_HARD_LIMIT,
  SMART_MAX_ACTIVE_WMS_LAYERS,
  SMART_MAX_WARMING_LAYERS,
  SMART_MAX_ATTACHED_WMS_LAYERS,
  SMART_SUSPEND_EVICT_DELAY_MS,
  SMART_RECONCILE_DEBOUNCE_MS,
  prepareAttachCandidates,
  evaluateBulkThreshold,
  transformLayerExtent,
  PerLayerStatsManager,
} from './mapLayerBatch'
import type { BulkResolvedLayer } from '../types'

function makeLayer(overrides: Partial<BulkResolvedLayer> = {}): BulkResolvedLayer {
  return {
    id: overrides.id ?? 'layer-1',
    code: 'test_code',
    name: 'Test Layer',
    objectClass: overrides.objectClass ?? 'DEPARE',
    objectNameZh: '水深区域',
    geometryType: 'Multi Polygon',
    geoserverWorkspace: 'test_ws',
    geoserverLayerName: 'test_layer',
    serviceUrl: '/geoserver/test_ws/wms',
    styleName: null,
    opacity: 1,
    minZoom: null,
    maxZoom: null,
    extent: null,
    featureCount: null,
    displayCategory: 'bathymetry',
    loadProfile: 'core_chart',
    displayPriority: overrides.displayPriority ?? 10,
    recommended: true,
    renderable: true,
    loadable: overrides.loadable ?? true,
    styleMapped: true,
    skipReason: null,
    queryable: false,
    exportable: false,
    groupName: '电子海图',
    sortOrder: 0,
  }
}

describe('prepareAttachCandidates', () => {
  it('filters out non-loadable layers', () => {
    const layers = [
      makeLayer({ id: '1', loadable: false }),
      makeLayer({ id: '2', loadable: true }),
    ]
    const { candidates, nonLoadable } = prepareAttachCandidates(layers, new Set())
    expect(candidates).toHaveLength(1)
    expect(candidates[0].id).toBe('2')
    expect(nonLoadable).toBe(1)
  })

  it('skips already-loaded layer IDs', () => {
    const layers = [makeLayer({ id: '1' }), makeLayer({ id: '2' })]
    const { candidates, skipped } = prepareAttachCandidates(layers, new Set(['1']))
    expect(candidates).toHaveLength(1)
    expect(candidates[0].id).toBe('2')
    expect(skipped).toBe(1)
  })

  it('deduplicates by layer ID', () => {
    const layers = [makeLayer({ id: '1' }), makeLayer({ id: '1' })]
    const { candidates } = prepareAttachCandidates(layers, new Set())
    expect(candidates).toHaveLength(1)
  })

  it('sorts by displayPriority, objectClass, then id', () => {
    const layers = [
      makeLayer({ id: 'c', objectClass: 'ZZZ', displayPriority: 50 }),
      makeLayer({ id: 'a', objectClass: 'AAA', displayPriority: 10 }),
      makeLayer({ id: 'b', objectClass: 'AAA', displayPriority: 10 }),
    ]
    const { candidates } = prepareAttachCandidates(layers, new Set())
    expect(candidates.map((l) => l.id)).toEqual(['a', 'b', 'c'])
  })
})

describe('evaluateBulkThreshold', () => {
  it('allows 40 layers without confirmation', () => {
    const result = evaluateBulkThreshold(40)
    expect(result.blocked).toBe(false)
    expect(result.needsConfirm).toBe(false)
  })

  it('needs confirmation for 41 layers', () => {
    const result = evaluateBulkThreshold(41)
    expect(result.blocked).toBe(false)
    expect(result.needsConfirm).toBe(true)
  })

  it('allows 160 layers', () => {
    const result = evaluateBulkThreshold(160)
    expect(result.blocked).toBe(false)
  })

  it('blocks 161 layers', () => {
    const result = evaluateBulkThreshold(161)
    expect(result.blocked).toBe(true)
  })
})

describe('transformLayerExtent', () => {
  it('returns undefined for null input', () => {
    expect(transformLayerExtent(null, 'EPSG:3857')).toBeUndefined()
  })

  it('returns undefined for invalid array', () => {
    expect(transformLayerExtent([1, 2], 'EPSG:3857')).toBeUndefined()
  })

  it('transforms valid EPSG:4326 extent', () => {
    const result = transformLayerExtent([-10, 60, 10, 75], 'EPSG:3857')
    expect(result).toBeDefined()
    expect(result).toHaveLength(4)
    // Swapped corner check: transformed extent should be roughly [-1.1M, 8.4M, 1.1M, 12.9M]
    expect(result![0]).toBeLessThan(0)
    expect(result![2]).toBeGreaterThan(0)
  })
})

describe('constants', () => {
  it('has expected values', () => {
    expect(BULK_ATTACH_BATCH_SIZE).toBe(5)
    expect(BULK_ATTACH_INTERVAL_MS).toBe(200)
    expect(BULK_CONFIRM_THRESHOLD).toBe(40)
    expect(BULK_HARD_LIMIT).toBe(160)
    expect(SMART_MAX_ACTIVE_WMS_LAYERS).toBe(30)
    expect(SMART_MAX_WARMING_LAYERS).toBe(10)
    expect(SMART_MAX_ATTACHED_WMS_LAYERS).toBe(60)
    expect(SMART_SUSPEND_EVICT_DELAY_MS).toBe(30_000)
    expect(SMART_RECONCILE_DEBOUNCE_MS).toBe(150)
  })
})

describe('PerLayerStatsManager', () => {
  it('tracks pending tile count', () => {
    const m = new PerLayerStatsManager()
    expect(m.pendingTileCount).toBe(0)
    m.recordTileStart('layer-1')
    m.recordTileStart('layer-2')
    expect(m.pendingTileCount).toBe(2)
  })

  it('computes average and p95 duration', () => {
    const m = new PerLayerStatsManager()
    m.recordTileStart('a')
    m.recordTileEnd('a') // duration is near-zero
    expect(m.loadedTileCount).toBe(1)
    expect(m.averageTileDurationMs).toBeGreaterThanOrEqual(0)
    expect(m.p95TileDurationMs).toBeGreaterThanOrEqual(0)
  })

  it('tracks errors and pending count drops after error', () => {
    const m = new PerLayerStatsManager()
    m.recordTileStart('x')
    expect(m.pendingTileCount).toBe(1)
    m.recordTileError('x')
    expect(m.pendingTileCount).toBe(0)
    expect(m.failedTileCount).toBe(1)
  })

  it('snapshot returns correct structure', () => {
    const m = new PerLayerStatsManager()
    const s = m.snapshot(3, 5, 2, 1)
    expect(s.activeLayerCount).toBe(3)
    expect(s.attachedLayerCount).toBe(5)
    expect(s.suspendedLayerCount).toBe(2)
    expect(s.currentGeneration).toBe(1)
    expect(s.averageTileDurationMs).toBeGreaterThanOrEqual(0)
  })

  it('reset clears all', () => {
    const m = new PerLayerStatsManager()
    m.recordTileStart('a')
    m.recordTileError('a')
    m.recordRetry()
    m.reset()
    expect(m.pendingTileCount).toBe(0)
    expect(m.failedTileCount).toBe(0)
    expect(m.retryCount).toBe(0)
  })
})
