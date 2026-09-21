import { describe, expect, it } from 'vitest'
import type { FeatureLike } from 'ol/Feature'
import { get as getProjection, toLonLat } from 'ol/proj'
import { register } from 'ol/proj/proj4'
import type CircleStyle from 'ol/style/Circle'
import type { Style } from 'ol/style'
import type { StyleFunction } from 'ol/style/Style'
import proj4 from 'proj4'
import type { RouteDraft, RoutePoint } from '../types'
import {
  ROUTE_COLOR_POOL,
  ROUTE_END_COLOR,
  ROUTE_MIN_POINTS,
  ROUTE_START_COLOR,
  ROUTE_VIA_COLOR,
  buildRouteFeature,
  buildRouteLineString,
  calculateRouteLength,
  coordinatesEqual,
  createId,
  createRoutePointStyles,
  createRouteStyle,
  longitudeDelta,
  normalizeLongitude,
  normalizeRoutePoints,
  parseRouteCoordinateText,
  projectedCoordinatesToRoutePoints,
  routeColor,
  routePointRole,
  routePointRoleLabel,
  routePointsToProjectedCoordinates,
  shiftExtentIntoProjection,
  unwrapLongitudes,
  validateRouteCoordinate,
  validateRoutePoints,
} from './mapRoute'

// EPSG:3413 只在 MapWorkspaceView.vue 模块作用域注册,测试环境无全局注册 ——
// 此处有意重复同样的 proj4 定义,保证 3413 变换在测试中真实可用。
proj4.defs('EPSG:3413', '+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +datum=WGS84 +units=m +no_defs')
register(proj4)
getProjection('EPSG:3413')?.setExtent([-4194304, -4194304, 4194304, 4194304])

function makePoints(coords: [number, number][]): RoutePoint[] {
  return coords.map(([lon, lat], index) => ({ id: `p-${index}`, seq: index + 1, lon, lat }))
}

function makeRoute(id: string, coords: [number, number][]): RouteDraft {
  return {
    id,
    projectId: 'proj-1',
    name: `航路 ${id}`,
    points: makePoints(coords),
    visible: true,
    createdAt: '2026-09-16T00:00:00Z',
    updatedAt: '2026-09-16T00:00:00Z',
  }
}

describe('validateRouteCoordinate / validateRoutePoints', () => {
  it.each([
    [0, 0],
    [180, 90],
    [-180, -90],
    [120.123456, 72.123456],
  ])('合法坐标 %i,%i', (lon, lat) => {
    expect(validateRouteCoordinate(lon, lat).ok).toBe(true)
  })

  it.each([
    [181, 0, '经度'],
    [-181, 0, '经度'],
    [0, 91, '纬度'],
    [0, -91, '纬度'],
    [NaN, 0, '有限数字'],
    [0, NaN, '有限数字'],
    [Infinity, 0, '有限数字'],
    [0, -Infinity, '有限数字'],
  ])('非法坐标 %s,%s → 提示包含 %s', (lon, lat, hint) => {
    const check = validateRouteCoordinate(lon, lat)
    expect(check.ok).toBe(false)
    if (!check.ok) expect(check.error).toContain(hint)
  })

  it('非数字/空值一律拒绝', () => {
    expect(validateRouteCoordinate('120', 0).ok).toBe(false)
    expect(validateRouteCoordinate(null, 0).ok).toBe(false)
    expect(validateRouteCoordinate(undefined, undefined).ok).toBe(false)
    expect(validateRouteCoordinate(120, undefined).ok).toBe(false)
  })

  it('少于两个航路点拒绝', () => {
    expect(validateRoutePoints([]).ok).toBe(false)
    const check = validateRoutePoints(makePoints([[120, 72]]))
    expect(check.ok).toBe(false)
    if (!check.ok) expect(check.error).toBe('航路至少需要两个航路点')
  })

  it('含非法点的航路拒绝', () => {
    const check = validateRoutePoints(makePoints([[120, 72], [999, 73]]))
    expect(check.ok).toBe(false)
  })

  it('两个合法点通过', () => {
    expect(validateRoutePoints(makePoints([[120, 72], [122, 73]])).ok).toBe(true)
  })
})

describe('parseRouteCoordinateText', () => {
  it('三行坐标解析为 3 个航路点', () => {
    const { points, errors } = parseRouteCoordinateText('120,72\n122,73\n125,74')
    expect(errors).toEqual([])
    expect(points).toHaveLength(3)
    expect(points.map((p) => p.seq)).toEqual([1, 2, 3])
    expect(points[0]).toMatchObject({ lon: 120, lat: 72 })
    expect(points[2]).toMatchObject({ lon: 125, lat: 74 })
  })

  it('非法行给出带行号的明确错误,且不产生该点', () => {
    const { points, errors } = parseRouteCoordinateText('120,72\nabc,1\n122,73')
    expect(points).toHaveLength(2)
    expect(errors).toEqual(['第 2 行坐标格式错误(应为 经度,纬度)'])
  })

  it('缺 token / 纬度越界分别报错', () => {
    expect(parseRouteCoordinateText('120\n122,73').errors).toEqual(['第 1 行坐标格式错误(应为 经度,纬度)'])
    expect(parseRouteCoordinateText('120,91\n122,73').errors).toEqual(['第 1 行坐标格式错误(应为 经度,纬度)'])
    expect(parseRouteCoordinateText('120,72,1\n122,73').errors).toEqual(['第 1 行坐标格式错误(应为 经度,纬度)'])
  })

  it('跳过空行与 # 注释,行号按原始文本计算', () => {
    const { points, errors } = parseRouteCoordinateText('# 注释\n120,72\n\n122,73\nbad-line')
    expect(points).toHaveLength(2)
    expect(errors).toEqual(['第 5 行坐标格式错误(应为 经度,纬度)'])
  })

  it('兼容空格 / 分号分隔(每行一个点)', () => {
    const { points, errors } = parseRouteCoordinateText('120 72\n122;73')
    expect(errors).toEqual([])
    expect(points).toHaveLength(2)
    expect(points[0]).toMatchObject({ lon: 120, lat: 72 })
    expect(points[1]).toMatchObject({ lon: 122, lat: 73 })
  })
})

describe('buildRouteLineString(3857 / 3413)', () => {
  it.each(['EPSG:3857', 'EPSG:3413'] as const)('%s: N 点输入 → N 点几何', (crs) => {
    const geometry = buildRouteLineString(makePoints([[120, 72], [122, 73], [125, 74]]), crs)
    expect(geometry).not.toBeNull()
    expect(geometry!.getCoordinates()).toHaveLength(3)
  })

  it.each(['EPSG:3857', 'EPSG:3413'] as const)('%s: [lon,lat] 顺序正确,不交换经纬度', (crs) => {
    const geometry = buildRouteLineString(makePoints([[120, 72]]), crs)
    expect(geometry).toBeNull() // 单点 → null
    const line = buildRouteLineString(makePoints([[120, 72], [122, 73]]), crs)!
    const back = toLonLat(line.getCoordinates()[0]!, crs)
    expect(longitudeDelta(back[0]!, 120)).toBeLessThan(1e-9)
    expect(Math.abs(back[1]! - 72)).toBeLessThan(1e-9)
  })

  it('不足两个点返回 null', () => {
    expect(buildRouteLineString([], 'EPSG:3857')).toBeNull()
    expect(buildRouteLineString(makePoints([[120, 72]]), 'EPSG:3857')).toBeNull()
  })

  it('按 seq 排序构建(输入乱序不影响几何顺序)', () => {
    const unsorted = [
      { id: 'c', seq: 3, lon: 125, lat: 74 },
      { id: 'a', seq: 1, lon: 120, lat: 72 },
      { id: 'b', seq: 2, lon: 122, lat: 73 },
    ]
    const geometry = buildRouteLineString(unsorted, 'EPSG:3857')!
    const first = toLonLat(geometry.getCoordinates()[0]!, 'EPSG:3857')
    expect(longitudeDelta(first[0]!, 120)).toBeLessThan(1e-9)
  })
})

describe('投影 round-trip(4326 → crs → 4326)', () => {
  it.each(['EPSG:3857', 'EPSG:3413'] as const)('%s: 经纬度基本一致', (crs) => {
    const original = makePoints([[120, 72], [122, 73], [125, 74]])
    const projected = routePointsToProjectedCoordinates(original, crs)
    const restored = projectedCoordinatesToRoutePoints(projected, crs)
    expect(restored).toHaveLength(original.length)
    for (let i = 0; i < original.length; i++) {
      expect(longitudeDelta(restored[i]!.lon, original[i]!.lon)).toBeLessThan(1e-9)
      expect(Math.abs(restored[i]!.lat - original[i]!.lat)).toBeLessThan(1e-9)
    }
  })

  it('回写坐标永远落在合法范围内', () => {
    const restored = projectedCoordinatesToRoutePoints([[2.1e7, 1.1e7]], 'EPSG:3857')
    expect(restored).toHaveLength(1)
    expect(restored[0]!.lon).toBeGreaterThanOrEqual(-180)
    expect(restored[0]!.lon).toBeLessThanOrEqual(180)
    expect(restored[0]!.lat).toBeGreaterThanOrEqual(-90)
    expect(restored[0]!.lat).toBeLessThanOrEqual(90)
  })
})

describe('跨 180° 经线', () => {
  it('unwrap 后相邻经度差 ≤ 180', () => {
    expect(unwrapLongitudes(makePoints([[179, 72], [-179, 72]]))).toEqual([179, 181])
    expect(unwrapLongitudes(makePoints([[-179, 72], [179, 72]]))).toEqual([-179, -181])
  })

  it('EPSG:3857: 179→-179 不产生全球长连线', () => {
    const geometry = buildRouteLineString(makePoints([[179, 72], [-179, 72]]), 'EPSG:3857')!
    const [first, second] = geometry.getCoordinates()
    expect(second![0]! - first![0]!).toBeGreaterThan(0)
    expect(second![0]! - first![0]!).toBeLessThan(1e6) // 2° 经度 ≈ 22 万米,远小于半个世界宽
  })

  it('EPSG:3857: round-trip 还原原始 ±180 内的经度', () => {
    const original = makePoints([[179, 72], [-179, 72]])
    const geometry = buildRouteLineString(original, 'EPSG:3857')!
    const restored = projectedCoordinatesToRoutePoints(geometry.getCoordinates(), 'EPSG:3857')
    expect(restored).toHaveLength(2)
    expect(longitudeDelta(restored[0]!.lon, 179)).toBeLessThan(1e-9)
    expect(longitudeDelta(restored[1]!.lon, -179)).toBeLessThan(1e-9)
  })

  it('EPSG:3413: 极地投影下跨日期变更线天然连续', () => {
    const geometry = buildRouteLineString(makePoints([[179, 72], [-179, 72]]), 'EPSG:3413')!
    const [first, second] = geometry.getCoordinates()
    const distance = Math.hypot(second![0]! - first![0]!, second![1]! - first![1]!)
    expect(distance).toBeLessThan(1e6) // 2° 经度差在极地投影下只有约 8.7 万米
  })
})

describe('calculateRouteLength', () => {
  it('赤道 1° ≈ 111.19 km', () => {
    const meters = calculateRouteLength(makePoints([[0, 0], [1, 0]]))
    expect(meters).toBeGreaterThan(111000)
    expect(meters).toBeLessThan(111400)
  })

  it('跨 180° 的 2° 航路是短弧而非全球长线', () => {
    const meters = calculateRouteLength(makePoints([[179, 0], [-179, 0]]))
    expect(meters).toBeGreaterThan(220000)
    expect(meters).toBeLessThan(225000)
  })

  it('少于两个点返回 0', () => {
    expect(calculateRouteLength([])).toBe(0)
    expect(calculateRouteLength(makePoints([[120, 72]]))).toBe(0)
  })
})

describe('routeColor / createId', () => {
  it('同一 routeId 颜色稳定,不同 id 落在颜色池内', () => {
    expect(routeColor('route-a')).toBe(routeColor('route-a'))
    expect(routeColor('route-a')).toBe(routeColor('route-a'))
    for (const id of ['route-a', 'route-b', 'route-c', 'route-d']) {
      expect(ROUTE_COLOR_POOL).toContain(routeColor(id))
    }
  })

  it('createId 生成非空唯一字符串', () => {
    const a = createId()
    const b = createId()
    expect(a).toBeTruthy()
    expect(b).toBeTruthy()
    expect(a).not.toBe(b)
  })
})

describe('createRouteStyle', () => {
  function buildStyleFn(overrides: {
    visible?: (id: string) => boolean
    active?: (id: string) => boolean
    editing?: (id: string) => boolean
  } = {}): StyleFunction {
    return createRouteStyle({
      isRouteVisible: overrides.visible ?? (() => true),
      isRouteActive: overrides.active ?? ((id) => id === 'A'),
      isRouteEditing: overrides.editing ?? (() => false),
    })
  }

  const routeA = makeRoute('A', [[120, 72], [122, 73]])
  const routeB = makeRoute('B', [[125, 74], [127, 75]])
  const routeC = makeRoute('C', [[130, 70], [132, 71]])
  const featureA = buildRouteFeature(routeA, 'EPSG:3857')!
  const featureB = buildRouteFeature(routeB, 'EPSG:3857')!
  const featureC = buildRouteFeature(routeC, 'EPSG:3857')!

  it('隐藏航路样式返回空值,A/C 保持显示', () => {
    const styleFn = buildStyleFn({ visible: (id) => id !== 'B' })
    expect(styleFn(featureB as FeatureLike, 0)).toBeFalsy()
    expect(styleFn(featureA as FeatureLike, 0)).toBeTruthy()
    expect(styleFn(featureC as FeatureLike, 0)).toBeTruthy()
  })

  it('选中航路线宽大于普通航路', () => {
    const styleFn = buildStyleFn()
    const activeStyles = styleFn(featureA as FeatureLike, 0) as Style[]
    const normalStyles = styleFn(featureC as FeatureLike, 0) as Style[]
    const activeWidth = activeStyles[1]!.getStroke()!.getWidth()!
    const normalWidth = normalStyles[1]!.getStroke()!.getWidth()!
    expect(activeWidth).toBeGreaterThan(normalWidth)
  })

  it('编辑中的航路使用虚线样式', () => {
    const styleFn = buildStyleFn({ editing: (id) => id === 'A' })
    const styles = styleFn(featureA as FeatureLike, 0) as Style[]
    expect(styles[1]!.getStroke()!.getLineDash()).toEqual([8, 6])
  })

  it('选中(非编辑)航路叠加全部航路点标记', () => {
    const styleFn = buildStyleFn()
    const styles = styleFn(featureA as FeatureLike, 0) as Style[]
    expect(styles).toHaveLength(4) // halo + 主线 + 起点标记 + 终点标记(2 点航路无途经点)
  })

  it('未选中航路也带起点 / 终点方向标记,但不显示途经点', () => {
    const styleFn = buildStyleFn()
    const styles = styleFn(featureC as FeatureLike, 0) as Style[] // C 未选中
    expect(styles).toHaveLength(4) // halo + 主线 + 起点 + 终点
    const colors = styles.slice(2).map((style) => (style.getImage() as unknown as CircleStyle).getFill()?.getColor())
    expect(colors).toEqual([ROUTE_START_COLOR, ROUTE_END_COLOR])
  })

  it('编辑中航路仍标明方向(起点 / 终点标记保留)', () => {
    const styleFn = buildStyleFn({ editing: (id) => id === 'A' })
    const styles = styleFn(featureA as FeatureLike, 0) as Style[]
    const colors = styles.slice(2).map((style) => (style.getImage() as unknown as CircleStyle).getFill()?.getColor())
    expect(colors).toEqual([ROUTE_START_COLOR, ROUTE_END_COLOR])
  })

  it('无 routeId 的要素不渲染', () => {
    const styleFn = buildStyleFn()
    const stray = buildRouteFeature(routeA, 'EPSG:3857')!
    stray.unset('routeId')
    expect(styleFn(stray as FeatureLike, 0)).toBeFalsy()
  })
})

describe('routePointRole / routePointRoleLabel', () => {
  it('空航路无角色可言', () => {
    expect(routePointRole(makePoints([]), 0)).toBe('invalid')
  })

  it('单点航路首点即起点也是终点(优先显示起点)', () => {
    expect(routePointRole(makePoints([[120, 72]]), 0)).toBe('start')
  })

  it('多点航路:首点=起点、末点=终点、其余=途经', () => {
    const points = makePoints([[120, 72], [122, 73], [125, 74], [127, 75]])
    expect(routePointRole(points, 0)).toBe('start')
    expect(routePointRole(points, 1)).toBe('via')
    expect(routePointRole(points, 2)).toBe('via')
    expect(routePointRole(points, 3)).toBe('end')
  })

  it('两个航路点:起点 + 终点,无途经点', () => {
    const points = makePoints([[120, 72], [122, 73]])
    expect(points.map((_, index) => routePointRole(points, index))).toEqual(['start', 'end'])
  })

  it('角色由 seq(航路方向)决定,而非数组下标', () => {
    // 数组顺序被打乱,seq 才是方向真值
    const points: RoutePoint[] = [
      { id: 'c', seq: 3, lon: 125, lat: 74 },
      { id: 'a', seq: 1, lon: 120, lat: 72 },
      { id: 'b', seq: 2, lon: 122, lat: 73 },
    ]
    expect(routePointRole(points, 1)).toBe('start') // 数组下标 1 但 seq=1
    expect(routePointRole(points, 0)).toBe('end') // 数组下标 0 但 seq=3
    expect(routePointRole(points, 2)).toBe('via') // seq=2
  })

  it('下标越界返回 invalid', () => {
    const points = makePoints([[120, 72], [122, 73]])
    expect(routePointRole(points, 2)).toBe('invalid')
    expect(routePointRole(points, -1)).toBe('invalid')
  })

  it('中文标注:起点 / 终点 / 途经', () => {
    expect(routePointRoleLabel('start')).toBe('起点')
    expect(routePointRoleLabel('end')).toBe('终点')
    expect(routePointRoleLabel('via')).toBe('途经')
    expect(routePointRoleLabel('invalid')).toBe('')
  })
})

describe('createRoutePointStyles(起点 / 途经 / 终点 标记)', () => {
  // 用类投影量级的坐标,避免与 unwrap 边界纠缠
  const projected = [
    [1.3e7, 1.0e7],
    [1.31e7, 1.01e7],
    [1.32e7, 1.02e7],
    [1.33e7, 1.03e7],
  ]

  function markerColor(style: Style): unknown {
    const image = style.getImage() as unknown as CircleStyle | null
    return image ? (image.getFill()?.getColor() ?? null) : null
  }

  /** 标记几何恒为 Point;Style.getGeometry() 的联合类型需收窄后才能取坐标 */
  function markerCoordinates(style: Style): number[] | undefined {
    const geometry = style.getGeometry() as unknown as { getCoordinates: () => number[] } | undefined
    return geometry?.getCoordinates()
  }

  it('每个航路点一个标记', () => {
    expect(createRoutePointStyles('A', projected)).toHaveLength(projected.length)
  })

  it('起点 / 途经 / 终点 三色互不相同,且起点终点颜色按角色固定', () => {
    const styles = createRoutePointStyles('A', projected)
    const colors = styles.map(markerColor)
    expect(colors[0]).toBe(ROUTE_START_COLOR)
    expect(colors[1]).toBe(ROUTE_VIA_COLOR)
    expect(colors[2]).toBe(ROUTE_VIA_COLOR)
    expect(colors[3]).toBe(ROUTE_END_COLOR)
    expect(new Set([ROUTE_START_COLOR, ROUTE_VIA_COLOR, ROUTE_END_COLOR]).size).toBe(3)
    expect(ROUTE_START_COLOR).not.toBe(ROUTE_END_COLOR)
  })

  it('起点终点颜色与航路配色池不同,不会被线路颜色淹没', () => {
    for (const color of ROUTE_COLOR_POOL) {
      expect(ROUTE_START_COLOR).not.toBe(color)
      expect(ROUTE_END_COLOR).not.toBe(color)
    }
  })

  it('标记落在对应航路点的投影坐标上', () => {
    const styles = createRoutePointStyles('A', projected)
    expect(markerCoordinates(styles[0]!)).toEqual(projected[0])
    expect(markerCoordinates(styles[3]!)).toEqual(projected[3])
  })

  it('起点终点半径大于途经点,方向端更醒目', () => {
    const styles = createRoutePointStyles('A', projected)
    const startRadius = (styles[0]!.getImage() as CircleStyle).getRadius()
    const viaRadius = (styles[1]!.getImage() as CircleStyle).getRadius()
    const endRadius = (styles[3]!.getImage() as CircleStyle).getRadius()
    expect(startRadius).toBe(endRadius)
    expect(startRadius).toBeGreaterThan(viaRadius)
  })

  it('颜色不随航路配色变化(同角色恒定)', () => {
    const first = createRoutePointStyles('A', projected)
    const second = createRoutePointStyles('B', projected)
    expect(markerColor(first[0]!)).toBe(markerColor(second[0]!))
    expect(markerColor(first[3]!)).toBe(markerColor(second[3]!))
    expect(routeColor('A')).not.toBe(routeColor('B')) // 前提:两条航路线色确实不同
  })

  it('空坐标返回空数组', () => {
    expect(createRoutePointStyles('A', [])).toEqual([])
  })
})

describe('buildRouteFeature', () => {
  it('携带 routeId / routeName / routeType 属性', () => {
    const feature = buildRouteFeature(makeRoute('A', [[120, 72], [122, 73]]), 'EPSG:3857')
    expect(feature).not.toBeNull()
    expect(feature!.get('routeId')).toBe('A')
    expect(feature!.get('routeName')).toBe('航路 A')
    expect(feature!.get('routeType')).toBe('route-draft')
  })

  it('非法航路(少于 2 点)返回 null', () => {
    expect(buildRouteFeature(makeRoute('A', []), 'EPSG:3857')).toBeNull()
    expect(buildRouteFeature(makeRoute('A', [[120, 72]]), 'EPSG:3857')).toBeNull()
  })
})

describe('coordinatesEqual', () => {
  it('相等 / 不等判断', () => {
    expect(coordinatesEqual([[0, 1]], [[0, 1]])).toBe(true)
    expect(coordinatesEqual([[0, 1]], [[0, 2]])).toBe(false)
    expect(coordinatesEqual([[0, 1], [2, 3]], [[0, 1]])).toBe(false)
  })

  it('投影 round-trip 的浮点误差视为相等', () => {
    expect(coordinatesEqual([[1e7, 1e7]], [[1e7 + 5e-10, 1e7 - 5e-10]])).toBe(true)
    expect(coordinatesEqual([[1e7, 1e7]], [[1e7 + 1, 1e7]])).toBe(false)
  })
})

describe('normalizeRoutePoints / normalizeLongitude', () => {
  it('丢弃非法点、补 id、重排 seq', () => {
    const normalized = normalizeRoutePoints([
      { id: '', seq: 99, lon: 120, lat: 72 },
      { id: 'keep', seq: 1, lon: 122, lat: 73 },
      { id: 'bad', seq: 2, lon: 999, lat: 0 },
    ])
    expect(normalized).toHaveLength(2)
    expect(normalized.map((p) => p.seq)).toEqual([1, 2])
    expect(normalized[0]!.id).toBeTruthy()
    expect(normalized[1]!.id).toBe('keep')
  })

  it('normalizeLongitude 收拢到 ±180', () => {
    expect(normalizeLongitude(181)).toBeCloseTo(-179)
    expect(normalizeLongitude(-181)).toBeCloseTo(179)
    expect(normalizeLongitude(540)).toBe(180)
    expect(normalizeLongitude(179)).toBe(179)
    expect(normalizeLongitude(-180)).toBe(-180)
  })
})

describe('shiftExtentIntoProjection', () => {
  it('3857 范围内 extent 原样返回', () => {
    const extent = [0, 0, 1000, 1000]
    expect(shiftExtentIntoProjection(extent, 'EPSG:3857')).toEqual(extent)
  })

  it('3857 跨 180° 的越界 extent 平移回投影范围内', () => {
    const projectionExtent = getProjection('EPSG:3857')!.getExtent()!
    const width = projectionExtent[2]! - projectionExtent[0]!
    const shifted = shiftExtentIntoProjection([width + 1000, 0, width + 3000, 1000], 'EPSG:3857')
    expect(shifted[0]).toBeGreaterThanOrEqual(projectionExtent[0]!)
    expect(shifted[2]).toBeLessThanOrEqual(projectionExtent[2]!)
    expect(shifted[2]! - shifted[0]!).toBe(2000)
  })

  it('3413 不做平移', () => {
    const extent = [12345, 6789, 23456, 7890]
    expect(shiftExtentIntoProjection(extent, 'EPSG:3413')).toEqual(extent)
  })
})

describe('ROUTE_MIN_POINTS', () => {
  it('最小航路点数为 2', () => {
    expect(ROUTE_MIN_POINTS).toBe(2)
  })
})
