/**
 * 冰情叠加 —— 纯地图/投影工具。
 *
 * 硬性约束:
 * - 冰情是独立环境叠加层:本模块只允许 import ol 的投影/瓦片网格纯数学模块
 *   (与 proj4),禁止 import ol/layer、ol/source、ol/Map(保持 jsdom 可测、
 *   与渲染体系解耦);
 * - 源网格坐标系 = EPSG:3411(Hughes 椭球,NSIDC 极射赤面,与后端 pyproj
 *   EPSG:3411 及 NetCDF 数据一致);显示投影 3413/3857 一律经 WGS84 中转,
 *   绝不把 3411 米坐标当作 3413;
 * - 瓦片 URL 必须携带日期(浏览器不会跨日期错误复用瓦片);
 * - 时间轴一律使用 info.dates 的**数组索引**,绝不按 date ± 1 天推算;
 * - 调色板色值必须与后端 app/services/ice.py 的 PALETTE_STOPS 逐值一致
 *   (两侧测试各自锁定同一组色值,禁止两套配色)。
 */
import { get as getProjection, transformExtent } from 'ol/proj'
import { register } from 'ol/proj/proj4'
import { createXYZ } from 'ol/tilegrid'
import type TileGrid from 'ol/tilegrid/TileGrid'
import proj4 from 'proj4'
import type { IceFieldId, IceInfo } from '../types'

// ── 源投影注册(EPSG:3411,与后端 pyproj 定义逐项一致) ─────────────────

export const ICE_SOURCE_CRS = 'EPSG:3411'
const ICE_SOURCE_PROJ4 =
  '+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +a=6378273 +b=6356889.449 +units=m +no_defs'

let sourceProjectionRegistered = false

/** 按需注册 EPSG:3411(幂等;仅使用 probe 式注册,不覆盖已有定义)。 */
function ensureSourceProjection(): void {
  if (sourceProjectionRegistered) return
  if (!getProjection(ICE_SOURCE_CRS)) {
    proj4.defs(ICE_SOURCE_CRS, ICE_SOURCE_PROJ4)
  }
  register(proj4)
  sourceProjectionRegistered = true
}

// ── 瓦片网格常量 ────────────────────────────────────────────────────────

export const ICE_TILE_SIZE = 256
export const ICE_MAX_ZOOM = 10
/** 与后端 _png 的 half=4194304(及 MapWorkspaceView 的 3413 setExtent)严格一致 */
export const ICE_EXTENT_3413: [number, number, number, number] = [-4194304, -4194304, 4194304, 4194304]
/** 标准 Web 墨卡托 extent(= π·6378137) */
export const ICE_EXTENT_3857: [number, number, number, number] = [
  -Math.PI * 6378137, -Math.PI * 6378137, Math.PI * 6378137, Math.PI * 6378137,
]

/**
 * 冰情图层 zIndex:海图 S-57 为 10-40、航路 95、测量 100、AIS 110 ——
 * 冰情占 60/62(海图之上、航路之下),不修改任何现有 zIndex。
 * 厚度在下、浓度在上(与任务书的图层叠加次序一致)。
 */
export const ICE_LAYER_Z_INDEX: Record<IceFieldId, number> = { thickness: 60, concentration: 62 }
/** 对齐调试控制点(黄色圆点)显示在最上层 */
export const ICE_ALIGNMENT_Z_INDEX = 120

/** 字段中文名(与后端 FIELD_LABELS 一致,面板/浮窗共用) */
export const ICE_FIELD_LABELS: Record<IceFieldId, string> = {
  concentration: '海冰浓度',
  thickness: '海冰厚度',
}

/** CSS 色值辅助类型(与后端 PALETTE_STOPS 的 RGBA 元组同构) */
export interface IcePaletteStop {
  value: number
  rgba: [number, number, number, number]
}

/** 与 backend/app/services/ice.py PALETTE_STOPS 逐值一致的调色板(含 alpha) */
export const ICE_PALETTES: Record<IceFieldId, IcePaletteStop[]> = {
  concentration: [
    { value: 0.0, rgba: [218, 246, 249, 0] },
    { value: 0.1, rgba: [173, 232, 235, 140] },
    { value: 0.2, rgba: [112, 210, 218, 165] },
    { value: 0.3, rgba: [51, 180, 195, 190] },
    { value: 0.4, rgba: [28, 140, 170, 210] },
    { value: 0.5, rgba: [25, 94, 145, 225] },
    { value: 0.6, rgba: [242, 207, 103, 230] },
    { value: 0.7, rgba: [245, 166, 65, 235] },
    { value: 0.8, rgba: [236, 112, 56, 240] },
    { value: 0.9, rgba: [213, 64, 57, 245] },
    { value: 1.0, rgba: [171, 36, 66, 250] },
  ],
  thickness: [
    { value: 0.0, rgba: [255, 246, 214, 0] },
    { value: 0.5, rgba: [255, 229, 153, 145] },
    { value: 1.5, rgba: [239, 155, 70, 210] },
    { value: 3.0, rgba: [177, 63, 111, 235] },
    { value: 5.0, rgba: [142, 36, 95, 250] },
  ],
}

// ── 工具函数 ────────────────────────────────────────────────────────────

/** 当前投影对应的 XYZ 瓦片网格(仅 3413/3857 两种显示投影存在)。 */
export function createIceTileGrid(crs: string): TileGrid {
  const extent = crs === 'EPSG:3413' ? ICE_EXTENT_3413 : ICE_EXTENT_3857
  return createXYZ({ extent, tileSize: ICE_TILE_SIZE, maxZoom: ICE_MAX_ZOOM })
}

/** 冰情瓦片 URL(相对路径,经 dev 代理/nginx 的 /api 前缀;日期必须入 URL)。 */
export function buildIceTileUrl(field: IceFieldId, crs: string, date: string): string {
  const base = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE_URL || '/api/v1'
  return `${base}/ice/${field}/${crs}/tile/{z}/{x}/{y}.png?date=${date}`
}

/** 字段在指定日期是否有真实数据(只认后端扫描出的实际日期列表)。 */
export function iceFieldAvailable(
  info: IceInfo | null,
  field: IceFieldId,
  date: string | null,
): boolean {
  if (!info || !date) return false
  const fieldInfo = info.fields.find((item) => item.id === field)
  return Boolean(fieldInfo && fieldInfo.availableDates.includes(date))
}

/** '20220101' → '2022-01-01';异常输入原样返回(不构造不存在的格式)。 */
export function formatIceDate(date: string): string {
  if (!/^\d{8}$/.test(date)) return date
  return `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`
}

/** 当前日期在 info.dates 中的数组下标;不存在给 -1(绝不就近取整)。 */
export function iceTimelineIndex(dates: string[], date: string | null): number {
  if (!date) return -1
  return dates.indexOf(date)
}

/** 按数组下标步进日期,首尾钳制;空列表返回 null。 */
export function stepIceDate(dates: string[], current: string | null, delta: number): string | null {
  if (dates.length === 0) return null
  const index = iceTimelineIndex(dates, current)
  const base = index < 0 ? 0 : index
  const next = Math.min(Math.max(base + delta, 0), dates.length - 1)
  return dates[next]
}

/** EPSG:3411 米范围 → 当前显示投影(经 WGS84 中转;为 hover 预筛的近似范围)。 */
export function projectIceExtent(
  extent3411: [number, number, number, number] | null,
  crs: string,
): [number, number, number, number] | null {
  if (!extent3411) return null
  ensureSourceProjection()
  return transformExtent(extent3411, ICE_SOURCE_CRS, crs) as [number, number, number, number]
}

/** 原始值有效性:0 是有效值;null/NaN/无穷/非数字一律无效。 */
export function isIceValueValid(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/** 图例 CSS 渐变:与后端渲染同一组 RGBA 控制点(含 alpha 斜坡)。 */
export function iceLegendGradient(field: IceFieldId): string {
  const stops = ICE_PALETTES[field]
  const max = stops[stops.length - 1].value
  const parts = stops.map((stop) => {
    const [r, g, b, a] = stop.rgba
    const position = ((stop.value / max) * 100).toFixed(1)
    return `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)}) ${position}%`
  })
  return `linear-gradient(90deg, ${parts.join(', ')})`
}
