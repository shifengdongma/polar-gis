import { describe, expect, it } from 'vitest'
import proj4 from 'proj4'
import { toLonLat } from 'ol/proj'
import { register } from 'ol/proj/proj4'
import type { VectorObservation } from '../types/navigation'
import {
  arrowLengthForZoom,
  buildArrowFeature,
  environmentBbox,
  environmentMetricLabel,
  environmentValueText,
} from './mapEnvironment'

proj4.defs(
  'EPSG:3413',
  '+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +datum=WGS84 +units=m +no_defs',
)
register(proj4)

function observation(overrides: Partial<VectorObservation>): VectorObservation {
  return {
    id: 'p1',
    longitude: 120,
    latitude: 75,
    field: 'wind',
    available: true,
    values: {},
    units: {},
    quality: 'real',
    source: 'test',
    matchedTime: '2025-02-15T12:00:00Z',
    reason: null,
    ...overrides,
  }
}

describe('mapEnvironment arrow geometry', () => {
  it('wind FROM 270 points east in EPSG:3857', () => {
    const feature = buildArrowFeature(
      observation({ values: { speedMs: 10, directionFromDeg: 270 } }),
      'EPSG:3857',
      4,
    )
    expect(feature).not.toBeNull()
    const coordinates = feature!.getGeometry()!.getCoordinates()
    const [start, end] = coordinates[0]
    expect(end[0]).toBeGreaterThan(start[0])
    expect(Math.abs(end[1] - start[1])).toBeLessThan(Math.abs(end[0] - start[0]))
  })

  it('current TO 090 points east in EPSG:3857', () => {
    const feature = buildArrowFeature(
      observation({ field: 'current', values: { speedMs: 0.4, directionToDeg: 90 } }),
      'EPSG:3857',
      4,
    )
    const [start, end] = feature!.getGeometry()!.getCoordinates()[0]
    expect(end[0]).toBeGreaterThan(start[0])
  })

  it('wave FROM 240 points to 060 in EPSG:3413', () => {
    const feature = buildArrowFeature(
      observation({ field: 'wave', values: { heightM: 2, directionFromDeg: 240 } }),
      'EPSG:3413',
      4,
    )
    expect(feature).not.toBeNull()
    const coordinates = feature!.getGeometry()!.getCoordinates()[0]
    const [endLon, endLat] = toLonLat(coordinates[1], 'EPSG:3413')
    // 060° is north-east in geographic terms; do not assume projected x/y axes.
    expect(endLon).toBeGreaterThan(120)
    expect(endLat).toBeGreaterThan(75)
  })

  it('does not create an arrow for unavailable observations or missing direction', () => {
    expect(buildArrowFeature(observation({ available: false }), 'EPSG:3857', 3)).toBeNull()
    expect(buildArrowFeature(observation({ values: {} }), 'EPSG:3857', 3)).toBeNull()
  })
})

describe('mapEnvironment helpers', () => {
  it('bbox converts a projected extent to WGS84', () => {
    const bbox = environmentBbox([13300000, 9000000, 13500000, 9200000], 'EPSG:3857')
    expect(bbox[1]).toBeGreaterThan(55)
    expect(bbox[1]).toBeLessThan(85)
    expect(bbox[0]).toBeLessThan(bbox[2])
  })

  it('arrow length decreases with zoom and never goes below 8 km', () => {
    expect(arrowLengthForZoom(2)).toBeGreaterThan(arrowLengthForZoom(6))
    expect(arrowLengthForZoom(18)).toBe(8_000)
  })

  it('formats field metrics with explicit units', () => {
    const wind = observation({ values: { speedMs: 10.2, directionFromDeg: 270 } })
    expect(environmentMetricLabel(wind)).toBe('10.2 m/s')
    expect(environmentValueText(wind)).toContain('来向 270°')
    const wave = observation({
      field: 'wave',
      values: { heightM: 2.4, periodS: 7.1, directionFromDeg: 240 },
    })
    expect(environmentMetricLabel(wave)).toBe('2.4 m')
    expect(environmentValueText(wave)).toContain('周期 7.1 s')
  })
})
