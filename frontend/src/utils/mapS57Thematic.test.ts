import { describe, expect, it } from 'vitest'
import Feature from 'ol/Feature'
import Point from 'ol/geom/Point'
import {
  THEMATIC_OVERLAY_Z_INDEX,
  thematicCategoryColor,
  thematicPreviewExtent,
  thematicStyleForFeature,
} from './mapS57Thematic'

describe('mapS57Thematic', () => {
  it('uses category colors and a separate overlay zIndex', () => {
    expect(THEMATIC_OVERLAY_Z_INDEX).toBe(79)
    expect(thematicCategoryColor('depth')).not.toBe(thematicCategoryColor('hazards'))
    expect(thematicCategoryColor('unknown')).toBe(thematicCategoryColor('other'))
  })

  it('styles point samples by category and zoom without throwing', () => {
    const feature = new Feature({
      geometry: new Point([0, 0]),
      category: 'hazards',
    })
    const near = thematicStyleForFeature(feature as never, undefined, 500)
    const far = thematicStyleForFeature(feature as never, undefined, 30_000)
    expect(near).toBeTruthy()
    expect(far).toBeTruthy()
  })

  it('computes an extent from a sample FeatureCollection', () => {
    const extent = thematicPreviewExtent(
      [
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [10, 70, -12.5] },
          properties: { category: 'depth' },
        },
      ],
      'EPSG:3857',
    )
    expect(extent).not.toBeNull()
    expect(extent![2]).toBeGreaterThan(extent![0])
  })
})
