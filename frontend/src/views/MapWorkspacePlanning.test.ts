import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(join(process.cwd(), 'src/views/MapWorkspaceView.vue'), 'utf8')

describe('MapWorkspace planning integration invariants', () => {
  it('keeps exactly one map, one singleclick and one pointermove', () => {
    expect((source.match(/new OlMap\(/g) ?? []).length).toBe(1)
    expect((source.match(/map\.on\('singleclick'/g) ?? []).length).toBe(1)
    expect((source.match(/map\.on\('pointermove'/g) ?? []).length).toBe(1)
  })

  it('attaches, disposes and reprojects planning/risk layers', () => {
    expect(source).toContain('planningRouteLayer.attach()')
    expect(source).toContain('riskGridLayer.attach()')
    expect(source).toContain('planningRouteLayer.dispose()')
    expect(source).toContain('riskGridLayer.dispose()')
    expect(source).toContain('planningRouteLayer.reloadForProjection()')
    expect(source).toContain('riskGridLayer.reloadForProjection()')
  })

  it('arbitrates planning picking and risk inspection inside the existing handler', () => {
    const handler = source.match(/map\.on\('singleclick'[\s\S]*?\n  \}\)/)?.[0] ?? ''
    expect(handler).toContain('navigationStore.pickMode')
    expect(handler).toContain('navigationStore.riskInspect')
    expect(handler).toContain('riskGridLayer.pickCellAtPixel')
    expect(handler).toContain('planningRouteLayer.pickRouteAtPixel')
    expect(handler).not.toContain('routePanelVisible')
  })

  it('passes the environment time into the planning workbench', () => {
    expect(source).toContain(':environment-time="environmentOverlays.requestedTime.value"')
  })
})
