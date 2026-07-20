import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { useProjectsStore } from './projects'

describe('projects store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('loads published projects', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({
      data: {
        items: [
          {
            id: 'project-1',
            code: 'arctic',
            name: '北极项目',
            description: '',
            status: 'published',
            defaultCrs: 'EPSG:3413',
            initialExtent: null,
            publishedAt: null,
            createdAt: '2026-01-01T00:00:00Z',
            updatedAt: '2026-01-01T00:00:00Z',
            layerCount: 3,
          },
        ],
        page: 1,
        pageSize: 100,
        total: 1,
      },
    })
    const store = useProjectsStore()
    await store.loadProjects()
    expect(store.total).toBe(1)
    expect(store.projects[0].defaultCrs).toBe('EPSG:3413')
  })
})

