import { beforeEach, describe, expect, it, vi } from 'vitest'
import Feature from 'ol/Feature'
import LineString from 'ol/geom/LineString'
import { useS57Waterways } from './useS57Waterways'
import type {
  S57WaterwayCatalog,
  S57WaterwayDetail,
  S57WaterwaySearchItem,
  S57WaterwaySearchResponse,
  S57WaterwaySnapshotManifest,
} from '../types/s57Waterways'

vi.mock('../api/s57Waterways', () => ({
  fetchWaterwayCatalog: vi.fn(),
  searchWaterways: vi.fn(),
  fetchWaterwayDetail: vi.fn(),
  createWaterwaySnapshot: vi.fn(),
  listWaterwaySnapshots: vi.fn(),
  downloadWaterwaySnapshot: vi.fn(),
}))

import {
  createWaterwaySnapshot,
  fetchWaterwayCatalog,
  fetchWaterwayDetail,
  listWaterwaySnapshots,
  searchWaterways,
} from '../api/s57Waterways'

const catalog: S57WaterwayCatalog = {
  classes: [
    {
      code: 'FAIRWY',
      nameZh: '航道',
      group: 'fairway_route',
      groupNameZh: '航道与推荐路线',
      auxiliary: false,
      defaultSelected: true,
      description: '',
      count: 2,
      layerCount: 1,
      queryable: true,
      renderable: true,
      layers: [],
    },
    {
      code: 'DEPARE',
      nameZh: '水深区域',
      group: 'waterway_environment',
      groupNameZh: '航道环境辅助要素',
      auxiliary: true,
      defaultSelected: false,
      description: '',
      count: 1,
      layerCount: 1,
      queryable: true,
      renderable: true,
      layers: [],
    },
  ],
  total: 3,
  countComplete: true,
  truncated: false,
  warnings: [],
}

function item(id = 'id-1', name: string | null = 'Fairway A'): S57WaterwaySearchItem {
  return {
    id,
    layerId: 'layer-1',
    layerName: 'FAIRWY',
    layerCode: 's57_test_1_fairwy',
    datasetCode: 's57_test',
    datasetName: 'S-57 海图 TEST',
    versionNo: 1,
    sourceCell: 'TEST',
    objectClass: 'FAIRWY',
    objectNameZh: '航道',
    group: 'fairway_route',
    groupNameZh: '航道与推荐路线',
    auxiliary: false,
    name,
    nameField: name ? 'OBJNAM' : null,
    inform: null,
    status: null,
    geometryType: 'LineString',
    renderable: true,
    geometry: { type: 'LineString', coordinates: [[10, 70], [11, 71]] },
    bbox: [10, 70, 11, 71],
  }
}

function response(items: S57WaterwaySearchItem[], total = items.length): S57WaterwaySearchResponse {
  return {
    items,
    page: 1,
    pageSize: 20,
    total,
    truncatedLayers: false,
    warnings: [],
  }
}

function snapshotManifest(id = 'snap-1'): S57WaterwaySnapshotManifest {
  return {
    snapshotId: id,
    projectId: 'project-1',
    name: '成果 A',
    createdAt: '2026-11-04T10:00:00+00:00',
    crs: 'EPSG:4326',
    featureCount: 2,
    truncated: false,
    objectClasses: ['FAIRWY'],
    sourceDatasets: [],
    sourceVersionIds: ['version-1'],
    sourceContentHashes: {},
    filters: {},
    schemaVersion: '1.0',
    warnings: [],
    geojsonSha256: null,
    stale: false,
  }
}

function fakeMap() {
  const fit = vi.fn()
  const addLayer = vi.fn()
  const removeLayer = vi.fn()
  const map = {
    addLayer,
    removeLayer,
    getView: () => ({ fit }),
    forEachFeatureAtPixel: (_pixel: number[], callback: (feature: Feature) => boolean) => {
      const feature = new Feature({ geometry: new LineString([[0, 0], [1, 1]]) })
      feature.set('waterwayId', 'id-1')
      callback(feature)
    },
    getSize: () => [800, 600],
  }
  return { map, fit, addLayer, removeLayer }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useS57Waterways', () => {
  it('loads the catalog and selects default primary classes only', async () => {
    vi.mocked(fetchWaterwayCatalog).mockResolvedValue(catalog)
    const { map } = fakeMap()
    const waterways = useS57Waterways({
      getProjectId: () => 'project-1',
      getMap: () => map as never,
      getCrs: () => 'EPSG:3857',
    })
    await waterways.loadCatalog()
    expect([...waterways.selectedClasses.value]).toEqual(['FAIRWY'])
    expect(waterways.includeAuxiliary.value).toBe(false)
    expect(waterways.hasWaterwayData.value).toBe(true)
  })

  it('searches with selected classes and stores results/warnings', async () => {
    vi.mocked(searchWaterways).mockResolvedValue(response([item()]))
    const { map } = fakeMap()
    const waterways = useS57Waterways({
      getProjectId: () => 'project-1',
      getMap: () => map as never,
      getCrs: () => 'EPSG:3857',
    })
    waterways.toggleClass('FAIRWY', true)
    await waterways.runSearch(1)
    expect(searchWaterways).toHaveBeenCalledWith(
      'project-1',
      expect.objectContaining({ objectClasses: ['FAIRWY'], page: 1 }),
      expect.any(AbortSignal),
    )
    expect(waterways.results.value).toHaveLength(1)
    expect(waterways.total.value).toBe(1)
  })

  it('ignores a stale search response after a newer search', async () => {
    let resolveFirst!: (value: S57WaterwaySearchResponse) => void
    let resolveSecond!: (value: S57WaterwaySearchResponse) => void
    vi.mocked(searchWaterways)
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveFirst = resolve }),
      )
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveSecond = resolve }),
      )
    const { map } = fakeMap()
    const waterways = useS57Waterways({
      getProjectId: () => 'project-1',
      getMap: () => map as never,
      getCrs: () => 'EPSG:3857',
    })
    waterways.toggleClass('FAIRWY', true)
    const first = waterways.runSearch(1)
    const second = waterways.runSearch(1)
    resolveSecond(response([item('new', 'New')]))
    await second
    resolveFirst(response([item('old', 'Old')]))
    await first
    expect(waterways.results.value[0].id).toBe('new')
  })

  it('shows only selected features and clears them on deactivate', async () => {
    vi.mocked(fetchWaterwayDetail).mockResolvedValue({
      ...item(),
      properties: [],
      rawProperties: {},
      updatedAt: null,
    } as S57WaterwayDetail)
    const { map, addLayer } = fakeMap()
    const waterways = useS57Waterways({
      getProjectId: () => 'project-1',
      getMap: () => map as never,
      getCrs: () => 'EPSG:3857',
      getFitPadding: () => [80, 80, 80, 380],
    })
    waterways.attach()
    expect(addLayer).toHaveBeenCalledTimes(1)
    expect(waterways.showItem(item(), true)).toBe(true)
    expect(waterways.displayedCount.value).toBe(1)
    expect(waterways.isItemShown('id-1')).toBe(true)
    expect(waterways.locate(item())).toBe(true)
    waterways.setSelectionMode(true)
    expect(waterways.pickAtPixel([10, 10])).toBe(true)
    await Promise.resolve()
    expect(waterways.detail.value?.id).toBe('id-1')
    waterways.deactivate()
    expect(waterways.displayedCount.value).toBe(0)
    expect(waterways.detail.value).toBeNull()
    expect(waterways.selectionMode.value).toBe(false)
  })

  it('removes auxiliary classes when auxiliary mode is disabled', () => {
    const { map } = fakeMap()
    const waterways = useS57Waterways({
      getProjectId: () => 'project-1',
      getMap: () => map as never,
      getCrs: () => 'EPSG:3857',
    })
    waterways.catalog.value = catalog
    waterways.toggleClass('DEPARE', true)
    expect(waterways.includeAuxiliary.value).toBe(true)
    expect(waterways.selectedClasses.value.has('DEPARE')).toBe(true)
    waterways.setIncludeAuxiliary(false)
    expect(waterways.selectedClasses.value.has('DEPARE')).toBe(false)
    expect(waterways.includeAuxiliary.value).toBe(false)
  })

  it('creates a snapshot from current filters and lists saved results', async () => {
    const manifest = snapshotManifest()
    vi.mocked(createWaterwaySnapshot).mockResolvedValue(manifest)
    vi.mocked(listWaterwaySnapshots).mockResolvedValue({ items: [manifest], warnings: [] })
    const { map } = fakeMap()
    const waterways = useS57Waterways({
      getProjectId: () => 'project-1',
      getMap: () => map as never,
      getCrs: () => 'EPSG:3857',
      getViewportBbox: () => [170, 70, -170, 80],
    })
    waterways.setClasses(['FAIRWY'])
    waterways.keyword.value = 'Jinghang'
    waterways.viewportOnly.value = true

    const created = await waterways.createSnapshot({ name: '成果 A', maxFeatures: 500 })
    expect(created?.snapshotId).toBe('snap-1')
    expect(createWaterwaySnapshot).toHaveBeenCalledWith(
      'project-1',
      {
        name: '成果 A',
        keyword: 'Jinghang',
        objectClasses: ['FAIRWY'],
        includeAuxiliary: false,
        bbox: [170, 70, -170, 80],
        maxFeatures: 500,
      },
      expect.any(AbortSignal),
    )
    expect(waterways.snapshots.value).toHaveLength(1)

    await waterways.loadSnapshots()
    expect(listWaterwaySnapshots).toHaveBeenCalledWith('project-1', expect.any(AbortSignal))
    expect(waterways.snapshots.value[0].stale).toBe(false)
  })
})
