export type Wgs84Extent = [number, number, number, number]

export function parseWgs84Extent(value: string | null): Wgs84Extent | null {
  if (!value) return null
  try {
    const extent = JSON.parse(value)
    if (!Array.isArray(extent) || extent.length !== 4 || !extent.every((coordinate) => Number.isFinite(coordinate))) {
      return null
    }
    const [minLongitude, minLatitude, maxLongitude, maxLatitude] = extent
    if (minLongitude >= maxLongitude || minLatitude >= maxLatitude) return null
    return [minLongitude, minLatitude, maxLongitude, maxLatitude]
  } catch {
    return null
  }
}
