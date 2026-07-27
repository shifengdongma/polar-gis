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
  geometryType: string | null
  minZoom?: number | null
  maxZoom?: number | null
  extent?: number[] | null
  objectClass?: string | null
  objectNameZh?: string | null
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
  dataType?: string | null
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
  purpose: string
  metadataJson: Record<string, unknown>
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

// ── Bulk layer resolve ──────────────────────────────────────────────

export type S57LoadProfile = 'core_chart' | 'navigation_recommended' | 'all_spatial'

export interface BulkMapLayerResolveRequest {
  datasetIds: string[]
  profile: S57LoadProfile
  includeMetadata?: boolean
}

export interface BulkResolvedLayer {
  id: string
  code: string
  name: string
  objectClass: string | null
  objectNameZh: string | null
  geometryType: string | null
  geoserverWorkspace: string | null
  geoserverLayerName: string | null
  serviceUrl: string
  styleName: string | null
  opacity: number
  minZoom: number | null
  maxZoom: number | null
  extent: number[] | null
  featureCount: number | null
  displayCategory: string
  loadProfile: string
  displayPriority: number
  recommended: boolean
  renderable: boolean
  loadable: boolean
  styleMapped: boolean
  skipReason: string | null
  queryable: boolean
  exportable: boolean
  groupName: string
  sortOrder: number
}

export interface BulkResolvedDataset {
  datasetId: string
  datasetCode: string
  datasetName: string
  versionNo: number
  layers: BulkResolvedLayer[]
}

export interface BulkLayerResolveSummary {
  datasetCount: number
  candidateCount: number
  loadableCount: number
  metadataSkippedCount: number
  nonSpatialSkippedCount: number
  unavailableSkippedCount: number
  unmappedStyleCount: number
}

export interface BulkMapLayerResolveResponse {
  datasets: BulkResolvedDataset[]
  summary: BulkLayerResolveSummary
}

export interface BulkLayerProgress {
  total: number
  processed: number
  succeeded: number
  failed: number
  skipped: number
  attachedLayerIds: string[]
  errors: Array<{ layerId: string; layerName: string; message: string }>
}

// ── S-57 Basemap types ──────────────────────────────────────────────

export interface BasemapProfile {
  code: string
  name: string
  usageBand: number
  cellCount: number
  fileCount: number
  description: string
}

export interface BasemapPreflightCell {
  cellName: string
  expectedMaxUpdate: number
  discoveredUpdates: number[]
  editionNumber: string | null
  usageBand: number | null
  compilationScale: number | null
  databaseCurrentUpdate: number | null
  action: 'create' | 'append_updates' | 'skip_current' | 'blocked'
  errors: string[]
}

export interface BasemapPreflightResponse {
  profileCode: string
  profileName: string
  manifestHash: string
  expectedCellCount: number
  expectedFileCount: number
  discoveredCellCount: number
  selectedFileCount: number
  ignoredFileCount: number
  createCellCount: number
  updateCellCount: number
  skipCellCount: number
  blockedCellCount: number
  totalSizeBytes: number
  coverageExtent: number[]
  coverageVerified: boolean
  coverageMessage: string
  canStart: boolean
  cells: BasemapPreflightCell[]
  ignoredFiles: string[]
}

export interface BasemapImportResponse {
  batchId: string
  profileCode: string
  status: string
  selectedCellCount: number
  selectedFileCount: number
}

export interface BasemapRunDetail extends S57ImportBatchDetail {
  postProcessStatus: string | null
  layerGroupStatus: string | null
  wmts3857Status: string | null
  wmts3413Status: string | null
  cacheWarmStatus: string | null
  baseMapIds: string[]
  warnings: string[]
}
