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
import { getDistance } from 'ol/sphere'
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

// ── 单位与格式化 ──────────────────────────────────────────────────────
// 距离/面积文本的唯一出口:面板、地图浮窗、测量状态栏共用,避免同一数值出现
// 两套写法。面积恒用 m² / km² —— 面积绝不换算为海里(距离才用 NM)。

/** 1 海里 = 1852 米(国际海里的定义值,非近似) */
export const METERS_PER_NAUTICAL_MILE = 1852

/** 赤道处 1° 纬度 ≈ 111320 m。用于把地面分辨率换算成经纬度小数位 */
export const METERS_PER_DEGREE_LAT = 111320

const EMPTY_VALUE = '—'

/**
 * 距离文本:短距离(< 1 km)兼显米,其余用千米,两者都附海里。
 * 例:`812.3 m（0.44 NM）`、`2642.27 km（1426.71 NM）`。非有限 / 负数 → `—`。
 */
export function formatDistance(meters: number): string {
  if (!Number.isFinite(meters) || meters < 0) return EMPTY_VALUE
  const nauticalMiles = (meters / METERS_PER_NAUTICAL_MILE).toFixed(2)
  const metric = meters < 1000 ? `${meters.toFixed(1)} m` : `${(meters / 1000).toFixed(2)} km`
  return `${metric}（${nauticalMiles} NM）`
}

/** 面积文本:m² / km²(永不换算为海里)。非有限 / 负数 → `—` */
export function formatArea(squareMeters: number): string {
  if (!Number.isFinite(squareMeters) || squareMeters < 0) return EMPTY_VALUE
  return squareMeters >= 1_000_000
    ? `${(squareMeters / 1_000_000).toFixed(2)} km²`
    : `${squareMeters.toFixed(1)} m²`
}

/** 方位角文本(度,保留 1 位小数);null / 非有限 → `—` */
export function formatBearing(degrees: number | null): string {
  if (degrees === null || !Number.isFinite(degrees)) return EMPTY_VALUE
  return `${degrees.toFixed(1)}°`
}

/**
 * 经纬度文本:`经度 123.4567° E · 纬度 74.1234° N`。
 * 显式写出「经度在前、纬度在后」并带方位字母 E/W、N/S —— 屏幕上永远不允许
 * 出现无法判断经纬度顺序的裸坐标。小数位由调用方按显示分辨率决定。
 */
export function formatLonLat(lon: number, lat: number, decimals = 4): string {
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return EMPTY_VALUE
  const lonHemisphere = lon >= 0 ? 'E' : 'W'
  const latHemisphere = lat >= 0 ? 'N' : 'S'
  return `经度 ${Math.abs(lon).toFixed(decimals)}° ${lonHemisphere} · 纬度 ${Math.abs(lat).toFixed(decimals)}° ${latHemisphere}`
}

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
 * 连续化经度序列(仅渲染用):保证相邻元素 |Δlon| ≤ 180。
 * 跨 180° 经线时 179 → -179 展开为 179 → 181,业务数据永不被改写。
 */
export function unwrapLongitudeSequence(lons: readonly number[]): number[] {
  const unwrapped = [...lons]
  for (let i = 1; i < unwrapped.length; i++) {
    const delta = unwrapped[i]! - unwrapped[i - 1]!
    if (delta > 180) unwrapped[i] = unwrapped[i]! - 360
    else if (delta < -180) unwrapped[i] = unwrapped[i]! + 360
  }
  return unwrapped
}

/**
 * 连续化经度(仅渲染用):按 seq 排序后委托 unwrapLongitudeSequence。
 * EPSG:3413 下 proj4 的 adjust_lon 会自行回绕,展开同样无害。
 */
export function unwrapLongitudes(points: RoutePoint[]): number[] {
  const sorted = [...points].sort((a, b) => a.seq - b.seq)
  return unwrapLongitudeSequence(sorted.map((point) => point.lon))
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

// ── 航段与长度计算 ────────────────────────────────────────────────────

/**
 * 初始真方位角(度,范围 [0, 360))。从起点沿大圆出发的初始航向。
 *
 * - 这是**真方位**(相对真北),不是磁方位;也不代表整段航程的恒定航向 ——
 *   沿大圆航行时航向会持续变化,只有出发瞬间等于该值;
 * - 不手工归一化 Δλ:sin / cos 本身以 2π 为周期,跨 180° 经线自动取短弧;
 * - 重合点(零长航段)与非有限输入返回 null。
 */
export function initialBearing(fromLon: number, fromLat: number, toLon: number, toLat: number): number | null {
  if (![fromLon, fromLat, toLon, toLat].every((value) => Number.isFinite(value))) return null
  if (fromLon === toLon && fromLat === toLat) return null
  const phi1 = (fromLat * Math.PI) / 180
  const phi2 = (toLat * Math.PI) / 180
  const deltaLambda = ((toLon - fromLon) * Math.PI) / 180
  const y = Math.sin(deltaLambda) * Math.cos(phi2)
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(deltaLambda)
  const degrees = (Math.atan2(y, x) * 180) / Math.PI
  if (!Number.isFinite(degrees)) return null
  return ((degrees % 360) + 360) % 360
}

export interface RouteSegment {
  /** 1-based:第 i 段 = 第 i 个航路点 → 第 i+1 个航路点 */
  index: number
  from: RoutePoint
  to: RoutePoint
  /** 球面最短路径(大圆)距离,米。与 ol/sphere getDistance 同源同值 */
  distanceMeters: number
  /** 截至该段终点的累计距离,米 */
  cumulativeMeters: number
  /** 该段初始真方位角(度);零长航段为 null */
  initialBearingDeg: number | null
}

/**
 * 按 seq 升序切分航段(n 点 → n−1 段)。航段是长度的唯一计算口径:
 * 面板「入站航段 / 累计」列与地图浮窗都读它,总长等于各段之和。
 * 起点没有入站航段,因此不产生 index 0 的段。
 */
export function routeSegments(points: RoutePoint[]): RouteSegment[] {
  const sorted = [...points].sort((a, b) => a.seq - b.seq)
  const segments: RouteSegment[] = []
  let cumulative = 0
  for (let i = 1; i < sorted.length; i++) {
    const from = sorted[i - 1]!
    const to = sorted[i]!
    const distanceMeters = getDistance([from.lon, from.lat], [to.lon, to.lat])
    cumulative += distanceMeters
    segments.push({
      index: i,
      from,
      to,
      distanceMeters,
      cumulativeMeters: cumulative,
      initialBearingDeg: initialBearing(from.lon, from.lat, to.lon, to.lat),
    })
  }
  return segments
}

/**
 * 球面长度(米)= 各航段距离之和。基于原始 WGS84 点,跨 180° 经线天然正确
 * (haversine 对 Δλ 取 sin²,自动取短弧),不需要 unwrap。
 *
 * 用 getDistance 逐段求和而非 getLength(LineString):ol/sphere 的 getLength
 * 内部就是同一函数逐段求和,故两者逐位相同,而这里能保证「分段之和 ≡ 总长」
 * 由构造成立,不会出现面板分段与浮窗总长对不上的情况。
 */
export function calculateRouteLength(points: RoutePoint[]): number {
  if (points.length < ROUTE_MIN_POINTS) return 0
  return routeSegments(points).reduce((total, segment) => total + segment.distanceMeters, 0)
}

/** 某航路点在 seq 升序中的下标;找不到返回 -1(点表定位用) */
export function routePointIndexById(points: RoutePoint[], pointId: string): number {
  const sorted = [...points].sort((a, b) => a.seq - b.seq)
  return sorted.findIndex((point) => point.id === pointId)
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

/** 选中航段的高亮色(叠加在线本身之上) */
export const ROUTE_SEGMENT_HIGHLIGHT_COLOR = '#ffd166'
/** 定位航路点时短暂高亮的颜色 */
export const ROUTE_POINT_HIGHLIGHT_COLOR = '#ffd166'

export interface RouteStyleContext {
  isRouteVisible: (routeId: string) => boolean
  isRouteActive: (routeId: string) => boolean
  isRouteEditing: (routeId: string) => boolean
  /** 高亮航段:1-based 航段序号(第 i 段 = 第 i 个点 → 第 i+1 个点);无 → null */
  getHighlightedSegment?: (routeId: string) => number | null
  /** 高亮航路点:seq 升序下标;无 → null */
  getHighlightedPointIndex?: (routeId: string) => number | null
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

// 高亮笔触 / 标记 image 与航路无关,可跨帧复用;仅 Style 包装器每帧新建
let segmentHighlightStroke: Stroke | null = null
let pointHighlightImage: CircleStyle | null = null

function getSegmentHighlightStroke(): Stroke {
  if (!segmentHighlightStroke) {
    // 外描边压在航路线之上,保证在任何航路配色与海图底色下都能看清被选中的段
    segmentHighlightStroke = new Stroke({ color: ROUTE_SEGMENT_HIGHLIGHT_COLOR, width: 6 })
  }
  return segmentHighlightStroke
}

function getPointHighlightImage(): CircleStyle {
  if (!pointHighlightImage) {
    pointHighlightImage = new CircleStyle({
      radius: ROUTE_START_END_MARKER_RADIUS + 3,
      fill: new Fill({ color: 'rgba(255,209,102,0.35)' }),
      stroke: new Stroke({ color: ROUTE_POINT_HIGHLIGHT_COLOR, width: 2.5 }),
    })
  }
  return pointHighlightImage
}

/**
 * 高亮叠加(选中航段 / 定位航路点)。
 * 不新增 source、layer 或 interaction:只是在同一条航路要素上多返回一条
 * 「自带几何」的 Style —— 与起点/终点标记完全相同的做法。Style 数组按顺序绘制,
 * 因此把高亮放在最后即画在最上层。几何每次新建(坐标随视图变化不可复用)。
 */
function createHighlightStyles(ctx: RouteStyleContext, routeId: string, coordinates: number[][]): Style[] {
  const styles: Style[] = []
  const segmentIndex = ctx.getHighlightedSegment?.(routeId) ?? null
  if (segmentIndex !== null && segmentIndex >= 1 && segmentIndex < coordinates.length) {
    const style = new Style({ stroke: getSegmentHighlightStroke() })
    style.setGeometry(new LineString([coordinates[segmentIndex - 1]!, coordinates[segmentIndex]!]))
    styles.push(style)
  }
  const pointIndex = ctx.getHighlightedPointIndex?.(routeId) ?? null
  if (pointIndex !== null && pointIndex >= 0 && pointIndex < coordinates.length) {
    const style = new Style({ image: getPointHighlightImage() })
    style.setGeometry(new Point(coordinates[pointIndex]!))
    styles.push(style)
  }
  return styles
}

/**
 * 航路样式工厂:
 * - 隐藏航路返回 undefined(单条显隐,绝不使用 routeLayer.setVisible(false));
 * - 普通 2.5px、选中 4.5px、编辑中虚线(Modify 自带顶点手柄,不额外渲染节点);
 * - 起点(绿)/ 终点(红)标记始终随航路显示,标明航路方向;
 * - 选中(非编辑)时额外叠加途经点小圆点;
 * - 选中航段 / 定位航路点的高亮叠加在最后(画在最上层)。
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
    const base =
      !active || editing
        ? [...lineStyles, ...directionStyles.filter((_, index) => index === 0 || index === coordinates.length - 1)]
        : [...lineStyles, ...directionStyles]
    return [...base, ...createHighlightStyles(ctx, routeId, coordinates)]
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

/**
 * 把坐标平移到与参考 extent 相同的世界副本(仅对 canWrapX 的投影有意义)。
 *
 * 为什么需要:fromLonLat 不会把经度回绕到主世界,而 toLonLat 会 —— 于是
 * `fromLonLat([181, 70])` 落在世界副本 +1(x ≈ +2.0e7),而同一地点经 toLonLat
 * 往返后只剩主世界的 x ≈ −1.99e7。渲染几何与重算坐标因此可能不同副本。
 * EPSG:3857 的 canWrapX() 为 true、EPSG:3413 为 false(proj4 注册的投影默认
 * 非 global),所以 3413 下原样返回。
 */
export function shiftCoordinateIntoWorldCopy(coordinate: number[], referenceExtent: Extent, crs: string): number[] {
  const projection = getProjection(crs)
  if (!projection?.canWrapX()) return coordinate
  const projectionExtent = projection.getExtent()
  if (!projectionExtent) return coordinate
  const worldWidth = getWidth(projectionExtent)
  if (!worldWidth) return coordinate
  const referenceX = (referenceExtent[0]! + referenceExtent[2]!) / 2
  const shift = Math.round((referenceX - coordinate[0]!) / worldWidth) * worldWidth
  return shift ? [coordinate[0]! + shift, coordinate[1]!] : coordinate
}

/** 环形经度差(范围 [-180, 180]),用于跨 ±180 经线的测试断言 */
export function longitudeDelta(a: number, b: number): number {
  let delta = (b - a) % 360
  if (delta > 180) delta -= 360
  if (delta < -180) delta += 360
  return delta
}
