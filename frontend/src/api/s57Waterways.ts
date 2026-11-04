import { api } from './client'
import type {
  S57WaterwayCatalog,
  S57WaterwayDetail,
  S57WaterwayPreviewRequest,
  S57WaterwayPreviewResponse,
  S57WaterwaySearchRequest,
  S57WaterwaySearchResponse,
  S57WaterwaySnapshotCreateRequest,
  S57WaterwaySnapshotList,
  S57WaterwaySnapshotManifest,
} from '../types/s57Waterways'

export async function fetchWaterwayCatalog(
  projectId: string,
  signal?: AbortSignal,
): Promise<S57WaterwayCatalog> {
  const response = await api.get<S57WaterwayCatalog>(
    `/projects/${projectId}/s57-waterways/catalog`,
    { signal, timeout: 30_000 },
  )
  return response.data
}

export async function searchWaterways(
  projectId: string,
  payload: S57WaterwaySearchRequest,
  signal?: AbortSignal,
): Promise<S57WaterwaySearchResponse> {
  const response = await api.post<S57WaterwaySearchResponse>(
    `/projects/${projectId}/s57-waterways/search`,
    payload,
    { signal, timeout: 30_000 },
  )
  return response.data
}

export async function fetchWaterwayDetail(
  projectId: string,
  featureId: string,
  signal?: AbortSignal,
): Promise<S57WaterwayDetail> {
  const response = await api.get<S57WaterwayDetail>(
    `/projects/${projectId}/s57-waterways/${encodeURIComponent(featureId)}`,
    { signal, timeout: 20_000 },
  )
  return response.data
}

export async function previewWaterways(
  projectId: string,
  payload: S57WaterwayPreviewRequest,
  signal?: AbortSignal,
): Promise<S57WaterwayPreviewResponse> {
  const response = await api.post<S57WaterwayPreviewResponse>(
    `/projects/${projectId}/s57-waterways/preview`,
    payload,
    { signal, timeout: 120_000 },
  )
  return response.data
}

export async function createWaterwaySnapshot(
  projectId: string,
  payload: S57WaterwaySnapshotCreateRequest,
  signal?: AbortSignal,
): Promise<S57WaterwaySnapshotManifest> {
  const response = await api.post<S57WaterwaySnapshotManifest>(
    `/projects/${projectId}/s57-waterways/snapshots`,
    payload,
    { signal, timeout: 180_000 },
  )
  return response.data
}

export async function listWaterwaySnapshots(
  projectId: string,
  signal?: AbortSignal,
): Promise<S57WaterwaySnapshotList> {
  const response = await api.get<S57WaterwaySnapshotList>(
    `/projects/${projectId}/s57-waterways/snapshots`,
    { signal, timeout: 30_000 },
  )
  return response.data
}

export async function fetchWaterwaySnapshot(
  projectId: string,
  snapshotId: string,
  signal?: AbortSignal,
): Promise<S57WaterwaySnapshotManifest> {
  const response = await api.get<S57WaterwaySnapshotManifest>(
    `/projects/${projectId}/s57-waterways/snapshots/${encodeURIComponent(snapshotId)}`,
    { signal, timeout: 30_000 },
  )
  return response.data
}

export async function downloadWaterwaySnapshot(
  projectId: string,
  snapshotId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await api.get<Blob>(
    `/projects/${projectId}/s57-waterways/snapshots/${encodeURIComponent(snapshotId)}/download`,
    { signal, responseType: 'blob', timeout: 120_000 },
  )
  return response.data
}
