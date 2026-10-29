/** Navigation environment/vessel API contracts (camelCase on the wire). */

export type EnvironmentField = 'bathymetry' | 'ice' | 'wind' | 'current' | 'wave'
export type DataQuality = 'real' | 'synthetic' | 'missing' | 'unknown'
export type DataPolicy = 'real_only' | 'allow_synthetic_research'

export interface TimeMatch {
  requestedTime: string
  matchedTime: string | null
  validTime: string | null
  issueTime: string | null
  observationTime?: string | null
  ingestTime?: string | null
  matchPolicy: string
  deltaSeconds: number | null
  quality: string
}

export interface FieldObservation {
  field: EnvironmentField
  available: boolean
  values: Record<string, number | boolean | null>
  units: Record<string, string>
  componentQuality: Record<string, DataQuality>
  quality: DataQuality
  source: string | null
  time: TimeMatch
  reason: string | null
  coverage: Record<string, number> | null
}

export interface EnvironmentSample {
  longitude: number
  latitude: number
  requestedTime: string
  dataPolicy: DataPolicy
  fields: Record<string, FieldObservation>
  qualitySummary: DataQuality
}

export interface EnvironmentSource {
  field: EnvironmentField
  available: boolean
  source: string | null
  units: Record<string, string>
  coverage: Record<string, number> | null
  times: string[]
  quality: DataQuality
  reason: string | null
}

export interface VectorObservation {
  id: string
  longitude: number
  latitude: number
  field: EnvironmentField
  available: boolean
  values: Record<string, number | boolean | null>
  units: Record<string, string>
  quality: DataQuality
  source: string | null
  matchedTime: string | null
  reason: string | null
}

export interface FieldQueryResponse {
  field: EnvironmentField
  requestedTime: string
  available: boolean
  source: string | null
  points: VectorObservation[]
  matchedTimes: string[]
  reason: string | null
}

export interface VesselSource {
  title: string
  url: string | null
  fields: string[]
}

export interface VesselProfile {
  id: string
  name: string
  vesselType: string
  operator: string | null
  lengthM: number
  beamM: number
  designDraftM: number
  designDisplacementT: number | null
  propulsionType: string | null
  azipodCount: number | null
  azipodPowerMwEach: number | null
  totalPropulsionPowerMw: number
  serviceSpeedMinKn: number
  serviceSpeedMaxKn: number
  maximumSpeedKn: number
  enduranceNmi: number | null
  enduranceDays: number | null
  iceClass: string | null
  continuousIceThicknessM: number
  continuousSnowThicknessM: number | null
  continuousIceSpeedMinKn: number | null
  continuousIceSpeedMaxKn: number | null
  ukcM: number
  requiredDepthM: number
  sources: VesselSource[]
  liveStateAvailable: boolean
  liveStateNote: string
}

export interface DepthSafety {
  depthM: number | null
  draftM: number
  ukcM: number
  requiredDepthM: number
  marginM: number | null
  status: 'SAFE' | 'UNSAFE' | 'UNKNOWN'
  reason: string | null
}

/** UI state for one environment overlay. */
export interface EnvironmentLayerState {
  visible: boolean
  opacity: number
  loading: boolean
  error: string
  quality: DataQuality | null
  source: string | null
  matchedTime: string | null
  available: boolean | null
  reason: string | null
}

// ── Planning tasks / candidate routes / risk grid ─────────────────────

export type PlanningRunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type RiskField = 'combined' | 'ice' | 'depth' | 'fog' | 'wind' | 'wave'
export type NavigatePickMode = 'idle' | 'start' | 'goal'

export interface PlanningPoint {
  longitude: number
  latitude: number
}

export interface PlanningCreatePayload {
  projectId: string
  start: PlanningPoint
  goal: PlanningPoint
  departureTime: string
  vesselId: string
  dataPolicy: DataPolicy
  algorithm?: 'dnsga3'
  objectives?: ['risk', 'energy', 'time']
  populationSize?: number
  generations?: number
  seed?: number
}

export interface PlanningRun {
  planId: string
  projectId: string
  vesselId: string
  mode: 'plan' | 'risk_only'
  status: PlanningRunStatus
  stage: string
  progress: number
  dataPolicy: DataPolicy
  riskModelVersion: string
  algorithmVersion: string
  errorCode: string | null
  errorMessage: string | null
  resultSummary: Record<string, unknown>
  environmentSnapshot: Record<string, unknown>
  cancelRequested: boolean
  queuedAt: string
  startedAt: string | null
  finishedAt: string | null
  createdAt: string
}

export interface PlanningRoute {
  routeId: string
  planId: string
  routeIndex: number
  label: string
  recommended: boolean
  coordinates: [number, number][]
  riskScore: number
  riskComponents: Record<string, number | null>
  energyMWh: number
  timeHours: number
  distanceKm: number
  sourceQuality: DataQuality | 'unknown'
  algorithmVersion: string
  createdAt: string
}

export interface RiskGridFeature {
  type: 'Feature'
  id?: string
  geometry: { type: 'Polygon'; coordinates: number[][][] }
  properties: {
    cellId: string
    value: number | null
    traversable: boolean | null
    quality: string | null
    riskModelVersion: string | null
  }
}

export interface RiskGridCollection {
  type: 'FeatureCollection'
  field: RiskField
  totalCells: number
  returnedCells: number
  snapshotTime: string | null
  features: RiskGridFeature[]
}

export interface RiskCell {
  cellId: string
  row: number
  column: number
  center: { latitude: number; longitude: number }
  bounds: Record<string, number>
  geometry: number[][]
  environment: Record<string, number | boolean | null>
  risk: Record<string, number | null>
  quality: Record<string, string>
  sources: Record<string, string>
  traversable: boolean
  blockedReason: string | null
  riskModelVersion: string
  isLand: boolean
  landRatio: number
}

export interface EvaluateRouteResult {
  traversable: boolean
  riskScore: number | null
  energyMWh: number | null
  timeHours: number | null
  distanceKm: number | null
  sourceQuality: string | null
  cellIds: string[]
  reason: string | null
  blockedCellId: string | null
  snapshotId: string | null
}

export interface RoutePlanningSnapshot {
  planId: string
  routeId: string
  geometryHash: string
  risk: number
  energyMWh: number
  timeHours: number
  distanceKm: number
  snapshotTime: string
}
