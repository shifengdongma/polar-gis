import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createGwcTileGrid,
  extractOwsException,
  fetchWmtsCapabilitiesWithRetry,
  isDirectTileTemplate,
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

  it('refuses an oversized capabilities document before reading it', async () => {
    const text = vi.fn()
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => String(700 * 1024 * 1024) },
      text,
    })
    await expect(
      fetchWmtsCapabilitiesWithRetry('https://example.test/wmts', {
        fetchImpl: fetchImpl as never,
        attempts: 3,
      }),
    ).rejects.toThrow(/体积过大/)
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    expect(text).not.toHaveBeenCalled()
  })

  it('rejects an HTTP 200 OWS ExceptionReport without retrying', async () => {
    const body =
      '<?xml version="1.0"?><ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">' +
      '<ows:Exception exceptionCode="NoApplicableCode"><ows:ExceptionText>' +
      'java.lang.OutOfMemoryError: Java heap space' +
      '</ows:ExceptionText></ows:Exception></ows:ExceptionReport>'
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => body })
    await expect(
      fetchWmtsCapabilitiesWithRetry('https://example.test/wmts', {
        fetchImpl: fetchImpl as never,
        attempts: 3,
      }),
    ).rejects.toThrow(/OutOfMemoryError/)
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })
})

describe('direct GWC tile templates', () => {
  it('detects GetTile templates and ignores capabilities URLs', () => {
    expect(
      isDirectTileTemplate(
        '/geoserver/gwc/service/wmts?REQUEST=GetTile&TILEMATRIX=EPSG:3413:{z}&TILEROW={y}&TILECOL={x}',
      ),
    ).toBe(true)
    expect(
      isDirectTileTemplate('/geoserver/gwc/service/wmts?REQUEST=GetCapabilities'),
    ).toBe(false)
  })

  it('builds the GWC EPSG:3413 grid with top-left origin and 22 levels', () => {
    const grid = createGwcTileGrid('EPSG:3413')
    expect(grid).not.toBeNull()
    expect(grid!.getOrigin(0)).toEqual([-4194304, 4194304])
    expect(grid!.getResolutions()?.[0]).toBe(32768)
    expect(grid!.getResolutions()?.[1]).toBe(16384)
    expect(grid!.getResolutions()).toHaveLength(22)
    expect(grid!.getExtent()).toEqual([-4194304, -4194304, 4194304, 4194304])
  })

  it('builds the GWC EPSG:900913 grid for 3857 basemaps', () => {
    const grid = createGwcTileGrid('EPSG:3857')
    expect(grid).not.toBeNull()
    expect(grid!.getOrigin(0)).toEqual([-20037508.34, 20037508.34])
    expect(grid!.getResolutions()?.[0]).toBeCloseTo(156543.03390625)
    expect(grid!.getResolutions()).toHaveLength(31)
  })

  it('returns null for unknown CRS values', () => {
    expect(createGwcTileGrid('EPSG:4326')).toBeNull()
  })

  it('extracts OWS exception text and returns null for valid documents', () => {
    expect(extractOwsException('<Capabilities><Contents/></Capabilities>')).toBeNull()
    expect(
      extractOwsException(
        '<ows:ExceptionReport><ows:Exception><ows:ExceptionText>boom &amp; bust</ows:ExceptionText></ows:Exception></ows:ExceptionReport>',
      ),
    ).toBe('boom & bust')
  })
})

describe('resolveActiveBaseMapId', () => {
  it('keeps an explicitly remembered id and never auto-selects a chart basemap', () => {
    expect(resolveActiveBaseMapId(['a', 'b'], 'b')).toBe('b')
    expect(resolveActiveBaseMapId(['a', 'b'], 'missing')).toBe('')
    expect(resolveActiveBaseMapId(['a', 'b'])).toBe('')
    expect(resolveActiveBaseMapId([], 'missing')).toBe('')
  })
})
