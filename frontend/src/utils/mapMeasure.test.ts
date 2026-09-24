import { describe, expect, it } from 'vitest'
import LineString from 'ol/geom/LineString'
import Polygon from 'ol/geom/Polygon'
import { get as getProjection, fromLonLat } from 'ol/proj'
import { register } from 'ol/proj/proj4'
import { DEFAULT_RADIUS, getArea } from 'ol/sphere'
import proj4 from 'proj4'
import {
  HOVER_MIN_GROUND_RESOLUTION_METERS,
  buildMeasureGeometry,
  formatMeasureResult,
  hoverDecimalsForGroundResolution,
  measureGeometryToDraft,
  projectedToLonLatSafe,
  sphericalRingArea,
  type MeasureDraft,
} from './mapMeasure'

// EPSG:3413 只在 MapWorkspaceView.vue 模块作用域注册,测试环境无全局注册 ——
// 此处有意重复同样的 proj4 定义,保证 3413 变换在测试中真实可用。
proj4.defs('EPSG:3413', '+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +datum=WGS84 +units=m +no_defs')
register(proj4)
getProjection('EPSG:3413')?.setExtent([-4194304, -4194304, 4194304, 4194304])

/** 解析闭式:纬度 φ 平行圈所围极点帽的面积 2πR²(1 − sin φ) */
function polarCapArea(latitudeDegrees: number): number {
  return 2 * Math.PI * DEFAULT_RADIUS * DEFAULT_RADIUS * (1 - Math.sin((latitudeDegrees * Math.PI) / 180))
}

/** 沿某纬度圈取 n 个等分顶点(不闭合) */
function parallelRing(latitude: number, count: number): number[][] {
  return Array.from({ length: count }, (_, index) => [(index * 360) / count, latitude])
}

describe('sphericalRingArea 与解析真值对照', () => {
  it('720 顶点极点帽应逼近解析解(≤0.01%)', () => {
    for (const latitude of [80, 75, 60]) {
      const area = sphericalRingArea(parallelRing(latitude, 720))
      expect(area).not.toBeNull()
      const truth = polarCapArea(latitude)
      expect(Math.abs(area! - truth) / truth).toBeLessThan(0.0001)
    }
  })

  it('36 顶点极点帽误差应在 0.6% 以内(多边形内接于平行圈,只会偏小)', () => {
    const area = sphericalRingArea(parallelRing(80, 36))
    const truth = polarCapArea(80)
    expect(area!).toBeLessThan(truth)
    expect(Math.abs(area! - truth) / truth).toBeLessThan(0.006)
  })

  it('环绕极点的环必须得到非零面积(ol/sphere.getArea 对这类环恒返回 0 的回归守卫)', () => {
    const ring = [[0, 75], [90, 75], [180, 75], [-90, 75]]
    const area = sphericalRingArea(ring)
    expect(area).not.toBe(0)
    // 大圆弦从平行圈内侧切过,故明显小于同纬度帽(8,690,037 km²)
    expect(area! / 1e6).toBeGreaterThan(5_500_000)
    expect(area! / 1e6).toBeLessThan(5_800_000)
    // 对照:同一输入下 ol/sphere.getArea 返回 0(即修复前的行为)
    expect(getArea(new Polygon([[...ring, ring[0]!]]), { projection: 'EPSG:4326' })).toBe(0)
  })

  it('跨 180° 经线的环与同一地理形状在常规经度下逐位相同', () => {
    const acrossAntimeridian = [[170, 70], [-170, 70], [-170, 76], [170, 76]]
    const normal = [[-10, 70], [10, 70], [10, 76], [-10, 76]]
    const a = sphericalRingArea(acrossAntimeridian)
    const b = sphericalRingArea(normal)
    expect(a).not.toBeNull()
    expect(Math.abs(a! - b!) / b!).toBeLessThan(1e-6)
    // 对照:ol/sphere.getArea 对同一个跨 180° 环偏大约 17 倍
    const olArea = getArea(new Polygon([[...acrossAntimeridian, acrossAntimeridian[0]!]]), { projection: 'EPSG:4326' })
    expect(olArea / b!).toBeGreaterThan(16)
    expect(olArea / b!).toBeLessThan(18)
  })

  it('小多边形与独立实现 ol/sphere.getArea 一致(边模型差异随尺寸趋零)', () => {
    const box = [[10, 70], [10.2, 70], [10.2, 70.2], [10, 70.2]]
    const ours = sphericalRingArea(box)
    const theirs = getArea(new Polygon([[...box, box[0]!]]), { projection: 'EPSG:4326' })
    expect(Math.abs(ours! - theirs) / theirs).toBeLessThan(0.0001)
    // 与平面近似交叉验证:0.2° 纬距 × (0.2° 经距 × cos70.1°)
    const expected = (0.2 * 111320) * (0.2 * 111320 * Math.cos((70.1 * Math.PI) / 180))
    expect(Math.abs(ours! - expected) / expected).toBeLessThan(0.005)
  })

  it('环方向与重复顶点不影响面积', () => {
    const ring = [[10, 70], [30, 70], [30, 76], [10, 76]]
    const reversed = [...ring].reverse()
    expect(sphericalRingArea(reversed)).toBeCloseTo(sphericalRingArea(ring)!, 6)
    const duplicated = [[10, 70], [10, 70], [30, 70], [30, 76], [10, 76]]
    expect(sphericalRingArea(duplicated)).toBeCloseTo(sphericalRingArea(ring)!, 6)
  })

  it('顶点不足 3 个或含非法坐标时返回 null(而不是 0)', () => {
    expect(sphericalRingArea([[10, 70], [30, 70]])).toBeNull()
    expect(sphericalRingArea([])).toBeNull()
    expect(sphericalRingArea([[10, 70], [Number.NaN, 70], [30, 76]])).toBeNull()
    expect(sphericalRingArea([[10, 70], [Number.POSITIVE_INFINITY, 70], [30, 76]])).toBeNull()
  })
})

describe('projectedToLonLatSafe 投影范围判定', () => {
  it('EPSG:3413 合法范围内转换正确', () => {
    const result = projectedToLonLatSafe([0, 0], 'EPSG:3413')
    expect(result).not.toBeNull()
    expect(result![0]).toBeCloseTo(-45, 6) // 投影原点经度即 lon_0
    expect(result![1]).toBeCloseTo(90, 6)
  })

  it('EPSG:3413 投影范围外的坐标必须返回 null(proj4 逆变换不会给 NaN)', () => {
    // 这两点在 proj4 下都会得到「有限但无意义」的经纬度,只能靠范围判断剔除
    expect(projectedToLonLatSafe([5_000_000, 5_000_000], 'EPSG:3413')).toBeNull()
    expect(projectedToLonLatSafe([20_000_000, 20_000_000], 'EPSG:3413')).toBeNull()
  })

  it('EPSG:3857 允许世界副本横向回绕,但纬度带之外返回 null', () => {
    const wrapped = projectedToLonLatSafe([20_148_827.83, 11_068_715.66], 'EPSG:3857')
    expect(wrapped).not.toBeNull()
    expect(wrapped![0]).toBeCloseTo(-179, 4)
    expect(wrapped![1]).toBeCloseTo(70, 4)
    // 墨卡托世界的南北边界之外(±20048966)不显示坐标
    expect(projectedToLonLatSafe([0, 30_000_000], 'EPSG:3857')).toBeNull()
    expect(projectedToLonLatSafe([0, -30_000_000], 'EPSG:3857')).toBeNull()
  })

  it('非有限坐标返回 null', () => {
    expect(projectedToLonLatSafe([Number.NaN, 0], 'EPSG:3857')).toBeNull()
    expect(projectedToLonLatSafe([0, Number.NaN], 'EPSG:3857')).toBeNull()
  })
})

describe('hoverDecimalsForGroundResolution 小数位与地面分辨率匹配', () => {
  it('小数位随地面分辨率提高而增加', () => {
    expect(hoverDecimalsForGroundResolution(2532)).toBe(2)
    expect(hoverDecimalsForGroundResolution(1000)).toBe(2)
    expect(hoverDecimalsForGroundResolution(633)).toBe(2)
    expect(hoverDecimalsForGroundResolution(158)).toBe(2)
    expect(hoverDecimalsForGroundResolution(39.6)).toBe(3)
    expect(hoverDecimalsForGroundResolution(9.9)).toBe(4)
    expect(hoverDecimalsForGroundResolution(0.5)).toBe(5)
  })

  it('小数点后至少 2 位、至多 5 位,非法输入退化为 2 位', () => {
    expect(hoverDecimalsForGroundResolution(1e9)).toBe(2)
    expect(hoverDecimalsForGroundResolution(1e-9)).toBe(5)
    expect(hoverDecimalsForGroundResolution(Number.NaN)).toBe(2)
    expect(hoverDecimalsForGroundResolution(0)).toBe(2)
  })

  it('末位数字代表的地面距离不小于地面分辨率(末位不细于 1 像素)', () => {
    for (const resolution of [1000, 633, 158, 39.6, 9.9, 0.5]) {
      const digits = hoverDecimalsForGroundResolution(resolution)
      const lastDigitMeters = 111320 / Math.pow(10, digits)
      expect(lastDigitMeters).toBeGreaterThanOrEqual(resolution)
    }
  })

  it('提示门槛为 1 km/px 量级(注释所述依据的守卫)', () => {
    expect(HOVER_MIN_GROUND_RESOLUTION_METERS).toBe(1000)
  })
})

describe('测量真值与显示几何的往返', () => {
  const lineDraft: MeasureDraft = { kind: 'LineString', lonLat: [[10, 70], [30, 75], [50, 72]] }

  it.each(['EPSG:3857', 'EPSG:3413'])('%s 下折线往返保持 WGS84 真值', (crs) => {
    const geometry = buildMeasureGeometry(lineDraft, crs)
    expect(geometry).toBeInstanceOf(LineString)
    const back = measureGeometryToDraft(geometry!, crs)
    expect(back).not.toBeNull()
    expect(back!.kind).toBe('LineString')
    back!.lonLat.forEach((coordinate, index) => {
      expect(coordinate[0]).toBeCloseTo(lineDraft.lonLat[index]![0]!, 6)
      expect(coordinate[1]).toBeCloseTo(lineDraft.lonLat[index]![1]!, 6)
    })
  })

  it('多边形往返去掉重复闭合点后再补回', () => {
    const draft: MeasureDraft = { kind: 'Polygon', lonLat: [[10, 70], [30, 70], [30, 76], [10, 76]] }
    const geometry = buildMeasureGeometry(draft, 'EPSG:3413') as Polygon
    expect(geometry).toBeInstanceOf(Polygon)
    expect(geometry.getCoordinates()[0]).toHaveLength(5)
    const back = measureGeometryToDraft(geometry, 'EPSG:3413')
    expect(back!.kind).toBe('Polygon')
    expect(back!.lonLat).toHaveLength(4)
  })

  it('跨 180° 的测量在 3857 下连续化显示(相邻顶点不跳到另一个世界副本)', () => {
    const draft: MeasureDraft = { kind: 'LineString', lonLat: [[179, 70], [-179, 71]] }
    const coordinates = (buildMeasureGeometry(draft, 'EPSG:3857') as LineString).getCoordinates()
    expect(Math.abs(coordinates[1]![0]! - coordinates[0]![0]!)).toBeLessThan(1_000_000)
  })

  it('顶点不足或坐标非法时返回 null', () => {
    expect(buildMeasureGeometry({ kind: 'LineString', lonLat: [[10, 70]] }, 'EPSG:3857')).toBeNull()
    expect(buildMeasureGeometry({ kind: 'Polygon', lonLat: [[10, 70], [30, 70]] }, 'EPSG:3857')).toBeNull()
    const bad = new LineString([fromLonLat([10, 70], 'EPSG:3413'), [Number.NaN, 0]])
    expect(measureGeometryToDraft(bad, 'EPSG:3413')).toBeNull()
  })
})

describe('formatMeasureResult 投影无关性', () => {
  it.each(['EPSG:3857', 'EPSG:3413'])('%s 下文本由 WGS84 真值生成,与投影无关', (crs) => {
    const draft: MeasureDraft = { kind: 'LineString', lonLat: [[10, 70], [30, 75], [50, 72]] }
    const geometry = buildMeasureGeometry(draft, crs)!
    // 显示几何换了个投影,但文本必须一模一样(这正是原实现缺失的性质)
    expect(formatMeasureResult(measureGeometryToDraft(geometry, crs)!)).toBe(formatMeasureResult(draft))
  })

  it('折线给距离(km 与 NM),多边形给面积(不含海里)', () => {
    const line = formatMeasureResult({ kind: 'LineString', lonLat: [[10, 70], [30, 75]] })
    expect(line).toContain('km')
    expect(line).toContain('NM')

    const polygon = formatMeasureResult({ kind: 'Polygon', lonLat: [[10, 70], [30, 70], [30, 76], [10, 76]] })
    expect(polygon).toContain('km²')
    expect(polygon).not.toContain('NM')
    expect(polygon).not.toContain('nmi')
  })
})
