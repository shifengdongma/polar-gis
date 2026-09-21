/**
 * 航路规划模拟 — 纯 GIS / 坐标逻辑。
 *
 * 硬性约束:
 * - 业务坐标唯一真值 = WGS84 经纬度 [lon, lat],本模块入口/出口永远是该形式;
 * - 只允许 import ol 的几何/投影/样式/球面计算等纯数学模块,
 *   禁止 import ol/layer、ol/source、ol/Map(保持 jsdom 可测、与渲染体系解耦);
 * - 跨 180° 经线的连续化(unwrap)仅作用于渲染几何,业务数据永不改写。
 */
import Feature from 'ol/Feature'
import type { Extent } from 'ol/extent'
import { getWidth } from 'ol/extent'
import LineString from 'ol/geom/LineString'
import Point from 'ol/geom/Point'
import { fromLonLat, get as getProjection, toLonLat } from 'ol/proj'
import { getLength } from 'ol/sphere'
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style'
import type { StyleFunction } from 'ol/style/Style'
import type { FeatureLike } from 'ol/Feature'
import type { RouteDraft, RoutePoint } from '../types'

// ── 常量 ──────────────────────────────────────────────────────────────

export const ROUTE_MIN_POINTS = 2

/** 航路固定颜色池 — 按 routeId 哈希稳定映射,同一条航路刷新后颜色保持一致 */
export const ROUTE_COLOR_POOL = [
  '#ff6b35',
  '#2a9d8f',
  '#457b9d',
  '#c084fc',
  '#e63946',
  '#f4a261',
  '#7bd389',
  '#8ab4f8',
] as const

// ── 校验 ──────────────────────────────────────────────────────────────

export type CoordinateCheck = { ok: true } | { ok: false; error: string }

export function validateRouteCoordinate(lon: unknown, lat: unknown): CoordinateCheck {
  if (typeof lon !== 'number' || typeof lat !== 'number') {
    return { ok: false, error: '坐标必须是有效数字' }
  }
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    return { ok: false, error: '坐标必须是有限数字(NaN / Infinity 无效)' }
  }
  if (lon < -180 || lon > 180) {
    return { ok: false, error: '经度必须是 -180 ~ 180 之间的数字' }
  }
  if (lat < -90 || lat > 90) {
    return { ok: false, error: '纬度必须是 -90 ~ 90 之间的数字' }
  }
  return { ok: true }
}

export function validateRoutePoint(point: Pick<RoutePoint, 'lon' | 'lat'> | null | undefined): CoordinateCheck {
  if (!point) return { ok: false, error: '航路点不能为空' }
  return validateRouteCoordinate(point.lon, point.lat)
}

export function validateRoutePoints(points: RoutePoint[]): CoordinateCheck {
  if (points.length < ROUTE_MIN_POINTS) {
    return { ok: false, error: '航路至少需要两个航路点' }
  }
  for (const point of points) {
    const check = validateRoutePoint(point)
    if (!check.ok) return check
  }
  return { ok: true }
}

// ── ID ────────────────────────────────────────────────────────────────

/**
 * 生成唯一 ID。crypto.randomUUID 仅在安全上下文可用(局域网 http 部署时为
 * undefined),降级为 getRandomValues 构造 UUID v4。
 */
export function createId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const bytes = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

// ── 归一化 ────────────────────────────────────────────────────────────

/** 经度收拢到 [-180, 180](地图坐标回写业务数据前必须调用) */
export function normalizeLongitude(lon: number): number {
  if (!Number.isFinite(lon)) return lon
  let wrapped = lon % 360
  if (wrapped > 180) wrapped -= 360
  if (wrapped < -180) wrapped += 360
  return wrapped
}

/** 丢弃非法点、补齐 id、按原始顺序重排 seq(1-based) */
export function normalizeRoutePoints(points: RoutePoint[]): RoutePoint[] {
  const normalized: RoutePoint[] = []
  for (const point of points) {
    const check = validateRoutePoint(point)
    if (!check.ok) continue
    normalized.push({
      id: point.id || createId(),
      seq: normalized.length + 1,
      lon: point.lon,
      lat: point.lat,
    })
  }
  return normalized
}

// ── 坐标文本解析 ──────────────────────────────────────────────────────

export interface ParsedRouteText {
  points: RoutePoint[]
  errors: string[]
}

/**
 * 解析批量坐标文本:每行一个点 `经度,纬度`(也兼容空格/分号/顿号分隔)。
 * 非法行返回 `第 N 行坐标格式错误(应为 经度,纬度)`,绝不静默生成错误航路。
 */
export function parseRouteCoordinateText(text: string): ParsedRouteText {
  const points: RoutePoint[] = []
  const errors: string[] = []
  const lines = text.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const trimmed = (lines[i] ?? '').trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const tokens = trimmed.split(/[\s,;、]+/).filter(Boolean)
    if (tokens.length !== 2) {
      errors.push(`第 ${i + 1} 行坐标格式错误(应为 经度,纬度)`)
      continue
    }
    const lon = Number(tokens[0])
    const lat = Number(tokens[1])
    const check = validateRouteCoordinate(lon, lat)
    if (!check.ok) {
      errors.push(`第 ${i + 1} 行坐标格式错误(应为 经度,纬度)`)
      continue
    }
    points.push({ id: createId(), seq: points.length + 1, lon, lat })
  }
  return { points, errors }
}

// ── 经纬度 ⇄ 投影坐标 ─────────────────────────────────────────────────

/**
 * 连续化经度(仅渲染用):内部按 seq 排序后,保证相邻点 |Δlon| ≤ 180。
 * 跨 180° 经线时 179 → -179 展开为 179 → 181,业务数据永不被改写。
 * EPSG:3413 下 proj4 的 adjust_lon 会自行回绕,展开同样无害。
 */
export function unwrapLongitudes(points: RoutePoint[]): number[] {
  const sorted = [...points].sort((a, b) => a.seq - b.seq)
  const lons = sorted.map((point) => point.lon)
  for (let i = 1; i < lons.length; i++) {
    const delta = lons[i]! - lons[i - 1]!
    if (delta > 180) lons[i] = lons[i]! - 360
    else if (delta < -180) lons[i] = lons[i]! + 360
  }
  return lons
}

/** WGS84 航路点 → 当前投影坐标(按 seq 排序,经度连续化) */
export function routePointsToProjectedCoordinates(points: RoutePoint[], crs: string): number[][] {
  const sorted = [...points].sort((a, b) => a.seq - b.seq)
  const lons = unwrapLongitudes(sorted)
  return sorted.map((point, index) => fromLonLat([lons[index] ?? point.lon, point.lat], crs))
}

/**
 * 投影坐标 → WGS84 航路点(地图拖拽/绘制后回写业务数据)。
 * 过滤非有限值、经度收拢到 ±180、纬度夹取到 ±90,保证写回 Store 的坐标永远合法。
 */
export function projectedCoordinatesToRoutePoints(coordinates: number[][], crs: string): RoutePoint[] {
  const points: RoutePoint[] = []
  for (const coordinate of coordinates) {
    const [rawLon, rawLat] = toLonLat(coordinate, crs)
    if (!Number.isFinite(rawLon) || !Number.isFinite(rawLat)) continue
    points.push({
      id: createId(),
      seq: points.length + 1,
      lon: normalizeLongitude(rawLon),
      lat: Math.min(90, Math.max(-90, rawLat)),
    })
  }
  return points
}

/** 从 WGS84 航路点构建当前投影下的 LineString;< 2 点或产出非有限坐标时返回 null */
export function buildRouteLineString(points: RoutePoint[], crs: string): LineString | null {
  const sorted = [...points].sort((a, b) => a.seq - b.seq)
  if (sorted.length < ROUTE_MIN_POINTS) return null
  const lons = unwrapLongitudes(sorted)
  const coordinates = sorted.map((point, index) => fromLonLat([lons[index] ?? point.lon, point.lat], crs))
  if (coordinates.some((coordinate) => coordinate.some((value) => !Number.isFinite(value)))) return null
  return new LineString(coordinates)
}

// ── 长度计算 ──────────────────────────────────────────────────────────

/** 球面长度(米)。基于原始 WGS84 点,跨 180° 经线天然正确,不需要 unwrap */
export function calculateRouteLength(points: RoutePoint[]): number {
  if (points.length < ROUTE_MIN_POINTS) return 0
  const sorted = [...points].sort((a, b) => a.seq - b.seq)
  const line = new LineString(sorted.map((point) => [point.lon, point.lat]))
  return getLength(line, { projection: 'EPSG:4326' })
}

// ── 航路方向(起点 / 途经 / 终点) ─────────────────────────────────────

/**
 * 航路点角色。航路方向由途经点先后顺序定义:seq 最小者 = 起点,最大者 = 终点,
 * 其余为途经点。角色以 seq(方向真值)而非数组下标判定。
 */
export type RoutePointRole = 'start' | 'via' | 'end' | 'invalid'

/** 按 seq 判定第 index 个航路点的方向角色;空航路 / 下标越界返回 invalid */
export function routePointRole(points: RoutePoint[], index: number): RoutePointRole {
  const point = points[index]
  if (!point) return 'invalid'
  if (points.length === 1) return 'start' // 单点航路:既是起点也是终点,优先显示起点
  let minSeq = Infinity
  let maxSeq = -Infinity
  for (const item of points) {
    if (item.seq < minSeq) minSeq = item.seq
    if (item.seq > maxSeq) maxSeq = item.seq
  }
  if (point.seq === minSeq) return 'start'
  if (point.seq === maxSeq) return 'end'
  return 'via'
}

/** 航路点角色中文标注(点表「说明」列);非法角色返回空串 */
export function routePointRoleLabel(role: RoutePointRole): string {
  switch (role) {
    case 'start':
      return '起点'
    case 'end':
      return '终点'
    case 'via':
      return '途经'
    default:
      return ''
  }
}

// ── 样式 ──────────────────────────────────────────────────────────────

/** routeId → 颜色池稳定映射(字符串哈希,不随机,刷新后颜色一致) */
export function routeColor(routeId: string): string {
  let hash = 0
  for (let i = 0; i < routeId.length; i++) hash = (hash * 31 + routeId.charCodeAt(i)) >>> 0
  return ROUTE_COLOR_POOL[hash % ROUTE_COLOR_POOL.length]!
}

/** 起点标记色 — 故意不使用配色池中的颜色,保证方向端不被线路颜色淹没 */
export const ROUTE_START_COLOR = '#2e9e4f'
/** 终点标记色 */
export const ROUTE_END_COLOR = '#e5484d'
/** 途经点标记色(跟随航路配色) */
export const ROUTE_VIA_COLOR = '#8a94a6'

export const ROUTE_START_END_MARKER_RADIUS = 7
export const ROUTE_VIA_MARKER_RADIUS = 4.5

export interface RouteStyleContext {
  isRouteVisible: (routeId: string) => boolean
  isRouteActive: (routeId: string) => boolean
  isRouteEditing: (routeId: string) => boolean
}

// styleFunction 每帧每个要素都会执行,线样式必须按 (color, variant) 缓存,禁止每次 new
const lineStyleCache = new Map<string, Style[]>()

function getCachedLineStyles(color: string, active: boolean, editing: boolean): Style[] {
  const variant = editing ? 'editing' : active ? 'active' : 'normal'
  const key = `${color}:${variant}`
  let cached = lineStyleCache.get(key)
  if (!cached) {
    cached = [
      // 外描边(halo),提高海图背景下的可见度
      new Style({ stroke: new Stroke({ color: 'rgba(6,20,32,0.9)', width: active ? 7 : 4 }) }),
      new Style({
        stroke: new Stroke({
          color,
          width: active ? 4.5 : 2.5,
          lineDash: editing ? [8, 6] : undefined,
        }),
      }),
    ]
    lineStyleCache.set(key, cached)
  }
  return cached
}

// 标记 image 与航路无关(起点恒绿、终点恒红),按角色缓存的 image 可跨帧复用
const markerImageCache = new Map<RoutePointRole, CircleStyle>()

function getMarkerImage(role: RoutePointRole): CircleStyle {
  let image = markerImageCache.get(role)
  if (!image) {
    // 方向端 = 起点 / 终点:加大并加粗描边,缩远时依然可辨
    const isDirectionEnd = role === 'start' || role === 'end'
    const color = role === 'start' ? ROUTE_START_COLOR : role === 'end' ? ROUTE_END_COLOR : ROUTE_VIA_COLOR
    image = new CircleStyle({
      radius: isDirectionEnd ? ROUTE_START_END_MARKER_RADIUS : ROUTE_VIA_MARKER_RADIUS,
      fill: new Fill({ color }),
      stroke: new Stroke({ color: '#ffffff', width: isDirectionEnd ? 2.5 : 2 }),
    })
    markerImageCache.set(role, image)
  }
  return image
}

/**
 * 航路点标记样式:数组下标 i 对应第 i 个投影坐标。
 * 按途经点先后顺序即航路方向 —— 首点 = 起点(绿)、末点 = 终点(红)、其余 = 途经点;
 * 单点航路按起点显示。几何每次新建,坐标不同不可跨帧复用;image 按角色缓存。
 */
export function createRoutePointStyles(_routeId: string, coordinates: number[][]): Style[] {
  return coordinates.map((coordinate, index) => {
    const role: RoutePointRole =
      index === 0 || coordinates.length === 1
        ? 'start'
        : index === coordinates.length - 1
          ? 'end'
          : 'via'
    const style = new Style({ image: getMarkerImage(role) })
    style.setGeometry(new Point(coordinate))
    return style
  })
}

/**
 * 航路样式工厂:
 * - 隐藏航路返回 undefined(单条显隐,绝不使用 routeLayer.setVisible(false));
 * - 普通 2.5px、选中 4.5px、编辑中虚线(Modify 自带顶点手柄,不额外渲染节点);
 * - 起点(绿)/ 终点(红)标记始终随航路显示,标明航路方向;
 * - 选中(非编辑)时额外叠加途经点小圆点。
 */
export function createRouteStyle(ctx: RouteStyleContext): StyleFunction {
  return (feature: FeatureLike): Style | Style[] | undefined => {
    const routeId = feature.get('routeId') as string | undefined
    if (!routeId || !ctx.isRouteVisible(routeId)) return undefined
    const active = ctx.isRouteActive(routeId)
    const editing = ctx.isRouteEditing(routeId)
    const lineStyles = getCachedLineStyles(routeColor(routeId), active, editing)
    const geometry = feature.getGeometry() as LineString | undefined
    const coordinates = geometry?.getCoordinates() ?? []
    if (coordinates.length < ROUTE_MIN_POINTS) return lineStyles
    const directionStyles = createRoutePointStyles(routeId, coordinates)
    // 选中且非编辑时,途经点也一并显示;其余情况只保留起点 / 终点方向标记
    if (!active || editing) return [...lineStyles, ...directionStyles.filter((_, index) => index === 0 || index === coordinates.length - 1)]
    return [...lineStyles, ...directionStyles]
  }
}

// ── Feature 构建与几何工具 ────────────────────────────────────────────

/** 由 RouteDraft 构建渲染 Feature(属性 routeId/routeName/routeType,业务真值仍在 Store) */
export function buildRouteFeature(route: RouteDraft, crs: string): Feature<LineString> | null {
  const geometry = buildRouteLineString(route.points, crs)
  if (!geometry) return null
  const feature = new Feature<LineString>({ geometry })
  feature.set('routeId', route.id)
  feature.set('routeName', route.name)
  feature.set('routeType', 'route-draft')
  return feature
}

/**
 * 坐标近似相等比较(容差 1e-6 米)。
 * 拖拽回写后 Store 重建的坐标与 Feature 现有坐标仅有投影 round-trip 浮点误差,
 * 视为相等以避免无意义的 setGeometry(触发 Modify 内部 rBush 重建)。
 */
export function coordinatesEqual(a: number[][], b: number[][], tolerance = 1e-6): boolean {
  if (a.length !== b.length) return false
  return a.every((coordinate, i) => {
    const other = b[i]
    if (!other || coordinate.length !== other.length) return false
    return coordinate.every((value, j) => Math.abs(value - other[j]!) <= tolerance)
  })
}

/**
 * 把 extent 平移到投影合法范围内(仅 EPSG:3857 需要)。
 * 跨 180° 航路 unwrap 后的 extent 可能落在 ±20037508 之外,而 View 会把
 * fit 中心夹回投影范围,导致定位航路看不到 —— 按世界宽度整数倍平移回来。
 */
export function shiftExtentIntoProjection(extent: Extent, crs: string): Extent {
  if (crs !== 'EPSG:3857') return extent
  const projectionExtent = getProjection(crs)?.getExtent()
  if (!projectionExtent) return extent
  const width = getWidth(projectionExtent)
  const [minX, minY, maxX, maxY] = extent
  if (minX >= projectionExtent[0]! && maxX <= projectionExtent[2]!) return extent
  const shift = Math.floor((minX - projectionExtent[0]!) / width) * width
  return [minX - shift, minY, maxX - shift, maxY]
}

/** 环形经度差(范围 [-180, 180]),用于跨 ±180 经线的测试断言 */
export function longitudeDelta(a: number, b: number): number {
  let delta = (b - a) % 360
  if (delta > 180) delta -= 360
  if (delta < -180) delta += 360
  return delta
}
