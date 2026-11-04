/**
 * WGS84 椭球测地线距离 — GeographicLib（Karney 算法）的薄封装。
 *
 * 输入/输出契约:
 * - 点坐标永远是 WGS84 [lon, lat](度),与当前地图投影无关;
 * - 返回值单位是米;非法输入返回 NaN,同一点返回 0;
 * - 经度可跨 ±180°,由 GeographicLib 内部正确处理。
 *
 * 注意:两点之间是椭球面最短测地线距离;多航点结果是各相邻航点距离之和,
 * 不是避障后的真实航行轨迹距离。
 */
import geographiclib from 'geographiclib-geodesic'

const WGS84 = geographiclib.Geodesic.WGS84

/**
 * 单段 WGS84 椭球测地线反算距离（米）。
 * 非有限坐标或 |lat| > 90 时返回 NaN。
 */
export function geodesicDistanceWGS84(
  pointA: readonly number[],
  pointB: readonly number[],
): number {
  const lon1 = pointA[0]
  const lat1 = pointA[1]
  const lon2 = pointB[0]
  const lat2 = pointB[1]
  if (
    lon1 === undefined ||
    lat1 === undefined ||
    lon2 === undefined ||
    lat2 === undefined ||
    !Number.isFinite(lon1) ||
    !Number.isFinite(lat1) ||
    !Number.isFinite(lon2) ||
    !Number.isFinite(lat2) ||
    Math.abs(lat1) > 90 ||
    Math.abs(lat2) > 90
  ) {
    return Number.NaN
  }
  const result = WGS84.Inverse(lat1, lon1, lat2, lon2)
  const distance = result.s12
  return typeof distance === 'number' && Number.isFinite(distance) ? distance : Number.NaN
}

/**
 * 折线总长（米）:对每对相邻航点做椭球测地线反算后求和。
 * 少于 2 个点时返回 0;任一段非法时返回 NaN。
 */
export function measurePolylineLength(points: readonly (readonly number[])[]): number {
  if (points.length < 2) return 0
  let total = 0
  for (let index = 1; index < points.length; index++) {
    const distance = geodesicDistanceWGS84(points[index - 1]!, points[index]!)
    if (!Number.isFinite(distance)) return Number.NaN
    total += distance
  }
  return total
}
