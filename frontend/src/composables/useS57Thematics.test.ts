import { describe, expect, it, vi } from 'vitest'
import { useS57Thematics } from './useS57Thematics'
import type {
  S57ThematicCatalog,
  S57ThematicExportManifest,
} from '../types/s57Thematics'

vi.mock('../api/s57Thematics', () => ({
  fetchThematicCatalog: vi.fn(),
  createThematicExport: vi.fn(),
  listThematicExports: vi.fn(),
  fetchThematicExport: vi.fn(),
  downloadThematicExport: vi.fn(),
  fetchThematicPreview: vi.fn(),
}))

import {
  createThematicExport,
  fetchThematicCatalog,
  listThematicExports,
} from '../api/s57Thematics'

const catalog: S57ThematicCatalog = {
  categories: [],
  classes: [
    {
      code: 'SOUNDG',
      nameZh: '水深点',
      category: 'depth',
      categoryNameZh: '水深与海底地形',
      description: '',
      caveats: [],
      defaultSelected: true,
      count: 12,
      countComplete: true,
      layerCount: 1,
      queryable: true,
      renderable: true,
      extractable: true,
      layers: [],
    },
  ],
  totalLayerCount: 1,
  extractableLayerCount: 1,
  featureCount: 12,
  countComplete: true,
  candidateLayerCount: 1,
  resolvedLayerCount: 1,
  cells: [],
  datasets: [],
  soundgDepth: { layers: [], depthPreserved: true, note: '' },
  warnings: [],
  semantics: [],
}

const manifest: S57ThematicExportManifest = {
  schemaVersion: '1.0',
  exportId: 'export-1',
  projectId: 'project-1',
  name: 'depth',
  createdAt: '2026-11-16T00:00:00Z',
  crs: 'EPSG:4326',
  categories: ['depth'],
  filters: {},
  bbox: null,
  featureCount: 12,
  featureCountUnit: 'S-57 features',
  complete: true,
  truncated: false,
  truncationReasons: [],
  objectClasses: [],
  classCounts: { SOUNDG: 12 },
  cellCounts: { NO1: 12 },
  files: [],
  sourceDatasets: [],
  sourceVersionIds: [],
  sourceContentHashes: {},
  sourceCells: ['NO1'],
  skippedLayers: [],
  depth: {},
  preview: null,
  semantics: [],
  warnings: [],
  stale: false,
}

describe('useS57Thematics', () => {
  it('loads the catalog and selects default extractable classes', async () => {
    vi.mocked(fetchThematicCatalog).mockResolvedValue(catalog)
    vi.mocked(listThematicExports).mockResolvedValue({ items: [], warnings: [] })
    const thematics = useS57Thematics({ getProjectId: () => 'project-1' })
    await thematics.loadCatalog()
    expect(thematics.catalog.value?.featureCount).toBe(12)
    expect(thematics.selectedClasses.value.has('SOUNDG')).toBe(true)
    expect(thematics.selectedFeatureCount.value).toBe(12)
  })

  it('creates an export with selected classes and source filters', async () => {
    vi.mocked(fetchThematicCatalog).mockResolvedValue(catalog)
    vi.mocked(createThematicExport).mockResolvedValue(manifest)
    const thematics = useS57Thematics({
      getProjectId: () => 'project-1',
      getViewportBbox: () => [10, 70, 20, 75],
    })
    await thematics.loadCatalog()
    thematics.setViewportOnly(true)
    thematics.exportName.value = 'depth snapshot'
    const created = await thematics.createExport()
    expect(created?.exportId).toBe('export-1')
    expect(createThematicExport).toHaveBeenCalledWith(
      'project-1',
      expect.objectContaining({
        name: 'depth snapshot',
        objectClasses: ['SOUNDG'],
        bbox: [10, 70, 20, 75],
      }),
      expect.any(AbortSignal),
    )
    expect(thematics.exports.value[0].exportId).toBe('export-1')
  })
})
