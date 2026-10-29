import { describe, expect, it } from 'vitest'
import type { PlanningRoute, PlanningRun } from '../types/navigation'
import type { RouteDraft } from '../types'
import {
  formatHours,
  formatMwh,
  planningErrorMessage,
  planningSnapshotFromRoute,
  routeGeometryHash,
  routeMetricsStale,
  routeToDraftPoints,
} from './routePlanning'

const route: PlanningRoute = {
  routeId: 'route-1',
  planId: 'plan-1',
  routeIndex: 0,
  label: '最低风险',
  recommended: true,
  coordinates: [
    [120, 75],
    [121, 76],
    [122, 77],
  ],
  riskScore: 0.21,
  riskComponents: { ice: 0.3, depth: 0.1, fog: null, wind: 0.1, wave: 0.05 },
  energyMWh: 12.5,
  timeHours: 4.2,
  distanceKm: 140,
  sourceQuality: 'synthetic',
  algorithmVersion: 'dnsga3-v3-port-1',
  createdAt: '2025-02-15T12:00:00Z',
}

describe('routePlanning adoption/staleness', () => {
  it('geometry hash is stable and changes when a point moves', () => {
    const first = routeGeometryHash([
      { lon: 120, lat: 75 },
      { lon: 121, lat: 76 },
    ])
    const second = routeGeometryHash([
      { lon: 120, lat: 75 },
      { lon: 121, lat: 76 },
    ])
    const moved = routeGeometryHash([
      { lon: 120, lat: 75 },
      { lon: 121.0001, lat: 76 },
    ])
    expect(first).toBe(second)
    expect(moved).not.toBe(first)
  })

  it('adoption converts coordinates to sequential draft points', () => {
    const points = routeToDraftPoints(route.coordinates)
    expect(points).toHaveLength(3)
    expect(points.map((point) => point.seq)).toEqual([1, 2, 3])
    expect(points[0].lon).toBe(120)
  })

  it('snapshot becomes stale after editing draft geometry', () => {
    const snapshot = planningSnapshotFromRoute(route, '2025-02-15T12:00:00Z')
    const draft: RouteDraft = {
      id: 'draft-1',
      projectId: 'project-1',
      name: '规划 · 最低风险',
      points: routeToDraftPoints(route.coordinates),
      visible: true,
      createdAt: '2025-02-15T12:00:00Z',
      updatedAt: '2025-02-15T12:00:00Z',
      origin: 'adopted',
      sourcePlanId: snapshot.planId,
      sourceRouteId: snapshot.routeId,
      planningSnapshot: snapshot,
    }
    expect(routeMetricsStale(draft)).toBe(false)
    draft.points[1] = { ...draft.points[1], lon: 121.5 }
    expect(routeMetricsStale(draft)).toBe(true)
  })

  it('formats negative/unknown metrics without inventing values', () => {
    expect(formatMwh(null)).toBe('—')
    expect(formatHours(undefined)).toBe('—')
    expect(formatMwh(12.345)).toBe('12.35 MWh')
    const run = {
      planId: 'plan-1',
      projectId: 'project-1',
      vesselId: 'xuelong2',
      mode: 'plan',
      status: 'failed',
      stage: 'failed',
      progress: 100,
      dataPolicy: 'real_only',
      riskModelVersion: 'real_v1',
      algorithmVersion: 'test',
      errorCode: 'ENVIRONMENT_DATA_MISSING',
      errorMessage: null,
      resultSummary: {},
      environmentSnapshot: {},
      cancelRequested: false,
      queuedAt: '2025-02-15T12:00:00Z',
      startedAt: null,
      finishedAt: null,
      createdAt: '2025-02-15T12:00:00Z',
    } satisfies PlanningRun
    expect(planningErrorMessage(run)).toBe('环境数据缺失，无法完成可靠规划')
  })
})
