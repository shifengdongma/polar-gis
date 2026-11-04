import { describe, expect, it } from 'vitest'
import Feature from 'ol/Feature'
import LineString from 'ol/geom/LineString'
import Point from 'ol/geom/Point'
import proj4 from 'proj4'
import { register } from 'ol/proj/proj4'
import { get as getProjection } from 'ol/proj'
import {
  waterwayDisplayName,
  waterwayExtent,
  waterwayFeatureFromItem,
  waterwayGroupColor,
  waterwaySourceLabel,
  waterwayStyleForFeature,
} from './mapS57Waterway'
import type { S57WaterwaySearchItem } from '../types/s57Waterways'

proj4.defs('EPSG:3413', '+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +datum=WGS84 +units=m +no_defs')
register(proj4)
getProjection('EPSG:3413')?.setExtent([-4194304, -4194304, 4194304, 4194304])

function item(overrides: Partial<S57WaterwaySearchItem> = {}): S57WaterwaySearchItem {
  return {
    id: 'opaque-id',
    layerId: 'layer',
    layerName: 'FAIRWY',
    layerCode: 's57_test_1_fairwy',
    datasetCode: 's57_test',
    datasetName: 'S-57 海图 TEST',
    versionNo: 1,
    sourceCell: 'TEST',
    objectClass: 'FAIRWY',
    objectNameZh: '航道',
    group: 'fairway_route',
    groupNameZh: '航道与推荐路线',
    auxiliary: false,
    name: 'Test Fairway',
    nameField: 'OBJNAM',
    inform: null,
    status: null,
    geometryType: 'MultiLineString',
    renderable: true,
    geometry: {
      type: 'LineString',
      coordinates: [[10, 70], [11, 71]],
    },
    bbox: [10, 70, 11, 71],
    ...overrides,
  }
}

describe('waterway display helpers', () => {
  it('never fabricates a name for unnamed features', () => {
    expect(waterwayDisplayName({ name: null })).toBe('未命名航道要素')
    expect(waterwayDisplayName({ name: '  ' })).toBe('未命名航道要素')
    expect(waterwayDisplayName({ name: 'Real Name' })).toBe('Real Name')
  })

  it('shows the source cell/version without inventing a chart edition', () => {
    expect(waterwaySourceLabel(item())).toBe('TEST')
    expect(waterwaySourceLabel(item({ sourceCell: null, versionNo: 3 }))).toBe(
      'S-57 海图 TEST · v3',
    )
  })
})

describe('waterway geometry/style', () => {
  it('reads WGS84 GeoJSON into the current projection', () => {
    const feature3857 = waterwayFeatureFromItem(item(), 'EPSG:3857')
    const feature3413 = waterwayFeatureFromItem(item(), 'EPSG:3413')
    expect(feature3857).not.toBeNull()
    expect(feature3413).not.toBeNull()
    const coords3857 = (feature3857!.getGeometry() as LineString).getCoordinates()[0]
    const coords3413 = (feature3413!.getGeometry() as LineString).getCoordinates()[0]
    expect(Math.abs(coords3857[0])).toBeGreaterThan(100_000)
    expect(Math.abs(coords3413[0])).toBeGreaterThan(100_000)
  })

  it('computes an extent and expands a point extent', () => {
    expect(waterwayExtent(item(), 'EPSG:3857')).not.toBeNull()
    const point = item({
      geometry: { type: 'Point', coordinates: [10, 70] },
      geometryType: 'Point',
    })
    const extent = waterwayExtent(point, 'EPSG:3857')!
    expect(extent[0]).toBeLessThan(extent[2])
    expect(extent[1]).toBeLessThan(extent[3])
  })

  it('styles fairway, traffic-separation, restriction and auxiliary differently', () => {
    const cache = new Map()
    const fairway = new Feature({ geometry: new LineString([[0, 0], [1, 1]]) })
    fairway.setProperties({ group: 'fairway_route', auxiliary: false })
    const traffic = new Feature({ geometry: new LineString([[0, 0], [1, 1]]) })
    traffic.setProperties({ group: 'traffic_separation', auxiliary: false })
    const aux = new Feature({ geometry: new Point([0, 0]) })
    aux.setProperties({ group: 'waterway_environment', auxiliary: true })
    const fairwayStyle = waterwayStyleForFeature(fairway, false, cache)
    const trafficStyle = waterwayStyleForFeature(traffic, false, cache)
    const auxStyle = waterwayStyleForFeature(aux, false, cache)
    const selectedStyle = waterwayStyleForFeature(fairway, true, cache)
    expect(fairwayStyle.getStroke()?.getColor()).not.toBe(
      trafficStyle.getStroke()?.getColor(),
    )
    expect(auxStyle.getImage()).not.toBeNull()
    expect(selectedStyle.getStroke()?.getColor()).toBe('#fde047')
    expect(selectedStyle.getStroke()?.getWidth()).toBeGreaterThan(
      fairwayStyle.getStroke()?.getWidth() ?? 0,
    )
    expect(waterwayGroupColor('fairway_route')).toBe('#22d3ee')
    expect(waterwayGroupColor('waterway_environment', true)).toBe('#94a3b8')
  })
})
