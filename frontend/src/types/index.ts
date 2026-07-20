export type Role = 'system_admin' | 'user'

export interface User {
  id: string
  username: string
  displayName: string
  role: Role
  isActive: boolean
  lastLoginAt: string | null
  createdAt: string
}

export type ProjectStatus = 'draft' | 'published' | 'archived'

export interface Project {
  id: string
  code: string
  name: string
  description: string
  status: ProjectStatus
  defaultCrs: string
  initialExtent: string | null
  publishedAt: string | null
  createdAt: string
  updatedAt: string
  layerCount: number
}

export interface MapLayerConfig {
  id: string
  code: string
  name: string
  groupName: string
  sortOrder: number
  visibleByDefault: boolean
  opacity: number
  queryable: boolean
  exportable: boolean
  serviceType: string
  serviceUrl: string
  serviceLayerName: string
  styleName: string | null
  metadata: Record<string, unknown>
}

export interface MapDatasetConfig {
  id: string
  code: string
  name: string
  groupName: string
  sortOrder: number
  visibleByDefault: boolean
  opacity: number
  memberLayerCount: number
}

export interface MapConfig {
  project: Project
  supportedCrs: string[]
  datasets: MapDatasetConfig[]
}

export interface Paginated<T> {
  items: T[]
  page: number
  pageSize: number
  total: number
}

export interface Dataset {
  id: string
  code: string
  name: string
  dataType: string
  description: string
  currentVersionId: string | null
  createdAt: string
  updatedAt: string
  versionCount: number
}

export interface DatasetVersion {
  id: string
  datasetId: string
  versionNo: number
  sourceFormat: string
  sourceCrs: string | null
  status: string
  contentHash: string
  metadataJson: Record<string, unknown>
  createdAt: string
  activatedAt: string | null
}

export interface DatasetProjectReference {
  id: string
  code: string
  name: string
  status: string
}

export interface DatasetBulkDeleteBlocked {
  datasetId: string
  datasetName: string
  projects: DatasetProjectReference[]
}

export interface DatasetBulkDeleteResult {
  deletedIds: string[]
  blocked: DatasetBulkDeleteBlocked[]
}

export interface DatasetCleanupPreview {
  datasetId: string
  datasetCode: string
  datasetName: string
  deletedAt: string
  confirmationText: string
  sourceFiles: string[]
  derivedTables: string[]
  geoserverResources: string[]
  versionCount: number
  layerCount: number
}

export interface DatasetBulkPurgePreview {
  confirmationText: string
  datasets: DatasetCleanupPreview[]
}

export interface DatasetBulkPurgeResult {
  purgedIds: string[]
}

export interface ImportJob {
  id: string
  datasetId: string
  datasetVersionId: string
  jobType: string
  status: string
  stage: string
  progress: number
  attempt: number
  errorCode: string | null
  errorMessage: string | null
  queuedAt: string
  startedAt: string | null
  finishedAt: string | null
}

export interface S57ImportBatch {
  id: string
  name: string
  status: string
  stage: string
  progress: number
  totalCells: number
  processedCells: number
  succeededCells: number
  failedCells: number
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
}

export interface S57ImportBatchItem {
  id: string
  batchId: string
  cellName: string
  status: string
  stage: string
  progress: number
  updateCount: number
  currentUpdate: number
  datasetId: string | null
  errorCode: string | null
  errorMessage: string | null
  finishedAt: string | null
}

export interface S57ImportBatchDetail extends S57ImportBatch {
  items: S57ImportBatchItem[]
}

export interface LayerRecord {
  id: string
  datasetVersionId: string
  code: string
  name: string
  geometryType: string | null
  sourceCrs: string | null
  status: string
  queryable: boolean
  exportable: boolean
  allowedFields: string[]
  metadataJson: Record<string, unknown>
}

export interface StyleRecord {
  id: string
  code: string
  name: string
  geoserverStyleName: string | null
  status: string
}

export interface BaseMapRecord {
  id: string
  name: string
  mapType: 'XYZ' | 'WMTS'
  urlTemplate: string
  crs: string
  attribution: string
  isOffline: boolean
  isEnabled: boolean
}

export interface ProjectLayerConfig {
  id: string
  layerId: string
  styleId: string | null
  groupName: string
  sortOrder: number
  visibleByDefault: boolean
  opacity: number
  minZoom: number | null
  maxZoom: number | null
}

export interface ProjectDatasetLayer {
  datasetId: string
  datasetCode: string
  datasetName: string
  dataType: string
  versionNo: number
  availableLayerCount: number
  selected: boolean
  groupName: string
  sortOrder: number
  visibleByDefault: boolean
  opacity: number
}
