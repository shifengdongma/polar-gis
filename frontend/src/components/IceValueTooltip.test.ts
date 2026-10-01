/**
 * IceValueTooltip 关键契约回归防护(源码断言)。
 *
 * 浮窗展示**后端返回的原始网格值**(绝不从 PNG 颜色反推):
 * 值 + 日期 + 经纬度;0 必须原样显示为 0;定位与既有 .map-hover-coord 同模式
 * (像素锚定 + 边缘翻转),指针事件不拦截地图。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(join(process.cwd(), 'src/components/IceValueTooltip.vue'), 'utf-8')
const styles = readFileSync(join(process.cwd(), 'src/styles.css'), 'utf-8')

describe('IceValueTooltip 内容与定位', () => {
  it('展示字段名、原始值(带单位)、格式化日期与经纬度', () => {
    expect(source).toContain('ICE_FIELD_LABELS')
    expect(source).toContain('formatIceDate(')
    expect(source).toContain('经度')
    expect(source).toContain('纬度')
  })

  it('0 是有效值:格式化不做真值判断', () => {
    expect(source).not.toMatch(/if\s*\(\s*!?props\.hover\.value\s*\)/) // 不得对值做真值判断
    expect(source).toContain('Number.isInteger')
  })

  it('像素锚定 + 边缘翻转,与既有坐标提示同模式', () => {
    expect(source).toContain('is-flip-x')
    expect(source).toContain('is-flip-y')
    expect(source).toContain('hover.x')
    expect(source).toContain('hover.y')
  })

  it('浮窗可交互但不吞地图事件(容器保持 pointer-events:none)', () => {
    expect(styles).toMatch(/\.ice-value-tooltip\s*\{[^}]*pointer-events: none/)
  })

  it('位于 .map-overlay-root(打印/截图自动排除)', () => {
    expect(styles).toContain('.map-overlay-root { display: none !important; }')
  })
})
