import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchWmtsCapabilitiesWithRetry,
  normalizeCapabilitiesCrs,
  normalizeCrsName,
  resolveActiveBaseMapId,
  selectWmtsLayerAndMatrix,
} from './basemapLayers'

function capabilities() {
  return {
    Contents: {
      Layer: [
        {
          Identifier: 'polar_gis:polar_global_enc_overview',
          TileMatrixSetLink: [{ TileMatrixSet: 'EPSG:3413' }, { TileMatrixSet: 'EPSG:3857' }],
        },
        {
          Identifier: 'other_layer',
          TileMatrixSetLink: [{ TileMatrixSet: 'EPSG:3857' }],
        },
      ],
      TileMatrixSet: [
        { Identifier: 'EPSG:3413', SupportedCRS: 'urn:ogc:def:crs:EPSG::3413' },
        { Identifier: 'EPSG:3857', SupportedCRS: 'urn:ogc:def:crs:EPSG::3857' },
      ],
    },
  }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('normalizeCrsName', () => {
  it('normalizes common OGC URN and URL forms', () => {
    expect(normalizeCrsName('EPSG:3413')).toBe('EPSG:3413')
    expect(normalizeCrsName('urn:ogc:def:crs:EPSG::3413')).toBe('EPSG:3413')
    expect(normalizeCrsName('urn:ogc:def:crs:EPSG:6.6:3857')).toBe('EPSG:3857')
    expect(normalizeCrsName('http://www.opengis.net/def/crs/EPSG/0/3413')).toBe('EPSG:3413')
    expect(normalizeCrsName('CRS:84')).toBe('EPSG:4326')
  })
})

describe('selectWmtsLayerAndMatrix', () => {
  it('selects the matrix set matching the requested CRS, not the first link', () => {
    const selection = selectWmtsLayerAndMatrix(capabilities(), 'EPSG:3413')
    expect(selection).toEqual({
      layer: 'polar_gis:polar_global_enc_overview',
      matrixSet: 'EPSG:3413',
    })
  })

  it('prefers the overview layer when several layers match', () => {
    const caps = capabilities()
    caps.Contents.Layer.push({
      Identifier: 'another_overview',
      TileMatrixSetLink: [{ TileMatrixSet: 'EPSG:3413' }],
    })
    expect(
      selectWmtsLayerAndMatrix(caps, 'EPSG:3413', 'polar_global_enc_overview'),
    ).toEqual({
      layer: 'polar_gis:polar_global_enc_overview',
      matrixSet: 'EPSG:3413',
    })
  })

  it('fails closed when no matrix set matches the requested CRS', () => {
    expect(selectWmtsLayerAndMatrix(capabilities(), 'EPSG:4326')).toBeNull()
  })

  it('fails closed on an ambiguous CRS match without a preferred name', () => {
    const caps = capabilities()
    caps.Contents.Layer.push({
      Identifier: 'another_layer',
      TileMatrixSetLink: [{ TileMatrixSet: 'EPSG:3413' }],
    })
    expect(selectWmtsLayerAndMatrix(caps, 'EPSG:3413')).toBeNull()
  })

  it('normalizes capabilities SupportedCRS in place', () => {
    const caps = capabilities()
    normalizeCapabilitiesCrs(caps)
    expect(caps.Contents.TileMatrixSet[0].SupportedCRS).toBe('EPSG:3413')
    expect(caps.Contents.TileMatrixSet[1].SupportedCRS).toBe('EPSG:3857')
  })
})

describe('fetchWmtsCapabilitiesWithRetry', () => {
  it('retries a transient 503 and returns the capabilities text', async () => {
    vi.useFakeTimers()
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, text: async () => '' })
      .mockResolvedValueOnce({ ok: true, status: 200, text: async () => '<Capabilities/>' })
    const promise = fetchWmtsCapabilitiesWithRetry('https://example.test/wmts', {
      fetchImpl: fetchImpl as never,
      attempts: 2,
      baseDelayMs: 10,
    })
    await vi.advanceTimersByTimeAsync(10)
    await expect(promise).resolves.toBe('<Capabilities/>')
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('does not retry a 404', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 404, text: async () => '' })
    await expect(
      fetchWmtsCapabilitiesWithRetry('https://example.test/wmts', {
        fetchImpl: fetchImpl as never,
        attempts: 3,
      }),
    ).rejects.toThrow(/404/)
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })
})

describe('resolveActiveBaseMapId', () => {
  it('keeps the remembered id when still available and otherwise picks the first', () => {
    expect(resolveActiveBaseMapId(['a', 'b'], 'b')).toBe('b')
    expect(resolveActiveBaseMapId(['a', 'b'], 'missing')).toBe('a')
    expect(resolveActiveBaseMapId([], 'missing')).toBe('')
  })
})
