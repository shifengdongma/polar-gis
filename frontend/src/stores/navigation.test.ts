import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useNavigationStore } from './navigation'
import { useRoutesStore } from './routes'
import type { PlanningRoute } from '../types/navigation'
import { routeMetricsStale } from '../utils/routePlanning'

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
  riskScore: 0.2,
  riskComponents: { ice: 0.3, depth: 0.1, fog: null, wind: 0.1, wave: 0.05 },
  energyMWh: 10,
  timeHours: 4,
  distanceKm: 120,
  sourceQuality: 'synthetic',
  algorithmVersion: 'test',
  createdAt: '2025-02-15T12:00:00Z',
}

describe('navigation store adoption and pick modes', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('adopts a recommended route as an editable draft with a snapshot', () => {
    const routesStore = useRoutesStore()
    const navigation = useNavigationStore()
    routesStore.ensureLoaded('project-1')
    navigation.setProject('project-1')
    navigation.snapshotTime = '2025-02-15T12:00:00Z'
    const draft = navigation.adoptRoute(route)
    expect(draft).not.toBeNull()
    expect(draft!.origin).toBe('adopted')
    expect(draft!.sourcePlanId).toBe('plan-1')
    expect(draft!.sourceRouteId).toBe('route-1')
    expect(draft!.points).toHaveLength(3)
    expect(draft!.planningSnapshot?.risk).toBe(0.2)
    expect(routeMetricsStale(draft!)).toBe(false)
    routesStore.updateRoutePoint(draft!.id, draft!.points[1].id, 121.5, 76)
    expect(routeMetricsStale(draft!)).toBe(true)
  })

  it('stores map-picked start/goal independent of the route panel', () => {
    const navigation = useNavigationStore()
    navigation.setPickMode('start')
    expect(navigation.pickMode).toBe('start')
    navigation.setPickedPoint({ longitude: 120, latitude: 75 })
    expect(navigation.pickedStart).toEqual({ longitude: 120, latitude: 75 })
    expect(navigation.pickMode).toBe('idle')
    navigation.setPickMode('goal')
    navigation.setPickedPoint({ longitude: 122, latitude: 77 })
    expect(navigation.pickedGoal).toEqual({ longitude: 122, latitude: 77 })
  })

  it('risk inspection and pick modes are mutually exclusive', () => {
    const navigation = useNavigationStore()
    navigation.setPickMode('start')
    navigation.setRiskInspect(true)
    expect(navigation.riskInspect).toBe(true)
    expect(navigation.pickMode).toBe('idle')
    navigation.setPickMode('goal')
    expect(navigation.riskInspect).toBe(false)
  })

  it('setProject clears plan-specific state', () => {
    const navigation = useNavigationStore()
    navigation.setProject('p1')
    navigation.riskInspect = true
    navigation.setProject('p2')
    expect(navigation.projectId).toBe('p2')
    expect(navigation.currentRun).toBeNull()
    expect(navigation.routes).toHaveLength(0)
    expect(navigation.riskInspect).toBe(false)
  })
})
