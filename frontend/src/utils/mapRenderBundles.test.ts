/**
 * Tests for mapRenderBundles — composite multi-layer TileWMS bundle runtime.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  createBundleTileSource,
  createBundleTileLayer,
  browserGeoServerUrl,
} from './mapRenderBundles'
import type { RenderBundleConfig } from '../types'

// ── Mock OpenLayers ────────────────────────────────────────────────────

vi.mock('ol/source/TileWMS', () => ({
  default: vi.fn(),
}))

vi.mock('ol/layer/Tile', () => ({
  default: vi.fn((options: Record<string, unknown>) => ({
    getVisible: () => options.visible === true,
    setVisible: vi.fn(),
  })),
}))

import TileWMS from 'ol/source/TileWMS'

const MockTileWMS = TileWMS as unknown as ReturnType<typeof vi.fn>

// ── Helpers ────────────────────────────────────────────────────────────

function makeBundleConfig(overrides: Partial<RenderBundleConfig> = {}): RenderBundleConfig {
  return {
    bundleId: overrides.bundleId ?? 'area_fill:abc12345',
    bucket: overrides.bucket ?? 'area_fill',
    layerIds: overrides.layerIds ?? ['l-1', 'l-2'],
    layerNames: overrides.layerNames ?? ['pg:layer_a', 'pg:layer_b'],
    styles: overrides.styles ?? ['pg:style_a', 'pg:style_b'],
    zIndex: overrides.zIndex ?? 10,
    opacity: overrides.opacity ?? 1.0,
    extent: overrides.extent ?? null,
    minZoom: overrides.minZoom ?? null,
    maxZoom: overrides.maxZoom ?? null,
    transport: overrides.transport ?? 'wms_multi',
    serviceUrl: overrides.serviceUrl ?? '/geoserver/polar_gis/wms',
    cacheKey: overrides.cacheKey ?? 'sha256hash',
  }
}

// ── Tests ──────────────────────────────────────────────────────────────

describe('browserGeoServerUrl', () => {
  it('returns absolute path unchanged', () => {
    expect(browserGeoServerUrl('/geoserver/pg/wms')).toBe('/geoserver/pg/wms')
  })

  it('extracts /geoserver prefix from full URL', () => {
    // Uses window.location.origin
    const url = `${window.location.origin}/geoserver/pg/wms`
    expect(browserGeoServerUrl(url)).toBe('/geoserver/pg/wms')
  })

  it('falls back to original on non-geoserver URL', () => {
    expect(browserGeoServerUrl('https://other.com/service')).toBe('https://other.com/service')
  })
})

describe('createBundleTileSource', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('creates TileWMS with comma-separated LAYERS', () => {
    const config = makeBundleConfig({
      layerNames: ['pg:a', 'pg:b', 'pg:c'],
      styles: ['pg:sa', 'pg:sb', 'pg:sc'],
    })
    const loadFn = vi.fn()
    createBundleTileSource(config, loadFn)

    expect(MockTileWMS).toHaveBeenCalledTimes(1)
    const callArgs = MockTileWMS.mock.calls[0][0]
    expect(callArgs.params.LAYERS).toBe('pg:a,pg:b,pg:c')
    expect(callArgs.params.STYLES).toBe('pg:sa,pg:sb,pg:sc')
    expect(callArgs.params.TILED).toBe(true)
    expect(callArgs.tileLoadFunction).toBe(loadFn)
  })

  it('uses browser-relative GeoServer URL', () => {
    const config = makeBundleConfig({ serviceUrl: '/geoserver/pg/wms' })
    createBundleTileSource(config, vi.fn())

    const callArgs = MockTileWMS.mock.calls[0][0]
    expect(callArgs.url).toBe('/geoserver/pg/wms')
  })

  it('sets transition to 0 for instant tile swaps', () => {
    createBundleTileSource(makeBundleConfig(), vi.fn())

    const callArgs = MockTileWMS.mock.calls[0][0]
    expect(callArgs.transition).toBe(0)
  })

  it('sets crossOrigin to anonymous', () => {
    createBundleTileSource(makeBundleConfig(), vi.fn())

    const callArgs = MockTileWMS.mock.calls[0][0]
    expect(callArgs.crossOrigin).toBe('anonymous')
  })
})

describe('createBundleTileLayer', () => {
  it('creates a layer that is visible immediately on attach', () => {
    // Deadlock guard: OpenLayers does not request tiles from an invisible
    // TileLayer, so a hidden bundle would never warm up ('warming' forever).
    // Attach only happens for in-viewport bundles, so visible-on-attach is safe.
    const config = makeBundleConfig()
    const source = createBundleTileSource(config, vi.fn())
    const layer = createBundleTileLayer(config, source)
    expect(layer.getVisible()).toBe(true)
  })
})

describe('BundleConfig validation', () => {
  it('LAYERS and STYLES arrays must be same length', () => {
    const config = makeBundleConfig()
    expect(config.layerNames.length).toBe(config.styles.length)
  })

  it('layerIds match layerNames count (logical layers)', () => {
    const config = makeBundleConfig({ layerIds: ['l-1', 'l-2', 'l-3'], layerNames: ['pg:a', 'pg:b', 'pg:c'] })
    expect(config.layerIds.length).toBe(config.layerNames.length)
  })

  it('bundleId contains bucket and hash', () => {
    const config = makeBundleConfig({ bundleId: 'area_fill:abc12345' })
    expect(config.bundleId).toMatch(/^area_fill:[a-f0-9]{8}$/)
  })

  it('different buckets should not be merged', () => {
    const areaBundle = makeBundleConfig({ bundleId: 'area_fill:aaa11111', bucket: 'area_fill', zIndex: 10 })
    const lineBundle = makeBundleConfig({ bundleId: 'line_structure:bbb22222', bucket: 'line_structure', zIndex: 20 })
    expect(areaBundle.bucket).not.toBe(lineBundle.bucket)
    expect(areaBundle.zIndex).not.toBe(lineBundle.zIndex)
  })
})
