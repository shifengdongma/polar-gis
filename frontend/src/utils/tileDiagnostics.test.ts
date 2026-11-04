import { describe, expect, it } from 'vitest'
import { TileDiagnostics, sanitizeTileUrl } from './tileDiagnostics'

describe('sanitizeTileUrl', () => {
  it('keeps the path and only the date query, dropping tokens and WMS parameters', () => {
    expect(
      sanitizeTileUrl('/api/v1/ice/concentration/EPSG:3413/tile/3/4/5.png?date=20220101&token=secret'),
    ).toBe('/api/v1/ice/concentration/EPSG:3413/tile/3/4/5.png?date=20220101')
    expect(
      sanitizeTileUrl('https://example.test/geoserver/wms?LAYERS=x&BBOX=1,2,3,4&token=secret'),
    ).toBe('https://example.test/geoserver/wms')
  })

  it('never throws on malformed input', () => {
    expect(sanitizeTileUrl('not a url ?token=secret')).toBe('not a url')
  })
})

describe('TileDiagnostics', () => {
  it('does nothing when disabled', () => {
    const diagnostics = new TileDiagnostics({ enabled: false, maxEvents: 10 })
    diagnostics.record({ layer: 'ice', sourceKey: 's', status: 'started' })
    expect(diagnostics.snapshot().events).toEqual([])
    expect(diagnostics.snapshot().counters.started).toBe(0)
  })

  it('caps the ring buffer and tracks terminal counters', () => {
    const diagnostics = new TileDiagnostics({ enabled: true, maxEvents: 2 })
    diagnostics.record({ layer: 'ice', sourceKey: 's', status: 'started' })
    diagnostics.record({ layer: 'ice', sourceKey: 's', status: 'retry', attempts: 1 })
    diagnostics.record({ layer: 'ice', sourceKey: 's', status: 'loaded', attempts: 2 })
    const snapshot = diagnostics.snapshot()
    expect(snapshot.events).toHaveLength(2)
    expect(snapshot.events[1].status).toBe('loaded')
    expect(snapshot.counters.started).toBe(1)
    expect(snapshot.counters.settled).toBe(1)
    expect(snapshot.counters.retries).toBe(1)
  })

  it('computes stuck as started minus settled', () => {
    const diagnostics = new TileDiagnostics({ enabled: true })
    diagnostics.record({ layer: 'ice', sourceKey: 's', status: 'started' })
    diagnostics.record({ layer: 'ice', sourceKey: 's', status: 'started' })
    diagnostics.record({ layer: 'ice', sourceKey: 's', status: 'cancelled' })
    expect(diagnostics.snapshot().counters.stuck).toBe(1)
    diagnostics.record({ layer: 'ice', sourceKey: 's', status: 'failed' })
    expect(diagnostics.snapshot().counters.stuck).toBe(0)
  })

  it('reports queue and cache pipeline stats when registered', () => {
    const diagnostics = new TileDiagnostics({ enabled: true })
    diagnostics.registerPipeline({
      queue: { pending: 2, queued: 3, queuedHigh: 1, queuedNormal: 2 },
      cache: { size: 7, bytes: 1024 },
    })
    expect(diagnostics.snapshot().pipeline).toEqual({
      pending: 2,
      queued: 3,
      queuedHigh: 1,
      queuedNormal: 2,
      cacheSize: 7,
      cacheBytes: 1024,
    })
  })
})
