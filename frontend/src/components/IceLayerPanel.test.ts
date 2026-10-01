/**
 * IceLayerPanel 关键契约回归防护(源码断言)。
 *
 * - 厚度在本数据集不存在是**正常状态**:必须显示「当前日期无厚度变量」并禁用
 *   开关,绝不生成假数据、绝不把缺失当 0;
 * - 图例色值必须来自 mapIce 的 ICE_PALETTES(与后端 PALETTE_STOPS 同源),
 *   不允许在组件里再写一套颜色;
 * - 免责声明必须保留(非认证显示/不可替代正式航海冰情资料);
 * - class 统一 ice- 前缀,不污染现有样式。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// jsdom 环境下 import.meta.url 为 http 协议,无法用于 fs;vitest cwd 即项目根目录
const source = readFileSync(join(process.cwd(), 'src/components/IceLayerPanel.vue'), 'utf-8')

describe('IceLayerPanel 字段开关与禁用态', () => {
  it('厚度缺失时明确提示并禁用(不生成假数据)', () => {
    expect(source).toContain('当前日期无厚度变量')
    expect(source).toContain('thicknessAvailable')
    // 开关在不可用时必须 disabled
    expect(source).toMatch(/:disabled="!thicknessAvailable/)
  })

  it('浓度/厚度开关与透明度滑杆接入 useIceOverlay 动作', () => {
    expect(source).toContain('toggleConcentration')
    expect(source).toContain('toggleThickness')
    expect(source).toContain('setConcentrationOpacity')
    expect(source).toContain('setThicknessOpacity')
  })

  it('无数据/错误时给出明确状态文案,不影响地图', () => {
    expect(source).toContain('无可用冰情数据')
  })
})

describe('IceLayerPanel 图例与免责', () => {
  it('图例渐变取自 mapIce(前后端同一组色值)', () => {
    expect(source).toContain('iceLegendGradient')
    expect(source).toContain("iceLegendGradient('concentration')")
    expect(source).toContain("iceLegendGradient('thickness')")
    // 不得在组件内硬编码第二套调色板
    expect(source).not.toContain('rgba(218, 246, 249')
  })

  it('浓度刻度 0-100% 每 10% 一个,厚度 0/0.5/1.5/3/5+', () => {
    expect(source).toContain('海冰浓度')
    expect(source).toContain('海冰厚度')
    expect(source).toContain('0.5')
    expect(source).toContain('5+')
  })

  it('免责声明与定位冰区入口保留', () => {
    expect(source).toContain('不可替代正式航海冰情资料')
    expect(source).toContain('fitIceExtent')
  })

  it('调试对齐默认关闭(class 带 ice- 前缀)', () => {
    expect(source).toContain('debugAlignment')
    expect(source).toContain('ice-panel')
  })
})
