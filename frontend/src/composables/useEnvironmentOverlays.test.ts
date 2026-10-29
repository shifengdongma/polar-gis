/**
 * useEnvironmentOverlays 首载/重试契约回归防护。
 *
 * 组合式函数强依赖真实 OpenLayers 地图实例，沿用项目既有源码断言方式：
 * 1. 地图构建完成前用户已开启的图层，attach() 必须重新应用 visible/opacity；
 * 2. 重复 loadSources() 不得并发执行，失败后由面板打开触发重试；
 * 3. 首次加载失败不得清空已加载的 sources。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  join(process.cwd(), 'src/composables/useEnvironmentOverlays.ts'),
  'utf-8',
)

describe('useEnvironmentOverlays 首载与重试', () => {
  it('attach 重新应用地图构建前选择的图层状态', () => {
    expect(source).toContain('layer.setVisible(layers[field].visible)')
    expect(source).toContain('layer.setOpacity(layers[field].opacity)')
    expect(source).toContain('refreshAll()')
  })

  it('loadSources 并发保护并记录首次加载完成', () => {
    expect(source).toContain('if (sourcesLoading.value) return')
    expect(source).toContain('sourcesLoaded.value = true')
  })

  it('失败时保留已加载的 sources，供面板重试', () => {
    expect(source).not.toContain('sources.value = []')
    expect(source).toContain('sourcesError.value = apiErrorMessage')
  })
})
