import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  join(process.cwd(), 'src/components/EnvironmentLayerPanel.vue'),
  'utf8',
)
const timeSource = readFileSync(
  join(process.cwd(), 'src/components/EnvironmentTimeControl.vue'),
  'utf8',
)

describe('EnvironmentLayerPanel', () => {
  it('contains time, quality, policy, and all four environment layers', () => {
    expect(source).toContain('EnvironmentTimeControl')
    expect(timeSource).toContain('环境时间（UTC）')
    expect(timeSource).toContain('刷新')
    expect(source).not.toContain('含合成数据')
    expect(source).toContain('研究数据')
    expect(source).toContain('水深（GEBCO）')
    expect(source).toContain('风场（CARRA2）')
    expect(source).toContain('海流（TOPAZ5）')
    expect(source).toContain('海浪（WAM）')
  })

  it('states that ice and risk have separate controls', () => {
    expect(source).toContain('海冰由底部冰情时间轴独立控制')
    expect(source).toContain('风险栅格需先完成规划或区域风险评估')
  })

  it('displays source, matched time, and per-layer error independently', () => {
    expect(source).toContain('matchedLabel')
    expect(source).toContain('environment-layer-error')
    expect(source).toContain('env.layers[field.id].loading')
  })
})
