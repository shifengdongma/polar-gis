import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function source(path: string): string {
  return readFileSync(join(process.cwd(), path), 'utf8')
}

describe('planning workbench panels', () => {
  it('NavigationTaskPanel supports coordinate input, map picking, policy, and three objectives', () => {
    const text = source('src/components/NavigationTaskPanel.vue')
    expect(text).toContain('地图选起点')
    expect(text).toContain('地图选终点')
    expect(text).toContain('取当前手绘航路端点')
    expect(text).toContain('real_only')
    expect(text).toContain('allow_synthetic_research')
    expect(text).toContain('NSGA-III 固定三目标')
    expect(text).toContain('不可作为真实航行决策依据')
  })

  it('RouteComparisonPanel uses a Pareto chart and adoption, never fake points', () => {
    const text = source('src/components/RouteComparisonPanel.vue')
    expect(text).toContain('Pareto')
    expect(text).toContain('采纳')
    expect(text).toContain('只绘制算法实际返回的候选解')
    expect(text).toContain('energyMWh')
    expect(text).toContain('riskScore')
  })

  it('RiskAnalysisPanel exposes per-field risk, cell details, and area evaluation', () => {
    const text = source('src/components/RiskAnalysisPanel.vue')
    expect(text).toContain('综合风险')
    expect(text).toContain('地图点选风险格')
    expect(text).toContain('提交区域风险评估')
    expect(text).toContain('riskModelVersion')
    expect(text).toContain('quality')
    expect(text).toContain('blockedReason')
  })

  it('PlanningResultPanel distinguishes snapshot time and synthetic data', () => {
    const text = source('src/components/PlanningResultPanel.vue')
    expect(text).toContain('规划快照时间与当前地图环境时间不同')
    expect(text).toContain('含合成环境数据')
    expect(text).toContain('历史任务')
    expect(text).toContain('取消任务')
  })

  it('IntelligentPlanningPanel composes task/vessel/comparison/risk/result tabs', () => {
    const text = source('src/components/IntelligentPlanningPanel.vue')
    expect(text).toContain('NavigationTaskPanel')
    expect(text).toContain('VesselProfilePanel')
    expect(text).toContain('RouteComparisonPanel')
    expect(text).toContain('RiskAnalysisPanel')
    expect(text).toContain('PlanningResultPanel')
    expect(text).toContain('已采纳为可编辑草稿')
  })
})
