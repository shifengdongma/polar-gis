/**
 * 测量(测距 / 测面积) — 纯 GIS / 坐标逻辑。
 *
 * 硬性约束:
 * - 业务坐标唯一真值 = WGS84 经纬度 [lon, lat];本模块入口/出口永远是该形式,
 *   投影坐标只在「绘制显示几何」这一步出现;
 * - 只允许 import ol 的几何/投影/球面计算等纯数学模块,
 *   禁止 import ol/layer、ol/source、ol/Map(保持 jsdom 可测、与渲染体系解耦);
 * - 结果文本一律由 WGS84 真值生成,不由「当前投影下的几何」生成 ——
 *   因此切换投影只重建显示几何、数值不变,不会出现旧投影几何配上新投影解释
 *   的错值(这正是原实现的问题:measureSource 里的几何不会随投影重建)。
 *
 * 面积算法说明:
 * 采用 Van Oosterom–Strackee 球面三角形立体角 + 以 0 号顶点扇形三角化,边按
 * **大圆**处理 —— 与 ol/sphere getLength/getDistance 的大圆语义一致。
 * 该算法与经度回绕无关(不需要 unwrap),且对环绕极点的环同样成立。
 * 代价:与 ol/sphere.getArea(其边在 (λ, sinφ) 空间取直线)存在边模型差异 ——
 * 小多边形 0.000%,大范围高纬多边形最大约 -1.8%(如 20°×6° 盒 @70–76°N);
 * 球面模型本身比 WGS84 椭球测地线偏短约 0.28%–0.42%(高纬更大)。
 * 界面按「近似地表距离」表述,不宣称具备航海认证精度。
 */
import { containsCoordinate } from 'ol/extent'
import LineString from 'ol/geom/LineString'
import Polygon from 'ol/geom/Polygon'
import { fromLonLat, get as getProjection, toLonLat } from 'ol/proj'
import { DEFAULT_RADIUS, getDistance } from 'ol/sphere'
import { METERS_PER_DEGREE_LAT, formatArea, formatDistance, normalizeLongitude, unwrapLongitudeSequence } from './mapRoute'

// ── 常量 ──────────────────────────────────────────────────────────────

/**
 * 地图内坐标提示的地面分辨率门槛(米/像素)。地面分辨率**粗于**该值时不显示提示。
 *
 * 依据:门槛取 1000 m/px 时,提示的最小可用小数位是 0.01°(≈1.1 km),与 1 个
 * 像素所代表的地面距离同量级 —— 再粗的视图下显示经纬度只会暗示地图本身给不
 * 出的定位精度。注意门槛必须用地面分辨率而非 zoom:同一个 zoom 数字在
 * EPSG:3857 与 EPSG:3413 下的地面精度相差数倍(实测 3857 zoom4 ≈ 2532 m/px,
 * 3413 zoom4 ≈ 39500 m/px),不能直接比 zoom。
 */
export const HOVER_MIN_GROUND_RESOLUTION_METERS = 1000

const EMPTY_VALUE = '—'

// ── 测量草稿(WGS84 真值) ─────────────────────────────────────────────

export type MeasureKind = 'LineString' | 'Polygon'

/**
 * 测量真值:WGS84 经纬度 [lon, lat] 序列,经度已收拢到 ±180。
 * LineString = 折线顶点;Polygon = 外环顶点,**不含重复的闭合点**
 * (由 measureGeometryToDraft 统一去重,buildMeasureGeometry 统一补回)。
 */
export interface MeasureDraft {
  kind: MeasureKind
  lonLat: number[][]
}

// ── 坐标换算 ──────────────────────────────────────────────────────────

/**
 * 内部换算:投影坐标 → WGS84。
 * - enforceExtent=false 时不检查投影范围,仅要求有限值与合法纬度(测量绘制用:
 *   3413 在低 zoom 下视口可超出投影范围,但用户确实点了那些点,直接拒绝整次测量
 *   反而更难理解);
 * - enforceExtent=true 时剔除投影有效范围外的坐标(悬停提示用:此时隐藏提示
 *   才是正确响应)。EPSG:3857 的 canWrapX() 为 true,横向允许世界副本回绕,
 *   只按纬度带剔除;EPSG:3413 为 false,按完整范围剔除。
 */
function toLonLatChecked(coordinate: readonly number[], crs: string, enforceExtent: boolean): [number, number] | null {
  if (!Number.isFinite(coordinate[0]) || !Number.isFinite(coordinate[1])) return null
  const projection = getProjection(crs)
  if (!projection) return null
  const extent = projection.getExtent()
  if (enforceExtent && extent) {
    if (projection.canWrapX()) {
      if (coordinate[1]! < extent[1]! || coordinate[1]! > extent[3]!) return null
    } else if (!containsCoordinate(extent, [coordinate[0]!, coordinate[1]!])) {
      return null
    }
  }
  const [lon, lat] = toLonLat([coordinate[0]!, coordinate[1]!], crs)
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null
  if (lat < -90 || lat > 90) return null
  return [normalizeLongitude(lon), lat]
}

/**
 * 投影坐标 → WGS84 经纬度,并**剔除投影有效范围外**的坐标。
 * 提示类 UI(悬停坐标)用:返回 null 表示「不显示」而不是「显示错值」。
 * 注意 EPSG:3413 下 proj4 的逆变换是全局双射,越界坐标**不会**产生 NaN
 * (实测 [5e6,5e6] → lon 90 / lat 30.5),因此这里必须显式做范围判断。
 */
export function projectedToLonLatSafe(coordinate: readonly number[], crs: string): [number, number] | null {
  return toLonLatChecked(coordinate, crs, true)
}

/**
 * 投影几何 → 测量真值。任一点非法即返回 null(测量图形不允许被静默截断,
 * 否则形状与结果都会失真)。
 */
export function measureGeometryToDraft(geometry: LineString | Polygon, crs: string): MeasureDraft | null {
  const kind: MeasureKind = geometry.getType() === 'Polygon' ? 'Polygon' : 'LineString'
  const raw = kind === 'Polygon' ? (geometry as Polygon).getCoordinates()[0] ?? [] : (geometry as LineString).getCoordinates()
  // 去掉 Draw 产生的重复闭合点,草稿始终是「顶点表」形式
  const coordinates = raw.length > 1 && sameCoordinate(raw[0]!, raw[raw.length - 1]!) ? raw.slice(0, -1) : raw
  const lonLat: number[][] = []
  for (const coordinate of coordinates) {
    const converted = toLonLatChecked(coordinate, crs, false)
    if (!converted) return null
    lonLat.push(converted)
  }
  const minimum = kind === 'Polygon' ? 3 : 2
  return lonLat.length < minimum ? null : { kind, lonLat }
}

/**
 * 测量真值 → 当前投影显示几何。经度连续化只作用于显示(跨 180° 时按短弧展开),
 * 真值永不被改写;产出非有限坐标时返回 null,绝不把坏几何放进测量图层。
 */
export function buildMeasureGeometry(draft: MeasureDraft, crs: string): LineString | Polygon | null {
  const minimum = draft.kind === 'Polygon' ? 3 : 2
  if (draft.lonLat.length < minimum) return null
  const lons = unwrapLongitudeSequence(draft.lonLat.map((coordinate) => coordinate[0]!))
  const coordinates = draft.lonLat.map((coordinate, index) => fromLonLat([lons[index]!, coordinate[1]!], crs))
  if (coordinates.some((coordinate) => coordinate.some((value) => !Number.isFinite(value)))) return null
  if (draft.kind === 'Polygon') {
    const ring = [...coordinates, coordinates[0]!]
    return new Polygon([ring])
  }
  return new LineString(coordinates)
}

// ── 球面面积 ──────────────────────────────────────────────────────────

type Vector3 = [number, number, number]

function toUnitVector(coordinate: readonly number[]): Vector3 | null {
  const lon = coordinate[0]
  const lat = coordinate[1]
  if (lon === undefined || lat === undefined || !Number.isFinite(lon) || !Number.isFinite(lat)) return null
  const lambda = (lon * Math.PI) / 180
  const phi = (lat * Math.PI) / 180
  const cosPhi = Math.cos(phi)
  return [cosPhi * Math.cos(lambda), cosPhi * Math.sin(lambda), Math.sin(phi)]
}

function dot(a: Vector3, b: Vector3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

function cross(a: Vector3, b: Vector3): Vector3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

/**
 * 球面三角形 (a, b, c) 的有向立体角(Van Oosterom & Strackee)。
 * 单位球上即该三角形面积(球面度)。
 */
function sphericalExcess(a: Vector3, b: Vector3, c: Vector3): number {
  return 2 * Math.atan2(dot(a, cross(b, c)), 1 + dot(a, b) + dot(b, c) + dot(c, a))
}

function sameCoordinate(a: readonly number[], b: readonly number[]): boolean {
  return a[0] === b[0] && a[1] === b[1]
}

/**
 * 环的球面面积(米²)。环边按大圆处理,与 getDistance/getLength 同一球体
 * (DEFAULT_RADIUS)。
 *
 * - 与经度是否跨 ±180 无关,也与环是否环绕极点无关(向量法天然免疫);
 *   这是它相对 ol/sphere.getArea 的关键区别:后者对跨 180° 的环偏大约 17 倍、
 *   对环绕极点的环恒返回 0;
 * - 环的两侧面积互补(和为整球面积),取**较小一侧** —— 在极区视图下即用户
 *   在屏幕上所绘环的内部;
 * - 顶点数不足 3 或存在非法/非有限坐标时返回 null(不返回 0,避免把「算不了」
 *   显示成「面积为零」)。
 */
export function sphericalRingArea(ringLonLat: readonly (readonly number[])[]): number | null {
  const vertices: Vector3[] = []
  for (const coordinate of ringLonLat) {
    const vector = toUnitVector(coordinate)
    if (!vector) return null
    vertices.push(vector)
  }
  // Draw 产出的外环首尾重复;兼容调用方传入已闭合的环
  const deduped =
    vertices.length > 3 && dot(vertices[0]!, vertices[vertices.length - 1]!) > 1 - 1e-12
      ? vertices.slice(0, -1)
      : vertices
  if (deduped.length < 3) return null
  let total = 0
  for (let i = 1; i < deduped.length - 1; i++) {
    total += sphericalExcess(deduped[0]!, deduped[i]!, deduped[i + 1]!)
  }
  const area = Math.abs(total) * DEFAULT_RADIUS * DEFAULT_RADIUS
  if (!Number.isFinite(area)) return null
  const sphereArea = 4 * Math.PI * DEFAULT_RADIUS * DEFAULT_RADIUS
  return Math.min(area, sphereArea - area)
}

// ── 结果文本 ──────────────────────────────────────────────────────────

/** 测量真值的折线长度(米):逐段球面最短路径求和 */
function draftLength(draft: MeasureDraft): number {
  let total = 0
  for (let i = 1; i < draft.lonLat.length; i++) {
    total += getDistance(draft.lonLat[i - 1]!, draft.lonLat[i]!)
  }
  return total
}

/**
 * 由 WGS84 真值生成结果文本 —— **与当前投影无关**,因此切换投影后重算必然得到
 * 同一字符串。折线用 formatDistance(km + NM),多边形用 formatArea(m² / km²)。
 */
export function formatMeasureResult(draft: MeasureDraft): string {
  if (draft.kind === 'Polygon') {
    const area = sphericalRingArea(draft.lonLat)
    return area === null ? EMPTY_VALUE : formatArea(area)
  }
  return formatDistance(draftLength(draft))
}

/**
 * 由地面分辨率(米/像素)推导经纬度小数位:取满足 0.1^d × 111320 m ≥ 分辨率
 * 的最大 d,即「末位数字从不细于 1 个像素」,不暗示超出地图显示能力的精度。
 *
 * 注意 floor 只在十进制档位跳变(如 158 m/px 与 1000 m/px 同为 2 位),
 * 因此同一档内末位会从约 1 px 漂到约 10 px —— 这是预期行为,不是缺陷:
 * 档位内变位数会让同一次缩放中数字长度跳动,反而更难读。
 */
export function hoverDecimalsForGroundResolution(groundResolutionMeters: number): number {
  if (!Number.isFinite(groundResolutionMeters) || groundResolutionMeters <= 0) return 2
  const digits = Math.floor(Math.log10(METERS_PER_DEGREE_LAT / groundResolutionMeters))
  return Math.min(5, Math.max(2, digits))
}
