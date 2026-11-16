import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(join(process.cwd(), 'src/components/S57LayerLegend.vue'), 'utf-8')

describe('S57LayerLegend', () => {
  it('loads the existing legend endpoint lazily and through the cache', () => {
    expect(source).toContain('fetchLayerLegend')
    expect(source).toContain('onMounted(load)')
    expect(source).not.toContain('Promise.all')
  })

  it('shows the real GeoServer image first', () => {
    expect(source).toContain(':src="payload.url"')
    expect(source).toContain('@error="imageFailed = true"')
    expect(source).toContain('naturalWidth')
  })

  it('falls back only to backend presets and never invents a symbol', () => {
    expect(source).toContain('fallback')
    expect(source).toContain('无可用图例/预设符号')
    expect(source).not.toContain('emoji')
  })

  it('uses Chinese object descriptions without safety/disclaimer notices', () => {
    expect(source).toContain('s57ObjectDescription')
    expect(source).toContain('同一类别可能随比例尺/属性变化')
    expect(source).not.toContain('不代表实时航行状态或已验证的安全通道')
  })
})
