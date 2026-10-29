import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  join(process.cwd(), 'src/components/VesselProfilePanel.vue'),
  'utf8',
)

describe('VesselProfilePanel', () => {
  it('shows static vessel capability fields and required depth', () => {
    expect(source).toContain('设计吃水')
    expect(source).toContain('富余水深 UKC')
    expect(source).toContain('requiredDepthM')
    expect(source).toContain('推进功率')
    expect(source).toContain('连续破冰')
  })

  it('never presents live vessel state as available', () => {
    expect(source).toContain('selected.liveStateNote')
    expect(source).toContain('静态资料')
    expect(source).toContain('资料来源')
  })
})
