import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  join(process.cwd(), 'src/components/S57ThematicDialog.vue'),
  'utf-8',
)

describe('S57ThematicDialog', () => {
  it('offers real depth/hazard extraction controls and honest completeness labels', () => {
    expect(source).toContain('S-57 专题数据提取（水深 / 危险物）')
    expect(source).toContain('项目全部有效数据')
    expect(source).toContain('当前视口')
    expect(source).toContain('对象类')
    expect(source).toContain('提取并保存')
    expect(source).toContain('截断/不完整')
    expect(source).not.toContain('不是经过安全论证')
    expect(source).not.toContain('不等于保证安全水深')
    expect(source).toContain('append-to-body')
  })

  it('previews only a sample and keeps the waterway snapshot separate', () => {
    expect(source).toContain('在图上预览样例')
    expect(source).toContain('样例预览')
    expect(source).not.toContain('非完整成果')
    expect(source).not.toContain('waterways.createSnapshot')
    expect(source).not.toContain('waterways.showOverview')
  })

  it('shows source cells/datasets, counts and manifest warnings', () => {
    expect(source).toContain('sourceCells')
    expect(source).toContain('selectedDatasets')
    expect(source).toContain('selectedExtractableLayerCount')
    expect(source).toContain('manifest.warnings')
    expect(source).toContain('truncationReasons')
  })
})
