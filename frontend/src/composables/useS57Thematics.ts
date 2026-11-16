/**
 * S-57 depth/hazard thematic export state.
 *
 * The composable only calls the project-scoped thematic API. It never reads
 * `.000` files or PostGIS directly, and it does not touch the waterway
 * snapshot or the map overlay stores.
 */
import { computed, ref, shallowRef } from 'vue'
import { apiErrorMessage } from '../api/client'
import {
  createThematicExport,
  downloadThematicExport,
  fetchThematicCatalog,
  fetchThematicPreview,
  listThematicExports,
} from '../api/s57Thematics'
import type {
  S57ThematicCatalog,
  S57ThematicClass,
  S57ThematicExportManifest,
} from '../types/s57Thematics'

export interface S57ThematicsOptions {
  getProjectId: () => string
  getViewportBbox?: () => [number, number, number, number] | null
}

export function useS57Thematics(options: S57ThematicsOptions) {
  const catalog = shallowRef<S57ThematicCatalog | null>(null)
  const catalogLoading = ref(false)
  const catalogError = ref('')

  const exports = shallowRef<S57ThematicExportManifest[]>([])
  const exportsLoading = ref(false)
  const exportsError = ref('')

  const selectedClasses = ref<Set<string>>(new Set())
  const selectedCells = ref<Set<string>>(new Set())
  const selectedDatasets = ref<Set<string>>(new Set())
  const viewportOnly = ref(false)
  const exportName = ref('')
  const maxFeaturesPerClass = ref<number | null>(null)
  const creating = ref(false)
  const createError = ref('')
  const downloading = ref(false)
  const downloadError = ref('')
  const previewLoading = ref(false)
  const previewError = ref('')

  let catalogController: AbortController | null = null
  let exportsController: AbortController | null = null
  let createController: AbortController | null = null
  let downloadController: AbortController | null = null
  let previewController: AbortController | null = null

  const classes = computed<S57ThematicClass[]>(() => catalog.value?.classes ?? [])
  const selectedClassList = computed(() =>
    classes.value.filter((item) => selectedClasses.value.has(item.code)),
  )
  const selectedLayerCount = computed(() =>
    selectedClassList.value.reduce((sum, item) => sum + item.layerCount, 0),
  )
  const selectedExtractableLayerCount = computed(() =>
    selectedClassList.value.reduce(
      (sum, item) =>
        sum + item.layers.filter((layer) => layer.extractable).length,
      0,
    ),
  )
  const selectedFeatureCount = computed(() =>
    selectedClassList.value.reduce((sum, item) => sum + item.count, 0),
  )
  const selectedCountComplete = computed(() =>
    selectedClassList.value.every((item) => item.countComplete),
  )
  const hasCatalogData = computed(() =>
    Boolean(catalog.value?.classes.some((item) => item.layerCount > 0)),
  )

  function defaultClasses(data: S57ThematicCatalog): Set<string> {
    return new Set(
      data.classes
        .filter((item) => item.defaultSelected && item.extractable)
        .map((item) => item.code),
    )
  }

  async function loadCatalog() {
    catalogController?.abort()
    catalogController = new AbortController()
    catalogLoading.value = true
    catalogError.value = ''
    try {
      const data = await fetchThematicCatalog(
        options.getProjectId(),
        catalogController.signal,
      )
      catalog.value = data
      if (selectedClasses.value.size === 0) {
        selectedClasses.value = defaultClasses(data)
      } else {
        const available = new Set(data.classes.map((item) => item.code))
        selectedClasses.value = new Set(
          [...selectedClasses.value].filter((code) => available.has(code)),
        )
      }
    } catch (caught) {
      if (!catalogController.signal.aborted) {
        catalogError.value = apiErrorMessage(caught, 'S-57 专题目录加载失败')
      }
    } finally {
      if (!catalogController.signal.aborted) catalogLoading.value = false
    }
  }

  function toggleClass(code: string, checked: boolean) {
    const next = new Set(selectedClasses.value)
    if (checked) next.add(code)
    else next.delete(code)
    selectedClasses.value = next
  }

  function setViewportOnly(value: boolean) {
    viewportOnly.value = value
  }

  function toggleCell(cell: string, checked: boolean) {
    const next = new Set(selectedCells.value)
    if (checked) next.add(cell)
    else next.delete(cell)
    selectedCells.value = next
  }

  function toggleDataset(datasetId: string, checked: boolean) {
    const next = new Set(selectedDatasets.value)
    if (checked) next.add(datasetId)
    else next.delete(datasetId)
    selectedDatasets.value = next
  }

  async function loadExports() {
    exportsController?.abort()
    exportsController = new AbortController()
    exportsLoading.value = true
    exportsError.value = ''
    try {
      const data = await listThematicExports(
        options.getProjectId(),
        exportsController.signal,
      )
      exports.value = data.items
    } catch (caught) {
      if (!exportsController.signal.aborted) {
        exportsError.value = apiErrorMessage(caught, '已保存专题成果加载失败')
      }
    } finally {
      if (!exportsController.signal.aborted) exportsLoading.value = false
    }
  }

  async function createExport(): Promise<S57ThematicExportManifest | null> {
    if (selectedClasses.value.size === 0) {
      createError.value = '请至少选择一个对象类'
      return null
    }
    let bbox: [number, number, number, number] | null = null
    if (viewportOnly.value) {
      bbox = options.getViewportBbox?.() ?? null
      if (!bbox) {
        createError.value = '当前视口暂不可用，请关闭“当前视口”后提取'
        return null
      }
    }
    createController?.abort()
    createController = new AbortController()
    creating.value = true
    createError.value = ''
    try {
      const manifest = await createThematicExport(
        options.getProjectId(),
        {
          name: exportName.value.trim() || null,
          objectClasses: [...selectedClasses.value],
          bbox,
          sourceCells: [...selectedCells.value],
          datasetIds: [...selectedDatasets.value],
          maxFeaturesPerClass: maxFeaturesPerClass.value,
        },
        createController.signal,
      )
      exports.value = [
        manifest,
        ...exports.value.filter((item) => item.exportId !== manifest.exportId),
      ]
      return manifest
    } catch (caught) {
      if (!createController.signal.aborted) {
        createError.value = apiErrorMessage(caught, 'S-57 专题提取失败')
      }
      return null
    } finally {
      if (!createController.signal.aborted) creating.value = false
    }
  }

  function exportFileName(manifest: S57ThematicExportManifest): string {
    const base = (manifest.name || manifest.exportId)
      .replace(/[\\/:*?"<>|]/g, '_')
      .trim()
    const safe = base || 's57-thematic'
    return `${safe}.${manifest.files.length > 1 ? 'zip' : 'geojson'}`
  }

  async function downloadExport(manifest: S57ThematicExportManifest) {
    downloadController?.abort()
    downloadController = new AbortController()
    downloading.value = true
    downloadError.value = ''
    try {
      const blob = await downloadThematicExport(
        options.getProjectId(),
        manifest.exportId,
        {},
        downloadController.signal,
      )
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = exportFileName(manifest)
      link.click()
      URL.revokeObjectURL(url)
    } catch (caught) {
      if (!downloadController.signal.aborted) {
        downloadError.value = apiErrorMessage(caught, '专题成果下载失败')
      }
    } finally {
      if (!downloadController.signal.aborted) downloading.value = false
    }
  }

  async function loadPreview(
    manifest: S57ThematicExportManifest,
  ): Promise<Record<string, unknown> | null> {
    previewController?.abort()
    previewController = new AbortController()
    previewLoading.value = true
    previewError.value = ''
    try {
      return await fetchThematicPreview(
        options.getProjectId(),
        manifest.exportId,
        previewController.signal,
      )
    } catch (caught) {
      if (!previewController.signal.aborted) {
        previewError.value = apiErrorMessage(caught, '专题样例预览加载失败')
      }
      return null
    } finally {
      if (!previewController.signal.aborted) previewLoading.value = false
    }
  }

  function dispose() {
    catalogController?.abort()
    exportsController?.abort()
    createController?.abort()
    downloadController?.abort()
    previewController?.abort()
    catalogController = null
    exportsController = null
    createController = null
    downloadController = null
    previewController = null
  }

  return {
    catalog,
    catalogLoading,
    catalogError,
    exports,
    exportsLoading,
    exportsError,
    selectedClasses,
    selectedCells,
    selectedDatasets,
    viewportOnly,
    exportName,
    maxFeaturesPerClass,
    creating,
    createError,
    downloading,
    downloadError,
    previewLoading,
    previewError,
    classes,
    selectedClassList,
    selectedLayerCount,
    selectedExtractableLayerCount,
    selectedFeatureCount,
    selectedCountComplete,
    hasCatalogData,
    loadCatalog,
    toggleClass,
    setViewportOnly,
    toggleCell,
    toggleDataset,
    loadExports,
    createExport,
    downloadExport,
    loadPreview,
    dispose,
  }
}

export type S57ThematicsApi = ReturnType<typeof useS57Thematics>
