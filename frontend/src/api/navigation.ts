/** Navigation environment/vessel API client. */
import { api } from './client'
import type {
  DataPolicy,
  DepthSafety,
  EnvironmentField,
  EnvironmentSample,
  EnvironmentSource,
  FieldQueryResponse,
  VesselProfile,
} from '../types/navigation'

export async function fetchNavigationSources(signal?: AbortSignal): Promise<EnvironmentSource[]> {
  const response = await api.get<EnvironmentSource[]>('/navigation/environment/sources', { signal })
  return response.data
}

export async function queryEnvironment(
  payload: {
    longitude: number
    latitude: number
    time: string
    fields: EnvironmentField[]
    dataPolicy?: DataPolicy
  },
  signal?: AbortSignal,
): Promise<EnvironmentSample> {
  const response = await api.post<EnvironmentSample>('/navigation/environment/query', payload, {
    signal,
    timeout: 60_000,
  })
  return response.data
}

export async function fetchEnvironmentField(
  payload: {
    field: 'wind' | 'current' | 'wave'
    bbox: [number, number, number, number]
    time: string
    zoom: number
    maxPoints: number
    dataPolicy?: DataPolicy
  },
  signal?: AbortSignal,
): Promise<FieldQueryResponse> {
  const response = await api.post<FieldQueryResponse>('/navigation/environment/field', payload, {
    signal,
    timeout: 60_000,
  })
  return response.data
}

export async function fetchVessels(signal?: AbortSignal): Promise<VesselProfile[]> {
  const response = await api.get<VesselProfile[]>('/navigation/vessels', { signal })
  return response.data
}

export async function fetchVessel(
  vesselId: string,
  signal?: AbortSignal,
): Promise<VesselProfile> {
  const response = await api.get<VesselProfile>(`/navigation/vessels/${vesselId}`, { signal })
  return response.data
}

export async function fetchDepthSafety(
  vesselId: string,
  depthM: number,
  signal?: AbortSignal,
): Promise<DepthSafety> {
  const response = await api.get<DepthSafety>(`/navigation/vessels/${vesselId}/depth-safety`, {
    params: { depthM },
    signal,
  })
  return response.data
}
