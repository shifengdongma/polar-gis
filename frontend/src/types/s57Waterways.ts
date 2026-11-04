/** S-57 waterway thematic API types (backend camelCase responses). */

export type WaterwayGroup =
  | 'fairway_route'
  | 'traffic_separation'
  | 'restriction'
  | 'waterway_environment'

export interface S57WaterwayLayerRef {
  id: string
  name: string
  code: string
  datasetCode: string
  datasetName: string
  versionNo: number
  sourceCell: string | null
  featureCount: number | null
  queryable: boolean
  renderable: boolean
  available: boolean
  reason: string | null
}

export interface S57WaterwayClass {
  code: string
  nameZh: string
  group: WaterwayGroup
  groupNameZh: string
  auxiliary: boolean
  defaultSelected: boolean
  description: string
  count: number
  layerCount: number
  queryable: boolean
  renderable: boolean
  layers: S57WaterwayLayerRef[]
}

export interface S57WaterwayCatalog {
  classes: S57WaterwayClass[]
  total: number
  countComplete: boolean
  truncated: boolean
  warnings: string[]
}

export interface S57WaterwaySearchRequest {
  keyword?: string | null
  objectClasses: string[]
  includeAuxiliary?: boolean
  bbox?: [number, number, number, number] | null
  page?: number
  pageSize?: number
}

export interface S57WaterwaySearchItem {
  id: string
  layerId: string
  layerName: string
  layerCode: string
  datasetCode: string
  datasetName: string
  versionNo: number
  sourceCell: string | null
  objectClass: string
  objectNameZh: string
  group: WaterwayGroup
  groupNameZh: string
  auxiliary: boolean
  name: string | null
  nameField: string | null
  inform: string | null
  status: string | null
  geometryType: string | null
  renderable: boolean
  geometry: Record<string, unknown> | null
  bbox: [number, number, number, number] | null
}

export interface S57WaterwaySearchResponse {
  items: S57WaterwaySearchItem[]
  page: number
  pageSize: number
  total: number
  truncatedLayers: boolean
  warnings: string[]
}

export interface S57WaterwaySnapshotCreateRequest {
  name?: string | null
  keyword?: string | null
  objectClasses: string[]
  includeAuxiliary?: boolean
  bbox?: [number, number, number, number] | null
  maxFeatures?: number | null
}

export interface S57WaterwaySnapshotSource {
  datasetId: string
  datasetCode: string
  datasetName: string
  versionId: string | null
  versionNo: number
  sourceCell: string | null
  layerIds: string[]
  contentHash: string | null
}

export interface S57WaterwaySnapshotManifest {
  snapshotId: string
  projectId: string
  name: string
  createdAt: string
  crs: string
  featureCount: number
  truncated: boolean
  objectClasses: string[]
  sourceDatasets: S57WaterwaySnapshotSource[]
  sourceVersionIds: string[]
  sourceContentHashes: Record<string, string>
  filters: Record<string, unknown>
  schemaVersion: string
  warnings: string[]
  geojsonSha256: string | null
  stale: boolean
}

export interface S57WaterwaySnapshotList {
  items: S57WaterwaySnapshotManifest[]
  warnings: string[]
}

export interface S57WaterwayProperty {
  field: string
  labelZh: string
  raw: unknown
  provided: boolean
  description: string | null
  source: string | null
}

export interface S57WaterwayDetail {
  id: string
  layerId: string
  layerName: string
  layerCode: string
  datasetCode: string
  datasetName: string
  versionNo: number
  sourceCell: string | null
  objectClass: string
  objectNameZh: string
  group: WaterwayGroup
  groupNameZh: string
  auxiliary: boolean
  name: string | null
  nameField: string | null
  geometryType: string | null
  geometry: Record<string, unknown> | null
  bbox: [number, number, number, number] | null
  updatedAt: string | null
  properties: S57WaterwayProperty[]
  rawProperties: Record<string, unknown>
}
