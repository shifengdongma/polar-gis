/**
 * 航路规划模拟 — Pinia Setup Store。
 *
 * 业务坐标唯一真值 = WGS84 经纬度 [lon, lat];OpenLayers Feature 仅为渲染结果。
 * 本阶段以 localStorage 持久化草稿(按 projectId 隔离),未来替换为后端 Route API 时
 * 只需更换 loadLocalRoutes / saveLocalRoutes 两个私有入口,Store 接口保持不变。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { defineStore } from 'pinia'
import type { RouteDraft, RouteInteractionMode, RoutePoint } from '../types'
import {
  ROUTE_MIN_POINTS,
  createId,
  normalizeRoutePoints,
  validateRouteCoordinate,
} from '../utils/mapRoute'

export const ROUTE_STORAGE_VERSION = 1
export const ROUTE_STORAGE_PREFIX = 'polar-gis:route-drafts'

export function routeStorageKey(projectId: string): string {
  return `${ROUTE_STORAGE_PREFIX}:${projectId}:v${ROUTE_STORAGE_VERSION}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** 逐点容错:非对象丢弃、非法经纬度丢弃、缺 id 补齐、seq 重排 */
function coercePoints(rawPoints: unknown): RoutePoint[] {
  if (!Array.isArray(rawPoints)) return []
  const points: RoutePoint[] = []
  for (const raw of rawPoints) {
    if (!isRecord(raw)) continue
    const lon = typeof raw.lon === 'number' ? raw.lon : NaN
    const lat = typeof raw.lat === 'number' ? raw.lat : NaN
    const check = validateRouteCoordinate(lon, lat)
    if (!check.ok) continue
    points.push({ id: typeof raw.id === 'string' && raw.id ? raw.id : createId(), seq: 0, lon, lat })
  }
  return normalizeRoutePoints(points)
}

function coerceRoute(
  raw: unknown,
  projectId: string,
  index: number,
  seenIds: Set<string>,
  now: string,
): RouteDraft | null {
  if (!isRecord(raw)) return null
  const points = coercePoints(raw.points)
  if (points.length < ROUTE_MIN_POINTS) return null
  if (typeof raw.id === 'string' && raw.id) {
    if (seenIds.has(raw.id)) return null // 重复 id 去重,保留首个
  }
  const id = typeof raw.id === 'string' && raw.id ? raw.id : createId()
  seenIds.add(id)
  return {
    id,
    projectId,
    name: typeof raw.name === 'string' && raw.name.trim() ? raw.name.trim() : `航路 ${index + 1}`,
    points,
    visible: typeof raw.visible === 'boolean' ? raw.visible : true,
    createdAt: typeof raw.createdAt === 'string' ? raw.createdAt : now,
    updatedAt: typeof raw.updatedAt === 'string' ? raw.updatedAt : now,
  }
}

/**
 * 容错解析 localStorage 草稿。任何损坏(JSON 错误 / 旧版本结构 / 非法字段)
 * 都只丢弃对应部分,绝不抛出,保证地图工作台正常加载。
 */
export function parseStoredRoutes(raw: string | null, projectId: string): RouteDraft[] {
  if (!raw) return []
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    console.warn('[routes] 本地航路草稿 JSON 解析失败,已忽略损坏数据')
    return []
  }
  // 兼容两种外形:{ version, routes } 或裸数组
  const list: unknown[] = Array.isArray(parsed)
    ? parsed
    : isRecord(parsed) && Array.isArray(parsed.routes)
      ? parsed.routes
      : []
  const routes: RouteDraft[] = []
  const seenIds = new Set<string>()
  const now = new Date().toISOString()
  for (let i = 0; i < list.length; i++) {
    const route = coerceRoute(list[i], projectId, i, seenIds, now)
    if (route) routes.push(route)
  }
  return routes
}

export function serializeRoutes(projectId: string, routes: RouteDraft[]): string {
  return JSON.stringify({ version: ROUTE_STORAGE_VERSION, projectId, routes })
}

export const useRoutesStore = defineStore('routes', () => {
  const routes = ref<RouteDraft[]>([])
  const activeRouteId = ref<string | null>(null)
  const interactionMode = ref<RouteInteractionMode>('idle')
  /** 单调递增的通知计数:地图同步 watch 它,避免 deep watch 大数组 */
  const revision = ref(0)
  const loadedProjectId = ref<string | null>(null)
  const storageWarned = ref(false)

  const visibleRouteIds = computed(() => routes.value.filter((route) => route.visible).map((route) => route.id))
  const activeRoute = computed(() => routes.value.find((route) => route.id === activeRouteId.value) ?? null)
  const canEditPoints = computed(() => (activeRoute.value?.points.length ?? 0) > ROUTE_MIN_POINTS)

  /** 所有数据变更动作的公共出口:通知地图同步 + 持久化 */
  function touch() {
    revision.value += 1
    saveLocalRoutes()
  }

  function nextRouteName(): string {
    const used = new Set(routes.value.map((route) => route.name))
    for (let n = 1; ; n++) {
      const candidate = `航路 ${n}`
      if (!used.has(candidate)) return candidate
    }
  }

  function ensureLoaded(projectId: string) {
    if (loadedProjectId.value === projectId) return
    loadedProjectId.value = projectId
    activeRouteId.value = null
    interactionMode.value = 'idle'
    routes.value = loadLocalRoutes(projectId)
    revision.value += 1
  }

  function loadLocalRoutes(projectId: string): RouteDraft[] {
    let raw: string | null = null
    try {
      raw = localStorage.getItem(routeStorageKey(projectId))
    } catch {
      return [] // 隐私模式 / 存储被禁用 → 空列表
    }
    return parseStoredRoutes(raw, projectId)
  }

  function saveLocalRoutes() {
    if (!loadedProjectId.value) return
    // 少于 2 点的草稿是非法几何,不落盘
    const storable = routes.value.filter((route) => route.points.length >= ROUTE_MIN_POINTS)
    try {
      localStorage.setItem(routeStorageKey(loadedProjectId.value), serializeRoutes(loadedProjectId.value, storable))
    } catch (error) {
      if (!storageWarned.value) {
        storageWarned.value = true
        console.warn('[routes] 本地航路草稿保存失败:', error)
        ElMessage.warning('航路草稿保存失败(浏览器存储不可用),本次修改仅保留在当前页面')
      }
    }
  }

  function createRoute(name?: string, points?: RoutePoint[]): RouteDraft | null {
    if (!loadedProjectId.value) return null
    const normalized = points ? normalizeRoutePoints(points) : []
    const now = new Date().toISOString()
    const route: RouteDraft = {
      id: createId(),
      projectId: loadedProjectId.value,
      name: (name ?? '').trim() || nextRouteName(),
      points: normalized,
      visible: true,
      createdAt: now,
      updatedAt: now,
    }
    routes.value.push(route)
    activeRouteId.value = route.id
    interactionMode.value = 'idle'
    touch()
    return route
  }

  function createRouteFromPoints(name: string | undefined, points: RoutePoint[]): RouteDraft | null {
    const normalized = normalizeRoutePoints(points)
    if (normalized.length < ROUTE_MIN_POINTS) return null
    return createRoute(name, normalized)
  }

  function deleteRoute(routeId: string) {
    const index = routes.value.findIndex((route) => route.id === routeId)
    if (index < 0) return
    routes.value.splice(index, 1)
    if (activeRouteId.value === routeId) activeRouteId.value = null
    interactionMode.value = 'idle'
    touch()
  }

  function setActiveRoute(routeId: string | null) {
    if (routeId !== null && !routes.value.some((route) => route.id === routeId)) return
    activeRouteId.value = routeId
    interactionMode.value = 'idle'
    touch() // 样式即时刷新;activeRouteId 不持久化,代价是一次写盘,可忽略
  }

  function updateRouteName(routeId: string, name: string): { ok: true } | { ok: false; error: string } {
    const trimmed = name.trim()
    if (!trimmed) return { ok: false, error: '航路名称不能为空' }
    const route = routes.value.find((item) => item.id === routeId)
    if (!route) return { ok: false, error: '航路不存在' }
    route.name = trimmed
    route.updatedAt = new Date().toISOString()
    touch()
    return { ok: true }
  }

  /** 整体替换航路点(拖拽回写 / 批量坐标应用)。按索引复用旧 id,保持编辑状态稳定 */
  function replaceRoutePoints(routeId: string, points: RoutePoint[]): { ok: true } | { ok: false; error: string } {
    const route = routes.value.find((item) => item.id === routeId)
    if (!route) return { ok: false, error: '航路不存在' }
    const normalized = normalizeRoutePoints(points)
    route.points = normalized.map((point, index) => {
      const old = route.points[index]
      return old ? { ...point, id: old.id } : point
    })
    route.updatedAt = new Date().toISOString()
    touch()
    return { ok: true }
  }

  function updateRoutePoint(
    routeId: string,
    pointId: string,
    lon: number,
    lat: number,
  ): { ok: true } | { ok: false; error: string } {
    const route = routes.value.find((item) => item.id === routeId)
    if (!route) return { ok: false, error: '航路不存在' }
    const point = route.points.find((item) => item.id === pointId)
    if (!point) return { ok: false, error: '航路点不存在' }
    const check = validateRouteCoordinate(lon, lat)
    if (!check.ok) return check
    point.lon = lon
    point.lat = lat
    route.updatedAt = new Date().toISOString()
    touch()
    return { ok: true }
  }

  function addRoutePoint(routeId: string, point?: Pick<RoutePoint, 'lon' | 'lat'>): { ok: true; point?: RoutePoint } | { ok: false; error: string } {
    const route = routes.value.find((item) => item.id === routeId)
    if (!route) return { ok: false, error: '航路不存在' }
    const last = route.points[route.points.length - 1]
    const lon = point?.lon ?? last?.lon ?? 120
    const lat = point?.lat ?? last?.lat ?? 72
    const check = validateRouteCoordinate(lon, lat)
    if (!check.ok) return check
    const newPoint: RoutePoint = { id: createId(), seq: route.points.length + 1, lon, lat }
    route.points.push(newPoint)
    route.updatedAt = new Date().toISOString()
    touch()
    return { ok: true, point: newPoint }
  }

  function removeRoutePoint(routeId: string, pointId: string): { ok: true } | { ok: false; error: string } {
    const route = routes.value.find((item) => item.id === routeId)
    if (!route) return { ok: false, error: '航路不存在' }
    const index = route.points.findIndex((item) => item.id === pointId)
    if (index < 0) return { ok: false, error: '航路点不存在' }
    if (route.points.length <= ROUTE_MIN_POINTS) {
      return { ok: false, error: '航路至少需要两个航路点' }
    }
    route.points.splice(index, 1)
    route.points = normalizeRoutePoints(route.points)
    route.updatedAt = new Date().toISOString()
    touch()
    return { ok: true }
  }

  function toggleRouteVisibility(routeId: string) {
    const route = routes.value.find((item) => item.id === routeId)
    if (!route) return
    route.visible = !route.visible
    route.updatedAt = new Date().toISOString()
    touch()
  }

  function showAllRoutes() {
    for (const route of routes.value) {
      route.visible = true
      route.updatedAt = new Date().toISOString()
    }
    touch()
  }

  function hideAllRoutes() {
    for (const route of routes.value) {
      route.visible = false
      route.updatedAt = new Date().toISOString()
    }
    touch()
  }

  function setInteractionMode(mode: RouteInteractionMode) {
    interactionMode.value = mode
  }

  function clearRoutes() {
    routes.value = []
    activeRouteId.value = null
    interactionMode.value = 'idle'
    touch()
  }

  /** 清空内存状态(不删除 localStorage 草稿),用于离开地图工作台 */
  function reset() {
    routes.value = []
    activeRouteId.value = null
    interactionMode.value = 'idle'
    loadedProjectId.value = null
    storageWarned.value = false
  }

  return {
    routes,
    activeRouteId,
    interactionMode,
    revision,
    loadedProjectId,
    visibleRouteIds,
    activeRoute,
    canEditPoints,
    nextRouteName,
    ensureLoaded,
    loadLocalRoutes,
    saveLocalRoutes,
    createRoute,
    createRouteFromPoints,
    deleteRoute,
    setActiveRoute,
    updateRouteName,
    replaceRoutePoints,
    updateRoutePoint,
    addRoutePoint,
    removeRoutePoint,
    toggleRouteVisibility,
    showAllRoutes,
    hideAllRoutes,
    setInteractionMode,
    clearRoutes,
    reset,
  }
})
