/**
 * useRouteDrawing 关键契约回归防护(源码断言)。
 *
 * 组合式函数强依赖真实 OpenLayers 地图实例,本项目没有组件级挂载测试的先例
 * (见 RoutePlannerPanel.test.ts 说明),这里沿用源码断言守护两条不可回退的契约:
 * 1. pickRouteAtPixel **不得有任何选择门控**——航路点选必须随时可用,
 *    曾经的双重门控(isSelectionEnabled + 视图 singleclick 分支)会让
 *    面板折叠后点击航线无任何反应;
 * 2. fitRoute 的让位 padding 必须可由视图按面板折叠状态动态注入,
 *    折叠两侧窗口后「定位整条航路」才能利用完整地图大屏。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// jsdom 环境下 import.meta.url 为 http 协议,无法用于 fs;vitest cwd 即项目根目录
const source = readFileSync(join(process.cwd(), 'src/composables/useRouteDrawing.ts'), 'utf-8')

describe('useRouteDrawing 选线门控与定位让位', () => {
  it('pickRouteAtPixel 不得有任何选择门控(随时可点选)', () => {
    expect(source).not.toContain('isSelectionEnabled')
  })

  it('fitRoute 的让位 padding 由视图按面板折叠状态动态注入', () => {
    const body = source.match(/function fitRoute\([\s\S]*?\n  \}/)?.[0] ?? ''
    expect(body).not.toBe('')
    expect(body).toContain('getFitPadding')
    expect(body).toContain('ROUTE_FIT_PADDING')
  })

  it('默认让位 padding 保持「两面板均打开」时的取值(未注入时向后兼容)', () => {
    expect(source).toContain('const ROUTE_FIT_PADDING: [number, number, number, number] = [90, 550, 90, 420]')
  })
})
