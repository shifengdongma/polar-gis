import { api } from './client'
import type {
  S57WaterwayCatalog,
  S57WaterwayDetail,
  S57WaterwaySearchRequest,
  S57WaterwaySearchResponse,
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
