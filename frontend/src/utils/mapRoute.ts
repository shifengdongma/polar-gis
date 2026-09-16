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
import MultiPoint from 'ol/geom/MultiPoint'
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

// ── 样式 ──────────────────────────────────────────────────────────────

/** routeId → 颜色池稳定映射(字符串哈希,不随机,刷新后颜色一致) */
export function routeColor(routeId: string): string {
  let hash = 0
  for (let i = 0; i < routeId.length; i++) hash = (hash * 31 + routeId.charCodeAt(i)) >>> 0
  return ROUTE_COLOR_POOL[hash % ROUTE_COLOR_POOL.length]!
}

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

/**
 * 航路样式工厂:
 * - 隐藏航路返回 undefined(单条显隐,绝不使用 routeLayer.setVisible(false));
 * - 普通 2.5px、选中 4.5px、编辑中虚线(Modify 自带顶点手柄,不额外渲染节点);
 * - 选中(非编辑)时叠加航路点小圆点,便于识别节点位置。
 */
export function createRouteStyle(ctx: RouteStyleContext): StyleFunction {
  return (feature: FeatureLike): Style | Style[] | undefined => {
    const routeId = feature.get('routeId') as string | undefined
    if (!routeId || !ctx.isRouteVisible(routeId)) return undefined
    const active = ctx.isRouteActive(routeId)
    const editing = ctx.isRouteEditing(routeId)
    const lineStyles = getCachedLineStyles(routeColor(routeId), active, editing)
    if (!active || editing) return lineStyles
    const geometry = feature.getGeometry() as LineString | undefined
    const coordinates = geometry?.getCoordinates() ?? []
    if (coordinates.length < ROUTE_MIN_POINTS) return lineStyles
    return [
      ...lineStyles,
      new Style({
        geometry: new MultiPoint(coordinates),
        image: new CircleStyle({
          radius: 4.5,
          fill: new Fill({ color: routeColor(routeId) }),
          stroke: new Stroke({ color: '#ffffff', width: 2 }),
        }),
      }),
    ]
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
