/** S-57 depth/hazard thematic API types (backend camelCase). */

export interface S57ThematicLayerRef {
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
  extractable: boolean
  geometryType: string | null
  reason: string | null
}

export interface S57ThematicClass {
  code: string
  nameZh: string
  category: string
  categoryNameZh: string
  description: string
  caveats: string[]
  defaultSelected: boolean
  count: number
  countComplete: boolean
  layerCount: number
  queryable: boolean
  renderable: boolean
  extractable: boolean
  layers: S57ThematicLayerRef[]
}

export interface S57ThematicCategory {
  code: string
  nameZh: string
  classes: S57ThematicClass[]
}

export interface S57ThematicCatalog {
  categories: S57ThematicCategory[]
  classes: S57ThematicClass[]
  totalLayerCount: number
  extractableLayerCount: number
  featureCount: number
  countComplete: boolean
  candidateLayerCount: number
  resolvedLayerCount: number
  cells: Array<{
    sourceCell: string
    layerCount: number
    featureCount: number
    datasetCodes: string[]
    objectClasses: string[]
  }>
  datasets: Array<{
    datasetId: string
    datasetCode: string
    datasetName: string
    versionNo: number
    sourceCell: string | null
    layerCount: number
    featureCount: number
  }>
  soundgDepth: {
    layers: Array<{
      layerId: string
      sourceCell: string | null
      geometryNdims: number | null
      zMin: number | null
      zMax: number | null
      depthPreserved: boolean | null
      note: string | null
    }>
    depthPreserved: boolean | null
    note: string
  }
  warnings: string[]
  semantics: string[]
}

export interface S57ThematicExportCreateRequest {
  name?: string | null
  objectClasses: string[]
  bbox?: [number, number, number, number] | null
  sourceCells?: string[] | null
  datasetIds?: string[] | null
  maxFeaturesPerClass?: number | null
}

export interface S57ThematicExportClassStat {
  code: string
  nameZh: string
  category: string
  categoryNameZh: string
  featureCount: number
  truncated: boolean
  layerCount: number
}

export interface S57ThematicExportFile {
  path: string
  objectClass: string
  sourceCell: string | null
  layerId: string
  featureCount: number
  sha256: string
  bytes: number
  part: number
}

export interface S57ThematicExportManifest {
  schemaVersion: string
  exportId: string
  projectId: string
  name: string
  createdAt: string
  crs: string
  categories: string[]
  filters: Record<string, unknown>
  bbox: [number, number, number, number] | null
  featureCount: number
  featureCountUnit: string | null
  complete: boolean
  truncated: boolean
  truncationReasons: string[]
  objectClasses: S57ThematicExportClassStat[]
  classCounts: Record<string, number>
  cellCounts: Record<string, number>
  files: S57ThematicExportFile[]
  sourceDatasets: Array<Record<string, unknown>>
  sourceVersionIds: string[]
  sourceContentHashes: Record<string, string>
  sourceCells: string[]
  skippedLayers: Array<Record<string, unknown>>
  depth: Record<string, unknown>
  preview: {
    path: string
    featureCount: number
    sha256: string
    sample: boolean
  } | null
  semantics: string[]
  warnings: string[]
  stale: boolean
}

export interface S57ThematicExportList {
  items: S57ThematicExportManifest[]
  warnings: string[]
}
