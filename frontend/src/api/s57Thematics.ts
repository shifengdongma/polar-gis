import { api } from './client'
import type {
  S57ThematicCatalog,
  S57ThematicExportCreateRequest,
  S57ThematicExportList,
  S57ThematicExportManifest,
} from '../types/s57Thematics'

export async function fetchThematicCatalog(
  projectId: string,
  signal?: AbortSignal,
): Promise<S57ThematicCatalog> {
  const response = await api.get<S57ThematicCatalog>(
    `/projects/${projectId}/s57-thematics/catalog`,
    { signal, timeout: 60_000 },
  )
  return response.data
}

export async function createThematicExport(
  projectId: string,
  payload: S57ThematicExportCreateRequest,
  signal?: AbortSignal,
): Promise<S57ThematicExportManifest> {
  const response = await api.post<S57ThematicExportManifest>(
    `/projects/${projectId}/s57-thematics/exports`,
    payload,
    { signal, timeout: 360_000 },
  )
  return response.data
}

export async function listThematicExports(
  projectId: string,
  signal?: AbortSignal,
): Promise<S57ThematicExportList> {
  const response = await api.get<S57ThematicExportList>(
    `/projects/${projectId}/s57-thematics/exports`,
    { signal, timeout: 30_000 },
  )
  return response.data
}

export async function fetchThematicExport(
  projectId: string,
  exportId: string,
  signal?: AbortSignal,
): Promise<S57ThematicExportManifest> {
  const response = await api.get<S57ThematicExportManifest>(
    `/projects/${projectId}/s57-thematics/exports/${encodeURIComponent(exportId)}`,
    { signal, timeout: 30_000 },
  )
  return response.data
}

export async function downloadThematicExport(
  projectId: string,
  exportId: string,
  options: { format?: 'geojson' | 'zip'; file?: string } = {},
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await api.get<Blob>(
    `/projects/${projectId}/s57-thematics/exports/${encodeURIComponent(exportId)}/download`,
    {
      signal,
      responseType: 'blob',
      timeout: 180_000,
      params: {
        format: options.format,
        file: options.file,
      },
    },
  )
  return response.data
}

export async function fetchThematicPreview(
  projectId: string,
  exportId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const response = await api.get<Record<string, unknown>>(
    `/projects/${projectId}/s57-thematics/exports/${encodeURIComponent(exportId)}/preview`,
    { signal, timeout: 60_000 },
  )
  return response.data
}
