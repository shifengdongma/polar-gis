/**
 * IceTimeline 关键契约回归防护(源码断言)。
 *
 * 时间轴是"实际存在文件"的纯粹索引视图:
 * - 只使用 info.dates 数组索引,绝不按日期算术推算(禁止 new Date / 手动加减);
 * - 步进按钮在首尾禁用;计数文案为「n / N 个可用日期」;
 * - 左右让位由视图传入(leftOffset/rightOffset),折叠面板后自动扩展,
 *   绝不写死 left/right 像素。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// jsdom 环境下 import.meta.url 为 http 协议,无法用于 fs;vitest cwd 即项目根目录
const source = readFileSync(join(process.cwd(), 'src/components/IceTimeline.vue'), 'utf-8')

describe('IceTimeline 索引驱动', () => {
  it('日期步进/选择全部走数组索引事件,不做日期算术', () => {
    expect(source).toContain("emit('step'")
    expect(source).toContain("emit('select'")
    expect(source).not.toContain('new Date(')
    expect(source).not.toContain('setDate(')
  })

  it('range 输入以索引为值(dates.length - 1 为上限)', () => {
    expect(source).toContain('min="0"')
    expect(source).toContain(':max="Math.max(0, dates.length - 1)"')
    expect(source).toContain('step="1"')
  })

  it('上一/下一按钮在首尾禁用', () => {
    expect(source).toContain(':disabled="currentIndex <= 0"')
    expect(source).toContain(':disabled="currentIndex >= dates.length - 1"')
  })

  it('显示当前日期与「n / N 个可用日期」,不构造文件名', () => {
    expect(source).toContain('formatIceDate(')
    expect(source).toContain('个可用日期')
    expect(source).not.toContain('.nc')
  })
})

describe('IceTimeline 布局让位', () => {
  it('左右让位由 props 注入,不得写死像素', () => {
    expect(source).toContain('leftOffset')
    expect(source).toContain('rightOffset')
    expect(source).toContain('leftOffset + \'px\'')
    expect(source).not.toContain('left: 400px')
    expect(source).not.toContain('right: 540px')
  })

  it('class 统一 ice- 前缀', () => {
    expect(source).toContain('ice-timeline')
  })
})
