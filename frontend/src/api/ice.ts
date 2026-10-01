/** 冰情叠加 API —— info / 原始值 / 对齐调试(全部只读)。 */
import { api } from './client'
import type { IceInfo, IceValue } from '../types'

/** 扫描后端数据目录:实际日期、字段并集与各字段可用日期、源网格范围。 */
export async function fetchIceInfo(signal?: AbortSignal): Promise<IceInfo> {
  const response = await api.get<IceInfo>('/ice/info', { signal })
  return response.data
}

/** 地图坐标处的原始网格值;miss 时后端返回 {"value": null}(键可能缺席)。 */
export async function fetchIceValue(
  params: { date: string; x: number; y: number; projection: string },
  signal?: AbortSignal,
): Promise<IceValue> {
  const response = await api.get<IceValue>('/ice/value', { params, signal })
  return response.data
}

/** 坐标对齐调试控制点(GeoJSON,坐标已处于请求的显示投影)。 */
export async function fetchIceAlignment(
  params: { date: string; projection: string },
  signal?: AbortSignal,
): Promise<{ type: string; features: unknown[] }> {
  const response = await api.get<{ type: string; features: unknown[] }>('/ice/alignment', {
    params,
    signal,
  })
  return response.data
}
