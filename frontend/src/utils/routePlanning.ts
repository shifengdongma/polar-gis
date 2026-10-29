/** Route adoption, geometry-hash staleness, and planning status formatting. */
import type { RouteDraft, RoutePoint } from '../types'
import type {
  PlanningRoute,
  PlanningRun,
  RoutePlanningSnapshot,
} from '../types/navigation'
import { createId, normalizeRoutePoints } from './mapRoute'

export function routeGeometryHash(points: Pick<RoutePoint, 'lon' | 'lat'>[]): string {
  const canonical = points
    .map((point) => `${point.lon.toFixed(7)},${point.lat.toFixed(7)}`)
    .join('|')
  let hash = 0x811c9dc5
  for (let index = 0; index < canonical.length; index += 1) {
    hash ^= canonical.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

export function routeToDraftPoints(coordinates: [number, number][]): RoutePoint[] {
  return normalizeRoutePoints(
    coordinates.map(([lon, lat]) => ({ id: createId(), seq: 0, lon, lat })),
  )
}

export function planningSnapshotFromRoute(
  route: PlanningRoute,
  snapshotTime: string,
): RoutePlanningSnapshot {
  return {
    planId: route.planId,
    routeId: route.routeId,
    geometryHash: routeGeometryHash(
      route.coordinates.map(([lon, lat]) => ({ lon, lat })),
    ),
    risk: route.riskScore,
    energyMWh: route.energyMWh,
    timeHours: route.timeHours,
    distanceKm: route.distanceKm,
    snapshotTime,
  }
}

export function routeMetricsStale(route: RouteDraft): boolean {
  const snapshot = route.planningSnapshot
  if (!snapshot) return false
  return routeGeometryHash(route.points) !== snapshot.geometryHash
}

export const planningStatusLabels: Record<string, string> = {
  queued: '排队中',
  running: '规划中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export const planningErrorLabels: Record<string, string> = {
  INPUT_INVALID: '输入参数不合法',
  ENVIRONMENT_DATA_MISSING: '环境数据缺失，无法完成可靠规划',
  NO_FEASIBLE_ROUTE: '没有可行航线',
  PLANNER_TIMEOUT: '规划超时',
  PLANNER_CANCELLED: '规划已取消',
  PLANNER_FAILED: '规划算法失败',
  PLANNER_LIMIT_EXCEEDED: '超出规划资源上限',
  PLANNER_RESULT_NOT_READY: '规划结果尚未生成',
  PLANNING_GRID_MISSING: '规划网格不可用',
  VESSEL_NOT_FOUND: '船舶资料不存在',
  PLAN_NOT_FOUND: '规划任务不存在',
  PLAN_NOT_CANCELLABLE: '当前任务不可取消',
}

export function planningErrorMessage(run: PlanningRun | null): string {
  if (!run) return ''
  if (run.errorCode) {
    const label = planningErrorLabels[run.errorCode] ?? run.errorCode
    // Keep the backend's actionable detail (timeout seconds, missing fields,
    // blocked reason) instead of replacing it with a generic label.
    if (!run.errorMessage || run.errorMessage === label) return label
    return run.errorMessage.includes(label)
      ? run.errorMessage
      : `${label}：${run.errorMessage}`
  }
  return run.errorMessage ?? ''
}

export function planningSnapshotTime(run: PlanningRun | null): string | null {
  if (!run) return null
  const value = run.environmentSnapshot?.requested_time ?? run.environmentSnapshot?.requestedTime
  return typeof value === 'string' ? value : null
}

export function isSyntheticRun(run: PlanningRun | null): boolean {
  if (!run) return false
  if (run.dataPolicy === 'allow_synthetic_research') return true
  const fields = run.environmentSnapshot?.fields
  if (!fields || typeof fields !== 'object') return false
  return Object.values(fields as Record<string, unknown>).some(
    (field) =>
      typeof field === 'object' &&
      field !== null &&
      (field as Record<string, unknown>).quality === 'synthetic',
  )
}

export function formatMwh(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} MWh` : '—'
}

export function formatHours(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} h` : '—'
}
