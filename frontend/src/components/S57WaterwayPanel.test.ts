/**
 * Source-level contract tests for the waterway panel, matching the existing
 * IceLayerPanel/EnvironmentLayerPanel convention. Runtime search/overlay logic
 * is covered by useS57Waterways.test.ts and mapS57Waterway.test.ts.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(join(process.cwd(), 'src/components/S57WaterwayPanel.vue'), 'utf-8')

describe('S57WaterwayPanel', () => {
  it('never fabricates a name: delegates to waterwayDisplayName', () => {
    expect(source).toContain('waterwayDisplayName')
    expect(source).not.toContain("item.name || `")
    expect(source).not.toContain('item.name || "')
  })

  it('separates primary classes from auxiliary objects', () => {
    expect(source).toContain('primaryGroups')
    expect(source).toContain('auxiliaryClasses')
    expect(source).toContain('相关辅助要素（不视为航道）')
    expect(source).toContain('辅助要素')
  })

  it('supports keyword, viewport, categories, pagination and explicit actions', () => {
    expect(source).toContain('搜索航道名称或属性')
    expect(source).toContain('当前视口')
    expect(source).toContain('地图点选')
    expect(source).toContain('waterways.runSearch')
    expect(source).toContain('waterways.setPage')
    expect(source).toContain('定位')
    expect(source).toContain('详情')
    expect(source).toContain('显示')
    expect(source).toContain('清除显示')
  })

  it('shows missing attributes as 未提供 and empty states honestly', () => {
    expect(source).toContain('未提供')
    expect(source).toContain('当前数据未检索到航道专题要素')
    expect(source).toContain('没有匹配结果')
  })

  it('supports snapshot save, listing and GeoJSON download', () => {
    expect(source).toContain('保存提取结果')
    expect(source).toContain('已保存航道数据')
    expect(source).toContain('下载 GeoJSON')
    expect(source).toContain('createSnapshot')
    expect(source).toContain('loadSnapshots')
    expect(source).toContain('基于旧版海图数据')
  })

  it('keeps snapshot entry points visible when the project has no waterway data', () => {
    const actions = source.indexOf('waterway-snapshot-actions')
    const emptyState = source.indexOf('!hasWaterwayData')
    expect(actions).toBeGreaterThan(0)
    expect(emptyState).toBeGreaterThan(0)
    expect(actions).toBeLessThan(emptyState)
  })

  it('provides a map overview legend and teleports dialog/drawers to body', () => {
    expect(source).toContain('地图专题图例')
    expect(source).toContain('在地图显示选中类别')
    expect(source).toContain('showOverview')
    expect(source).toContain('append-to-body')
  })

  it('explains the flow: no prior search or S-57 WMS load is required', () => {
    expect(source).toContain('使用说明')
    expect(source).toContain('不需要先搜索')
    expect(source).toContain('不要求先加载 S-57 WMS 海图图层')
    expect(source).toContain('地图点选')
    expect(source).toContain('当前视口')
  })

  it('keeps the map legend above the category list so it remains reachable', () => {
    const legend = source.indexOf('waterway-map-legend')
    const groups = source.indexOf('waterway-class-groups')
    expect(legend).toBeGreaterThan(0)
    expect(groups).toBeGreaterThan(0)
    expect(legend).toBeLessThan(groups)
  })

  it('does not write into route state', () => {
    expect(source).not.toContain('routesStore')
    expect(source).not.toContain('routeDrawing')
  })
})
