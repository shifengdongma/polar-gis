import { describe, it, expect, vi } from 'vitest'
import { resolveProjectMapLayers, getProjectDatasetMapLayers } from './projects'

vi.mock('./client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

import { api } from './client'

describe('projects API client', () => {
  it('resolveProjectMapLayers calls the correct URL with payload', async () => {
    const payload = {
      datasetIds: ['d1', 'd2'],
      profile: 'navigation_recommended' as const,
      includeMetadata: false,
    }
    const signal = new AbortController().signal
    const mockResponse = { data: { datasets: [], summary: { datasetCount: 0 } } }
    ;(api.post as ReturnType<typeof vi.fn>).mockResolvedValue(mockResponse)

    await resolveProjectMapLayers('p1', payload, signal)

    expect(api.post).toHaveBeenCalledWith(
      '/projects/p1/map-layers/resolve',
      payload,
      { signal },
    )
  })

  it('getProjectDatasetMapLayers calls the correct URL', async () => {
    const signal = new AbortController().signal
    const mockResponse = { data: [] }
    ;(api.get as ReturnType<typeof vi.fn>).mockResolvedValue(mockResponse)

    await getProjectDatasetMapLayers('p1', 'd1', signal)

    expect(api.get).toHaveBeenCalledWith(
      '/projects/p1/map-datasets/d1/layers',
      { signal },
    )
  })

  it('getProjectDatasetMapLayers works without signal', async () => {
    const mockResponse = { data: [] }
    ;(api.get as ReturnType<typeof vi.fn>).mockResolvedValue(mockResponse)

    await getProjectDatasetMapLayers('p1', 'd1')

    expect(api.get).toHaveBeenCalledWith(
      '/projects/p1/map-datasets/d1/layers',
      { signal: undefined },
    )
  })
})
