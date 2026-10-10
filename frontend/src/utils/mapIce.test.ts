/**
 * 冰情纯逻辑单测 —— 瓦片网格/URL/可用性/时间轴索引/投影/调色板。
 *
 * 独立推导期望值,不复刻实现内部结构;调色板与后端
 * backend/app/services/ice.py 的 PALETTE_STOPS 逐值锁定(两侧测试互为镜像)。
 */
import { describe, expect, it } from 'vitest'
import proj4 from 'proj4'
import { get as getProjection } from 'ol/proj'
import { register } from 'ol/proj/proj4'
import {
  ICE_MAX_ZOOM,
  ICE_PALETTES,
  ICE_TILE_SIZE,
  buildIceTileUrl,
  createIceTileGrid,
  formatIceDate,
  iceFieldAvailable,
  iceLegendGradient,
  iceTimelineIndex,
  isIceValueValid,
  projectIceExtent,
  stepIceDate,
} from './mapIce'
import type { IceInfo } from '../types'

// EPSG:3413 只在 MapWorkspaceView.vue 模块作用域注册,测试环境需在此重复
// (与 mapMeasure/mapRoute 测试同一先例);3411 由 mapIce 自身按需注册。
proj4.defs('EPSG:3413', '+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +datum=WGS84 +units=m +no_defs')
register(proj4)
getProjection('EPSG:3413')?.setExtent([-4194304, -4194304, 4194304, 4194304])

function makeInfo(overrides?: Partial<IceInfo>): IceInfo {
  return {
    dates: ['20220101', '20220105', '20220108'],
    fields: [
      {
        id: 'concentration',
        name: 'sic_merged',
        label: '海冰密集度',
        units: '%',
        available: true,
        availableDates: ['20220101', '20220105'],
      },
    ],
    defaultDate: '20220101',
    source: 'netcdf',
    sourceCrs: 'EPSG:3411',
    extent: [-2655329.3, -2492709.3, 2904169.9, 2256290.9],
    missingDatesAreExcluded: true,
    ...overrides,
  }
}

describe('冰情瓦片网格', () => {
  it('3413 使用与后端 _png 一致的 ±4194304 网格,256 像素,最大 zoom 10', () => {
    const grid = createIceTileGrid('EPSG:3413')
    expect(grid.getExtent()).toEqual([-4194304, -4194304, 4194304, 4194304])
    expect(grid.getTileSize(0)).toBe(ICE_TILE_SIZE)
    expect(grid.getMaxZoom()).toBe(ICE_MAX_ZOOM)
    // 瓦片原点在左上角(与后端 gy 递减的瓦片数学一致)
    const origin = grid.getOrigin(0)
    expect(origin[0]).toBeCloseTo(-4194304)
    expect(origin[1]).toBeCloseTo(4194304)
  })

  it('3857 使用标准 Web 墨卡托 extent', () => {
    const grid = createIceTileGrid('EPSG:3857')
    const half = Math.PI * 6378137
    expect(grid.getExtent()[0]).toBeCloseTo(-half, 3)
    expect(grid.getExtent()[3]).toBeCloseTo(half, 3)
  })
})

describe('冰情瓦片 URL', () => {
  it('包含字段、投影、日期与 {z}/{x}/{y}.png 模板', () => {
    const url = buildIceTileUrl('concentration', 'EPSG:3413', '20220105')
    expect(url).toContain('/ice/concentration/EPSG:3413/tile/{z}/{x}/{y}.png')
    expect(url).toContain('date=20220105')
  })

  it('厚度字段同样成立', () => {
    const url = buildIceTileUrl('thickness', 'EPSG:3857', '20220101')
    expect(url).toContain('/ice/thickness/EPSG:3857/tile/')
    expect(url).toContain('date=20220101')
  })
})

describe('字段可用性(只认实际日期)', () => {
  it('字段在该日期存在才可用;缺失日期/字段/信息一律不可用', () => {
    const info = makeInfo()
    expect(iceFieldAvailable(info, 'concentration', '20220101')).toBe(true)
    expect(iceFieldAvailable(info, 'concentration', '20220108')).toBe(false) // 该日无数据
    expect(iceFieldAvailable(info, 'thickness', '20220101')).toBe(false) // 样例无厚度
    expect(iceFieldAvailable(info, 'concentration', null)).toBe(false)
    expect(iceFieldAvailable(null, 'concentration', '20220101')).toBe(false)
  })
})

describe('时间轴索引(绝不按日期算术推算)', () => {
  const dates = ['20220101', '20220105', '20220108']

  it('formatIceDate 输出 YYYY-MM-DD;异常输入原样返回', () => {
    expect(formatIceDate('20220101')).toBe('2022-01-01')
    expect(formatIceDate('odd')).toBe('odd')
  })

  it('索引查找:存在给下标,不存在给 -1', () => {
    expect(iceTimelineIndex(dates, '20220105')).toBe(1)
    expect(iceTimelineIndex(dates, '20220103')).toBe(-1) // 不存在的日期绝不"就近"
    expect(iceTimelineIndex(dates, null)).toBe(-1)
  })

  it('步进使用数组下标,边界钳制在首尾', () => {
    expect(stepIceDate(dates, '20220101', 1)).toBe('20220105') // 跳到下一个实际日期
    expect(stepIceDate(dates, '20220105', -1)).toBe('20220101')
    expect(stepIceDate(dates, '20220101', -1)).toBe('20220101') // 首端钳制
    expect(stepIceDate(dates, '20220108', 1)).toBe('20220108') // 末端钳制
    expect(stepIceDate(dates, '20220103', 1)).toBe('20220105') // 未知当前值 → 从头部起算
    expect(stepIceDate([], '20220101', 1)).toBeNull()
    expect(stepIceDate(dates, null, 1)).toBe('20220105')
  })
})

describe('冰情范围投影(3411 → 当前显示投影,经 WGS84 中转)', () => {
  const extent3411: [number, number, number, number] = [
    -2655329.3, -2492709.3, 2904169.9, 2256290.9,
  ]

  it('null 输入返回 null', () => {
    expect(projectIceExtent(null, 'EPSG:3413')).toBeNull()
  })

  it.each(['EPSG:3413', 'EPSG:3857'] as const)('%s 下范围经度跨零且与源米值不同', (crs) => {
    const projected = projectIceExtent(extent3411, crs)
    expect(projected).not.toBeNull()
    const [minX, minY, maxX, maxY] = projected!
    expect(minX).toBeLessThan(0)
    expect(maxX).toBeGreaterThan(0)
    // 源数据全在北半球:3857 下 y 恒为正;3413(极点居中)下 y 跨零
    if (crs === 'EPSG:3857') {
      expect(minY).toBeGreaterThan(0)
      expect(maxY).toBeGreaterThan(minY)
    } else {
      expect(minY).toBeLessThan(0)
      expect(maxY).toBeGreaterThan(0)
    }
    // 3411(Hughes)≠ 3413(WGS84)/3857:绝不原样透传
    expect(Math.abs(minX - extent3411[0])).toBeGreaterThan(1)
  })
})

describe('原始值有效性(0 是有效值)', () => {
  it.each([
    [0, true],
    [63.5, true],
    [100, true],
    [null, false],
    [Number.NaN, false],
    [Number.POSITIVE_INFINITY, false],
    ['5', false],
    [undefined, false],
  ])('isIceValueValid(%s) === %s', (input, expected) => {
    expect(isIceValueValid(input)).toBe(expected)
  })
})

describe('调色板与图例(与后端 PALETTE_STOPS 逐值一致)', () => {
  it('密集度 11 个控制点,0% alpha 为 0', () => {
    const stops = ICE_PALETTES.concentration
    expect(stops.map((s) => s.value)).toEqual([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1])
    expect(stops[0].rgba).toEqual([218, 246, 249, 0])
    expect(stops[5].rgba).toEqual([25, 94, 145, 225])
    expect(stops[10].rgba).toEqual([171, 36, 66, 250])
  })

  it('厚度 5 个控制点,0 alpha 为 0', () => {
    const stops = ICE_PALETTES.thickness
    expect(stops.map((s) => s.value)).toEqual([0, 0.5, 1.5, 3, 5])
    expect(stops[0].rgba).toEqual([255, 246, 214, 0])
    expect(stops[4].rgba).toEqual([142, 36, 95, 250])
  })

  it('图例渐变为同一组色值(含 alpha),不是生硬色块', () => {
    const concentration = iceLegendGradient('concentration')
    expect(concentration.startsWith('linear-gradient(90deg')).toBe(true)
    expect(concentration).toContain('rgba(218, 246, 249, 0.000)')
    expect(concentration).toContain('rgba(171, 36, 66,')
    expect(concentration.split('rgba(').length - 1).toBe(11)
    const thickness = iceLegendGradient('thickness')
    expect(thickness.split('rgba(').length - 1).toBe(5)
  })
})
