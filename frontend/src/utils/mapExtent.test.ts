import { describe, expect, it } from 'vitest'

import { parseWgs84Extent } from './mapExtent'

describe('parseWgs84Extent', () => {
  it('parses a valid WGS84 bounding box', () => {
    expect(parseWgs84Extent('[-180, 58.2, -159.5, 68.1]')).toEqual([-180, 58.2, -159.5, 68.1])
  })

  it.each([null, 'not-json', '[1, 2, 3]', '[10, 20, 10, 30]', '[10, 30, 20, 30]'])('rejects invalid input %j', (value) => {
    expect(parseWgs84Extent(value)).toBeNull()
  })
})
