/** Navigation planning state: runs, candidates, risk grid, map picking. */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import {
  cancelPlanningRun,
  createPlanningRun,
  evaluatePlanningRoute,
  evaluateRiskArea,
  fetchPlanningRun,
  fetchPlanningRoutes,
  fetchPlanningRuns,
  fetchRiskCell,
  fetchRiskGrid,
  fetchVessels,
} from '../api/navigation'
import { apiErrorMessage } from '../api/client'
import type {
  DataPolicy,
  EvaluateRouteResult,
  NavigatePickMode,
  PlanningCreatePayload,
  PlanningPoint,
  PlanningRoute,
  PlanningRun,
  RiskCell,
  RiskField,
  RiskGridCollection,
  VesselProfile,
} from '../types/navigation'
import type { RouteDraft } from '../types'
import { useRoutesStore } from './routes'
import {
  planningSnapshotFromRoute,
  routeGeometryHash,
  routeToDraftPoints,
} from '../utils/routePlanning'

const POLL_INTERVAL_MS = 2000

export const useNavigationStore = defineStore('navigation', () => {
  const projectId = ref<string | null>(null)
  const vesselId = ref('xuelong2')
  const vessels = ref<VesselProfile[]>([])
  const vesselsLoading = ref(false)
  const runs = ref<PlanningRun[]>([])
  const currentRun = ref<PlanningRun | null>(null)
  const routes = ref<PlanningRoute[]>([])
  const selectedRouteId = ref<string | null>(null)
  const riskField = ref<RiskField>('combined')
  const riskGrid = ref<RiskGridCollection | null>(null)
  const riskCell = ref<RiskCell | null>(null)
  const loading = ref(false)
  const error = ref('')
  const pickMode = ref<NavigatePickMode>('idle')
  const riskInspect = ref(false)
  const pickedStart = ref<PlanningPoint | null>(null)
  const pickedGoal = ref<PlanningPoint | null>(null)
  const focusRouteRequest = ref<{ routeId: string; nonce: number } | null>(null)
  const snapshotTime = ref<string | null>(null)

  let pollTimer: number | undefined
  let pollToken = 0

  const selectedRoute = computed(
    () => routes.value.find((route) => route.routeId === selectedRouteId.value) ?? null,
  )
  const recommendedRoute = computed(
    () => routes.value.find((route) => route.recommended) ?? routes.value[0] ?? null,
  )
  const isActiveRun = computed(
    () => currentRun.value !== null && ['queued', 'running'].includes(currentRun.value.status),
  )
  const canCancel = computed(() => isActiveRun.value)
  const isSynthetic = computed(
    () =>
      currentRun.value?.dataPolicy === 'allow_synthetic_research' ||
      Object.values((currentRun.value?.environmentSnapshot?.fields ?? {}) as Record<string, unknown>).some(
        (field) =>
          typeof field === 'object' &&
          field !== null &&
          (field as Record<string, unknown>).quality === 'synthetic',
      ),
  )

  function setProject(id: string | null) {
    if (projectId.value === id) return
    stopPolling()
    projectId.value = id
    runs.value = []
    currentRun.value = null
    routes.value = []
    selectedRouteId.value = null
    riskGrid.value = null
    riskCell.value = null
    pickedStart.value = null
    pickedGoal.value = null
    pickMode.value = 'idle'
    riskInspect.value = false
  }

  async function loadVessels() {
    vesselsLoading.value = true
    try {
      vessels.value = await fetchVessels()
      if (!vessels.value.some((vessel) => vessel.id === vesselId.value)) {
        vesselId.value = vessels.value[0]?.id ?? 'xuelong2'
      }
    } catch (caught) {
      error.value = apiErrorMessage(caught, '船舶资料加载失败')
    } finally {
      vesselsLoading.value = false
    }
  }

  async function loadRuns() {
    if (!projectId.value) return
    try {
      runs.value = await fetchPlanningRuns(projectId.value)
    } catch (caught) {
      error.value = apiErrorMessage(caught, '规划任务列表加载失败')
    }
  }

  async function startPlan(payload: PlanningCreatePayload) {
    loading.value = true
    error.value = ''
    try {
      const run = await createPlanningRun(payload)
      currentRun.value = run
      runs.value = [run, ...runs.value.filter((item) => item.planId !== run.planId)]
      routes.value = []
      selectedRouteId.value = null
      riskGrid.value = null
      riskCell.value = null
      snapshotTime.value = payload.departureTime
      startPolling()
      return run
    } catch (caught) {
      error.value = apiErrorMessage(caught, '规划任务创建失败')
      throw caught
    } finally {
      loading.value = false
    }
  }

  function startPolling() {
    stopPolling()
    const token = ++pollToken
    const tick = async () => {
      if (token !== pollToken || !currentRun.value) return
      try {
        const run = await fetchPlanningRun(currentRun.value.planId)
        if (token !== pollToken) return
        currentRun.value = run
        updateRunInList(run)
        if (run.status === 'completed') {
          await loadRoutes(run.planId)
          const requested = run.environmentSnapshot?.requested_time ?? run.environmentSnapshot?.requestedTime
          snapshotTime.value = typeof requested === 'string' ? requested : snapshotTime.value
          stopPolling()
          return
        }
        if (['failed', 'cancelled'].includes(run.status)) {
          stopPolling()
          return
        }
        pollTimer = window.setTimeout(tick, POLL_INTERVAL_MS)
      } catch (caught) {
        if (token !== pollToken) return
        error.value = apiErrorMessage(caught, '规划状态查询失败')
        pollTimer = window.setTimeout(tick, POLL_INTERVAL_MS)
      }
    }
    pollTimer = window.setTimeout(tick, POLL_INTERVAL_MS)
  }

  function stopPolling() {
    pollToken += 1
    if (pollTimer !== undefined) {
      window.clearTimeout(pollTimer)
      pollTimer = undefined
    }
  }

  function updateRunInList(run: PlanningRun) {
    const index = runs.value.findIndex((item) => item.planId === run.planId)
    if (index >= 0) runs.value[index] = run
    else runs.value.unshift(run)
  }

  async function selectRun(planId: string) {
    stopPolling()
    loading.value = true
    error.value = ''
    try {
      const run = await fetchPlanningRun(planId)
      currentRun.value = run
      updateRunInList(run)
      routes.value = []
      selectedRouteId.value = null
      riskGrid.value = null
      riskCell.value = null
      const requested = run.environmentSnapshot?.requested_time ?? run.environmentSnapshot?.requestedTime
      snapshotTime.value = typeof requested === 'string' ? requested : null
      if (run.status === 'completed') {
        await loadRoutes(run.planId)
      } else if (['queued', 'running'].includes(run.status)) {
        startPolling()
      }
    } catch (caught) {
      error.value = apiErrorMessage(caught, '规划任务加载失败')
    } finally {
      loading.value = false
    }
  }

  async function loadRoutes(planId: string) {
    try {
      const loaded = await fetchPlanningRoutes(planId)
      routes.value = loaded
      const preferred =
        loaded.find((route) => route.recommended) ?? loaded[0] ?? null
      selectedRouteId.value = preferred?.routeId ?? null
    } catch (caught) {
      error.value = apiErrorMessage(caught, '候选航线加载失败')
    }
  }

  function selectRoute(routeId: string | null) {
    selectedRouteId.value = routeId
    if (routeId) requestFitRoute(routeId)
  }

  function requestFitRoute(routeId: string) {
    focusRouteRequest.value = { routeId, nonce: Date.now() }
  }

  async function cancelCurrent() {
    if (!currentRun.value) return
    try {
      const run = await cancelPlanningRun(currentRun.value.planId)
      currentRun.value = run
      updateRunInList(run)
      if (run.status === 'cancelled') stopPolling()
    } catch (caught) {
      ElMessage.error(apiErrorMessage(caught, '取消规划失败'))
    }
  }

  async function loadRiskGrid(field: RiskField = riskField.value, bbox?: [number, number, number, number]) {
    if (!currentRun.value) return
    try {
      riskField.value = field
      riskGrid.value = await fetchRiskGrid(currentRun.value.planId, field, bbox)
    } catch (caught) {
      error.value = apiErrorMessage(caught, '风险栅格加载失败')
    }
  }

  async function loadRiskCell(cellId: string) {
    if (!currentRun.value) return
    try {
      riskCell.value = await fetchRiskCell(currentRun.value.planId, cellId)
    } catch (caught) {
      error.value = apiErrorMessage(caught, '风险单元加载失败')
    }
  }

  async function startRiskEvaluation(payload: {
    projectId: string
    bbox: [number, number, number, number]
    departureTime: string
    vesselId: string
    dataPolicy: DataPolicy
  }) {
    loading.value = true
    error.value = ''
    try {
      const run = await evaluateRiskArea(payload)
      currentRun.value = run
      updateRunInList(run)
      routes.value = []
      selectedRouteId.value = null
      riskGrid.value = null
      riskCell.value = null
      snapshotTime.value = payload.departureTime
      startPolling()
      return run
    } catch (caught) {
      error.value = apiErrorMessage(caught, '区域风险评估创建失败')
      throw caught
    } finally {
      loading.value = false
    }
  }

  function setPickMode(mode: NavigatePickMode) {
    pickMode.value = mode
    if (mode !== 'idle') riskInspect.value = false
  }

  function setPickedPoint(point: PlanningPoint) {
    if (pickMode.value === 'start') pickedStart.value = point
    else if (pickMode.value === 'goal') pickedGoal.value = point
    pickMode.value = 'idle'
  }

  function setRiskInspect(value: boolean) {
    riskInspect.value = value
    if (value) pickMode.value = 'idle'
  }

  function adoptRoute(route: PlanningRoute): RouteDraft | null {
    const routesStore = useRoutesStore()
    const snapshot = planningSnapshotFromRoute(
      route,
      snapshotTime.value ?? new Date().toISOString(),
    )
    return routesStore.createRouteFromPoints(
      `规划 · ${route.label}`,
      routeToDraftPoints(route.coordinates),
      {
        origin: 'adopted',
        sourcePlanId: route.planId,
        sourceRouteId: route.routeId,
        planningSnapshot: snapshot,
      },
    )
  }

  async function refreshAdoptedMetrics(route: RouteDraft): Promise<EvaluateRouteResult> {
    const routesStore = useRoutesStore()
    if (!route.planningSnapshot) {
      throw new Error('当前草稿没有可重评的规划快照')
    }
    const coordinates = route.points
      .slice()
      .sort((a, b) => a.seq - b.seq)
      .map((point) => [point.lon, point.lat] as [number, number])
    const result = await evaluatePlanningRoute(route.planningSnapshot.planId, coordinates)
    if (!result.traversable || result.riskScore === null || result.energyMWh === null) {
      throw new Error(result.reason ?? '航线重评失败')
    }
    routesStore.updatePlanningSnapshot(route.id, {
      ...route.planningSnapshot,
      geometryHash: routeGeometryHash(route.points),
      risk: result.riskScore,
      energyMWh: result.energyMWh,
      timeHours: result.timeHours ?? route.planningSnapshot.timeHours,
      distanceKm: result.distanceKm ?? route.planningSnapshot.distanceKm,
    })
    return result
  }

  function setDataPolicy(policy: DataPolicy) {
    // The policy is part of the task form; this setter only keeps the last
    // selected value for the environment panel and new tasks.
    currentDataPolicy.value = policy
  }

  const currentDataPolicy = ref<DataPolicy>('real_only')

  function reset() {
    stopPolling()
    projectId.value = null
    runs.value = []
    currentRun.value = null
    routes.value = []
    selectedRouteId.value = null
    riskGrid.value = null
    riskCell.value = null
    pickMode.value = 'idle'
    riskInspect.value = false
    pickedStart.value = null
    pickedGoal.value = null
    error.value = ''
    snapshotTime.value = null
  }

  return {
    projectId,
    vesselId,
    vessels,
    vesselsLoading,
    runs,
    currentRun,
    routes,
    selectedRouteId,
    selectedRoute,
    recommendedRoute,
    riskField,
    riskGrid,
    riskCell,
    loading,
    error,
    pickMode,
    riskInspect,
    pickedStart,
    pickedGoal,
    focusRouteRequest,
    snapshotTime,
    isActiveRun,
    canCancel,
    isSynthetic,
    currentDataPolicy,
    setProject,
    setDataPolicy,
    loadVessels,
    loadRuns,
    startPlan,
    startRiskEvaluation,
    startPolling,
    stopPolling,
    selectRun,
    loadRoutes,
    selectRoute,
    requestFitRoute,
    cancelCurrent,
    loadRiskGrid,
    loadRiskCell,
    setPickMode,
    setPickedPoint,
    setRiskInspect,
    adoptRoute,
    refreshAdoptedMetrics,
    reset,
  }
})
