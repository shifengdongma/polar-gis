/** Navigation environment/vessel API client. */
import { api } from './client'
import type {
  DataPolicy,
  DepthSafety,
  EnvironmentField,
  EnvironmentSample,
  EnvironmentSource,
  EvaluateRouteResult,
  FieldQueryResponse,
  PlanningCreatePayload,
  PlanningRoute,
  PlanningRun,
  RiskCell,
  RiskField,
  RiskGridCollection,
  VesselProfile,
} from '../types/navigation'

export async function fetchNavigationSources(signal?: AbortSignal): Promise<EnvironmentSource[]> {
  // The first call builds the provider index (and may scan ice metadata);
  // 30 s is too tight on a cold production data directory.
  const response = await api.get<EnvironmentSource[]>('/navigation/environment/sources', {
    signal,
    timeout: 120_000,
  })
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

// ── planning tasks ────────────────────────────────────────────────────

interface PaginatedPlans {
  items: PlanningRun[]
  page: number
  pageSize: number
  total: number
}

export async function createPlanningRun(payload: PlanningCreatePayload): Promise<PlanningRun> {
  const response = await api.post<PlanningRun>('/navigation/plans', payload, {
    timeout: 60_000,
  })
  return response.data
}

export async function fetchPlanningRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<PlanningRun[]> {
  const response = await api.get<PaginatedPlans>('/navigation/plans', {
    params: { projectId, pageSize: 100 },
    signal,
  })
  return response.data.items
}

export async function fetchPlanningRun(
  planId: string,
  signal?: AbortSignal,
): Promise<PlanningRun> {
  const response = await api.get<PlanningRun>(`/navigation/plans/${planId}`, { signal })
  return response.data
}

export async function fetchPlanningRoutes(
  planId: string,
  signal?: AbortSignal,
): Promise<PlanningRoute[]> {
  const response = await api.get<PlanningRoute[]>(`/navigation/plans/${planId}/routes`, {
    signal,
  })
  return response.data
}

export async function cancelPlanningRun(planId: string): Promise<PlanningRun> {
  const response = await api.post<PlanningRun>(`/navigation/plans/${planId}/cancel`)
  return response.data
}

export async function renamePlanningRun(
  planId: string,
  title: string,
): Promise<PlanningRun> {
  const response = await api.patch<PlanningRun>(`/navigation/plans/${planId}`, { title })
  return response.data
}

export async function deletePlanningRun(planId: string): Promise<void> {
  await api.delete(`/navigation/plans/${planId}`)
}

export async function fetchRiskGrid(
  planId: string,
  field: RiskField,
  bbox?: [number, number, number, number],
  stride = 1,
  signal?: AbortSignal,
): Promise<RiskGridCollection> {
  const response = await api.get<RiskGridCollection>(
    `/navigation/plans/${planId}/risk-grid`,
    {
      params: {
        field,
        stride,
        ...(bbox ? { bbox: bbox.map((value) => value.toFixed(5)).join(',') } : {}),
      },
      signal,
    },
  )
  return response.data
}

export async function fetchRiskCell(planId: string, cellId: string): Promise<RiskCell> {
  const response = await api.get<RiskCell>(
    `/navigation/plans/${planId}/risk-grid/${encodeURIComponent(cellId)}`,
  )
  return response.data
}

export async function evaluatePlanningRoute(
  planId: string,
  coordinates: [number, number][],
): Promise<EvaluateRouteResult> {
  const response = await api.post<EvaluateRouteResult>(
    `/navigation/plans/${planId}/evaluate-route`,
    { coordinates },
    { timeout: 30_000 },
  )
  return response.data
}

export async function evaluateRiskArea(payload: {
  projectId: string
  bbox: [number, number, number, number]
  departureTime: string
  vesselId: string
  dataPolicy: DataPolicy
}): Promise<PlanningRun> {
  const response = await api.post<PlanningRun>('/navigation/risk/evaluate', payload, {
    timeout: 60_000,
  })
  return response.data
}
