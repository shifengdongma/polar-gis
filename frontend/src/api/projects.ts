import { api } from './client'
import type {
  BulkMapLayerResolveRequest,
  BulkMapLayerResolveResponse,
  MapConfig,
  MapLayerConfig,
} from '../types'

/** Fetch the full map config (datasets summary, project info, CRS). */
export async function getProjectMapConfig(projectId: string, signal?: AbortSignal): Promise<MapConfig> {
  const response = await api.get<MapConfig>(`/projects/${projectId}/map-config`, { signal })
  return response.data
}

/** Fetch lazily-loaded layers for a single dataset within a project. */
export async function getProjectDatasetMapLayers(
  projectId: string,
  datasetId: string,
  signal?: AbortSignal,
): Promise<MapLayerConfig[]> {
  const response = await api.get<MapLayerConfig[]>(
    `/projects/${projectId}/map-datasets/${datasetId}/layers`,
    { signal },
  )
  return response.data
}

/** Resolve S-57 layers across multiple datasets with profile filtering. */
export async function resolveProjectMapLayers(
  projectId: string,
  payload: BulkMapLayerResolveRequest,
  signal?: AbortSignal,
): Promise<BulkMapLayerResolveResponse> {
  const response = await api.post<BulkMapLayerResolveResponse>(
    `/projects/${projectId}/map-layers/resolve`,
    payload,
    { signal },
  )
  return response.data
}
