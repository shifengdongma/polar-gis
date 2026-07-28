export interface BuiltinBasemap {
  id: string
  name: string
  mapType: 'XYZ'
  urlTemplate: string
  crs: 'EPSG:3857'
  attribution: string
  /** Dot color shown in the dropdown for quick visual identification. */
  color: string
}

export const BUILTIN_BASEMAPS: BuiltinBasemap[] = [
  {
    id: 'builtin-osm',
    name: 'OpenStreetMap',
    mapType: 'XYZ',
    urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    crs: 'EPSG:3857',
    attribution: '© OpenStreetMap contributors',
    color: '#3b82f6',
  },
  {
    id: 'builtin-gaode',
    name: '高德地图',
    mapType: 'XYZ',
    urlTemplate: 'https://webrd0{1-4}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    crs: 'EPSG:3857',
    attribution: '© 高德地图',
    color: '#22c55e',
  },
  {
    id: 'builtin-google',
    name: 'Google Maps',
    mapType: 'XYZ',
    urlTemplate: 'https://mt{0-3}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}',
    crs: 'EPSG:3857',
    attribution: '© Google',
    color: '#eab308',
  },
  {
    id: 'builtin-tencent',
    name: '腾讯地图',
    mapType: 'XYZ',
    urlTemplate: 'https://rt{0-3}.map.gtimg.com/tile?z={z}&x={x}&y={y}&type=vector&styleid=0',
    crs: 'EPSG:3857',
    attribution: '© 腾讯地图',
    color: '#64748b',
  },
]
