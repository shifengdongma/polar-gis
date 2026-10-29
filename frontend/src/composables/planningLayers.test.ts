import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { useRiskGridLayer } from './useRiskGridLayer'

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

  it('loads GeoJSON features into the risk source', () => {
    const api = useRiskGridLayer({ getMap: () => null, getCrs: () => 'EPSG:3857' })
    api.setGrid({
      type: 'FeatureCollection',
      field: 'combined',
      totalCells: 1,
      returnedCells: 1,
      snapshotTime: null,
      features: [
        {
          type: 'Feature',
          id: 'r0c0',
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [120, 75],
                [121, 75],
                [121, 76],
                [120, 76],
                [120, 75],
              ],
            ],
          },
          properties: {
            cellId: 'r0c0',
            value: 0.2,
            traversable: true,
            quality: 'synthetic',
            riskModelVersion: 'legacy_v1',
          },
        },
      ],
    })
    expect(api.layer.getSource()?.getFeatures()).toHaveLength(1)
  })
})
