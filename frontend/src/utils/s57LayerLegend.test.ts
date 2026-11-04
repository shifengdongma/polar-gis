import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MapLayerConfig } from '../types'

vi.mock('../api/client', () => ({
  api: { get: vi.fn() },
}))

import { api } from '../api/client'
import {
  clearLayerLegendCache,
  fetchLayerLegend,
  legendCacheKey,
} from './s57LayerLegend'

const layer = {
  id: 'layer-1',
  styleName: 's57_navigation',
  objectClass: 'FAIRWY',
} as MapLayerConfig

const legend = {
  url: '/geoserver/polar_gis/wms?request=GetLegendGraphic',
  objectClass: 'FAIRWY',
  geometryType: 'MultiLineString',
  fallback: null,
}

beforeEach(() => {
  vi.resetAllMocks()
  clearLayerLegendCache()
})

describe('s57LayerLegend cache', () => {
  it('requests one layer only once and keys by style/object class', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: legend } as never)
    const first = await fetchLayerLegend(layer)
    const second = await fetchLayerLegend(layer)
    expect(first).toBe(second)
    expect(api.get).toHaveBeenCalledTimes(1)
    expect(String(vi.mocked(api.get).mock.calls[0]![0])).toBe('/layers/layer-1/legend')
    expect(legendCacheKey(layer)).toBe('layer-1:s57_navigation:FAIRWY')

    await fetchLayerLegend({ ...layer, styleName: 's57_depth' })
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('drops the failed entry so a retry can request again', async () => {
    vi.mocked(api.get)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ data: legend } as never)
    await expect(fetchLayerLegend(layer)).rejects.toThrow('network')
    await expect(fetchLayerLegend(layer)).resolves.toMatchObject({ url: legend.url })
    expect(api.get).toHaveBeenCalledTimes(2)
  })
})
