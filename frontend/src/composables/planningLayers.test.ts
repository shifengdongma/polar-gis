import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function source(path: string): string {
  return readFileSync(join(process.cwd(), path), 'utf8')
}

describe('planning layer lifecycle invariants', () => {
  it('planning route layer is independent and has attach/dispose/projection reload', () => {
    const text = source('src/composables/usePlanningRouteLayer.ts')
    expect(text).toContain('PLANNING_ROUTE_Z_INDEX = 90')
    expect(text).toContain('new VectorLayer')
    expect(text).toContain('map.addLayer(layer)')
    expect(text).toContain('map.removeLayer(layer)')
    expect(text).toContain('reloadForProjection')
    expect(text).toContain('pickRouteAtPixel')
    expect(text).not.toContain('new OlMap')
    expect(text).not.toContain('routesStore')
  })

  it('risk grid layer is independent and renders unknown cells distinctly', () => {
    const text = source('src/composables/useRiskGridLayer.ts')
    expect(text).toContain('PLANNING_RISK_Z_INDEX = 70')
    expect(text).toContain('featureProjection')
    expect(text).toContain('reloadForProjection')
    expect(text).toContain('value === null')
    expect(text).toContain('rgba(138, 148, 166, 0.30)')
    expect(text).not.toContain('new OlMap')
  })
})
