/**
 * Tests for mapTileMerger — TileWMS source merging for standard render mode.
 *
 * Merge key is (serviceUrl, renderTransport) — layers merge across
 * styles/object classes with per-layer comma-joined STYLES.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('ol/source/TileWMS', () => ({
  default: vi.fn(),
}))
vi.mock('ol/layer/Tile', () => ({
  default: vi.fn(),
}))

import TileWMS from 'ol/source/TileWMS'
import {
  computeMergeKey,
  groupResolvedLayers,
  createMergedTileSource,
  joinLayerParams,
  globalWmsUrl,
  toMergeableLayer,
  type MergeableLayer,
} from './mapTileMerger'
import type { MapLayerConfig } from '../types'

const MockTileWMS = TileWMS as unknown as ReturnType<typeof vi.fn>

// ── Helpers ────────────────────────────────────────────────────────────

function makeLayer(overrides: Partial<MergeableLayer> = {}): MergeableLayer {
  return {
    id: overrides.id ?? 'l-1',
    code: overrides.code ?? 'code-1',
    serviceUrl: overrides.serviceUrl ?? '/geoserver/pg/wms',
    tileServiceUrl: overrides.tileServiceUrl,
    renderTransport: overrides.renderTransport,
    styleName: overrides.styleName,
    objectClass: overrides.objectClass,
    sortOrder: overrides.sortOrder,
    minZoom: overrides.minZoom,
    maxZoom: overrides.maxZoom,
    geoserverLayerName: overrides.geoserverLayerName,
  }
}

// ── Tests ──────────────────────────────────────────────────────────────

describe('computeMergeKey', () => {
  it('is identical for layers with different styleName and objectClass (same endpoint+transport)', () => {
    const a = makeLayer({ id: 'a', styleName: 'pg:s57_depth', objectClass: 'DEPARE', renderTransport: 'gwc_wms', tileServiceUrl: '/geoserver/gwc/service/wms' })
    const b = makeLayer({ id: 'b', styleName: 'pg:s57_land', objectClass: 'LNDARE', renderTransport: 'gwc_wms', tileServiceUrl: '/geoserver/gwc/service/wms' })
    expect(computeMergeKey(a)).toEqual(computeMergeKey(b))
  })

  it('differs when serviceUrl differs', () => {
    const a = makeLayer({ id: 'a', serviceUrl: '/geoserver/ws_a/wms' })
    const b = makeLayer({ id: 'b', serviceUrl: '/geoserver/ws_b/wms' })
    expect(computeMergeKey(a)).not.toEqual(computeMergeKey(b))
  })

  it('differs when renderTransport differs', () => {
    const a = makeLayer({ id: 'a', renderTransport: 'wms' })
    const b = makeLayer({ id: 'b', renderTransport: 'gwc_wms', tileServiceUrl: '/geoserver/gwc/service/wms' })
    expect(computeMergeKey(a)).not.toEqual(computeMergeKey(b))
  })
})

describe('groupResolvedLayers', () => {
  it('merges layers with distinct styles and object classes into one group', () => {
    const layers = [
      makeLayer({ id: 'a', styleName: 'pg:s1', objectClass: 'DEPARE', geoserverLayerName: 'pg:a' }),
      makeLayer({ id: 'b', styleName: null, objectClass: 'SEAARE', geoserverLayerName: 'pg:b' }),
      makeLayer({ id: 'c', styleName: 'pg:s2', objectClass: 'LNDARE', geoserverLayerName: 'pg:c' }),
    ]
    const groups = groupResolvedLayers(layers)
    expect(groups).toHaveLength(1)
    expect(groups[0].layerIds).toHaveLength(3)
    expect(groups[0].layerNames).toEqual(['pg:a', 'pg:b', 'pg:c'])
    expect(groups[0].styles).toEqual(['pg:s1', '', 'pg:s2'])
  })

  it('orders members by zIndex then sortOrder then id', () => {
    const layers = [
      makeLayer({ id: 'lights', objectClass: 'LIGHTS', sortOrder: 1, geoserverLayerName: 'pg:lights' }),
      makeLayer({ id: 'depare', objectClass: 'DEPARE', sortOrder: 2, geoserverLayerName: 'pg:depare' }),
      makeLayer({ id: 'obstrn', objectClass: 'OBSTRN', sortOrder: 3, geoserverLayerName: 'pg:obstrn' }),
    ]
    const groups = groupResolvedLayers(layers)
    expect(groups[0].layerNames).toEqual(['pg:depare', 'pg:obstrn', 'pg:lights'])
  })

  it('splits buckets larger than 20 into chunks', () => {
    const layers = Array.from({ length: 45 }, (_, i) =>
      makeLayer({ id: `l-${i}`, objectClass: 'DEPARE', geoserverLayerName: `pg:l-${i}` }),
    )
    const groups = groupResolvedLayers(layers)
    expect(groups.map((g) => g.layerIds.length)).toEqual([20, 20, 5])
  })

  it('unions zoom ranges across members', () => {
    const layers = [
      makeLayer({ id: 'a', objectClass: 'DEPARE', minZoom: 2, maxZoom: 10 }),
      makeLayer({ id: 'b', objectClass: 'LIGHTS', minZoom: 5, maxZoom: 12 }),
    ]
    const groups = groupResolvedLayers(layers)
    expect(groups[0].minZoom).toBe(2)
    expect(groups[0].maxZoom).toBe(12)
  })

  it('sorts groups by min member zIndex', () => {
    const layers = [
      makeLayer({ id: 'lights', objectClass: 'LIGHTS', serviceUrl: '/geoserver/ws_a/wms' }),
      makeLayer({ id: 'depare', objectClass: 'DEPARE', serviceUrl: '/geoserver/ws_b/wms' }),
    ]
    const groups = groupResolvedLayers(layers)
    // DEPARE zIndex 10 < LIGHTS zIndex 40 → depare group first
    expect(groups[0].layerIds).toEqual(['depare'])
    expect(groups[1].layerIds).toEqual(['lights'])
  })
})

describe('joinLayerParams', () => {
  it('preserves positional empty styles for default-style layers', () => {
    expect(joinLayerParams(['a', 'b', 'c'], ['s1', null, 's2'])).toEqual({
      LAYERS: 'a,b,c',
      STYLES: 's1,,s2',
    })
  })
})

describe('globalWmsUrl', () => {
  it('strips workspace segment from /geoserver/<ws>/wms', () => {
    expect(globalWmsUrl('/geoserver/polar_gis/wms')).toBe('/geoserver/wms')
  })

  it('strips workspace segment from full URL', () => {
    expect(globalWmsUrl('http://host/geoserver/ws/wms')).toBe('http://host/geoserver/wms')
  })

  it('returns global endpoint unchanged', () => {
    expect(globalWmsUrl('/geoserver/wms')).toBe('/geoserver/wms')
  })

  it('returns non-geoserver URL unchanged', () => {
    expect(globalWmsUrl('/other/path')).toBe('/other/path')
  })
})

describe('createMergedTileSource', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('multi-layer group routes to global plain WMS with comma LAYERS/STYLES and no VERSION', () => {
    const group = groupResolvedLayers([
      makeLayer({ id: 'a', objectClass: 'DEPARE', styleName: 'pg:s1', geoserverLayerName: 'pg:a', renderTransport: 'gwc_wms', tileServiceUrl: '/geoserver/gwc/service/wms' }),
      makeLayer({ id: 'b', objectClass: 'LNDARE', styleName: 'pg:s2', geoserverLayerName: 'pg:b', renderTransport: 'gwc_wms', tileServiceUrl: '/geoserver/gwc/service/wms' }),
    ])[0]
    const loadFn = vi.fn()
    createMergedTileSource(group, MockTileWMS as never, loadFn as never)

    const args = MockTileWMS.mock.calls[0][0]
    expect(args.url).toBe('/geoserver/wms')
    expect(args.params.LAYERS).toBe('pg:a,pg:b')
    expect(args.params.STYLES).toBe('pg:s1,pg:s2')
    expect(args.params.TILED).toBe(true)
    expect(args.params.VERSION).toBeUndefined()
    expect(args.tileLoadFunction).toBe(loadFn)
  })

  it('single-layer gwc group keeps GWC endpoint with VERSION 1.1.1', () => {
    const group = groupResolvedLayers([
      makeLayer({ id: 'a', objectClass: 'DEPARE', styleName: 'pg:s1', geoserverLayerName: 'pg:a', renderTransport: 'gwc_wms', tileServiceUrl: '/geoserver/gwc/service/wms' }),
    ])[0]
    createMergedTileSource(group, MockTileWMS as never, vi.fn() as never)

    const args = MockTileWMS.mock.calls[0][0]
    expect(args.url).toBe('/geoserver/gwc/service/wms')
    expect(args.params.LAYERS).toBe('pg:a')
    expect(args.params.VERSION).toBe('1.1.1')
  })

  it('single-layer plain group keeps serviceUrl with no VERSION', () => {
    const group = groupResolvedLayers([
      makeLayer({ id: 'a', objectClass: 'DEPARE', geoserverLayerName: 'pg:a', renderTransport: 'wms' }),
    ])[0]
    createMergedTileSource(group, MockTileWMS as never, vi.fn() as never)

    const args = MockTileWMS.mock.calls[0][0]
    expect(args.url).toBe('/geoserver/pg/wms')
    expect(args.params.VERSION).toBeUndefined()
  })
})

describe('toMergeableLayer', () => {
  it('maps MapLayerConfig fields onto MergeableLayer', () => {
    const config: MapLayerConfig = {
      id: 'cfg-1',
      code: 'cfg-code',
      name: 'n',
      groupName: 'g',
      sortOrder: 7,
      visibleByDefault: true,
      opacity: 1,
      queryable: false,
      exportable: false,
      serviceType: 'wms',
      serviceUrl: '/geoserver/pg/wms',
      serviceLayerName: 'pg:layer',
      styleName: 'pg:style',
      geometryType: 'Polygon',
      minZoom: 3,
      maxZoom: 9,
      objectClass: 'DEPARE',
      metadata: {},
      renderTransport: 'wms',
    }
    const m = toMergeableLayer(config)
    expect(m.id).toBe('cfg-1')
    expect(m.code).toBe('cfg-code')
    expect(m.serviceUrl).toBe('/geoserver/pg/wms')
    expect(m.geoserverLayerName).toBe('pg:layer')
    expect(m.styleName).toBe('pg:style')
    expect(m.objectClass).toBe('DEPARE')
    expect(m.sortOrder).toBe(7)
    expect(m.minZoom).toBe(3)
    expect(m.maxZoom).toBe(9)
    expect(m.renderTransport).toBe('wms')
  })
})
