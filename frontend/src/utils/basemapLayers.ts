/**
 * WMTS capabilities selection and basemap-id resolution.
 *
 * GWC / GeoServer capabilities vary in layer and matrix-set ordering. The old
 * implementation blindly took Contents.Layer[0] + TileMatrixSetLink[0], which
 * could pair a 3413 base map with a 3857 matrix set. These helpers select the
 * first matrix set whose SupportedCRS normalizes to the requested CRS and fail
 * closed when the choice is ambiguous.
 *
 * Large GeoServer instances (~5.8k GWC layers) make the instance-wide WMTS
 * GetCapabilities document unusable: it reaches hundreds of MB (each layer
 * repeats TileMatrixSetLimits for every zoom level) and OOMs a small heap. The
 * overview basemaps therefore store a direct GetTile URL template and are
 * built locally from the GWC grids below, never by fetching GetCapabilities.
 */

import TileGrid from 'ol/tilegrid/TileGrid'

export interface WmtsSelection {
  layer: string
  matrixSet: string
}

/** GWC gridset definitions used by the overview basemap GetTile templates. */
interface GwcGridSpec {
  extent: [number, number, number, number]
  baseResolution: number
  levels: number
}

const GWC_GRIDS: Record<string, GwcGridSpec> = {
  // GWC's canonical Web Mercator gridset (EPSG:900913), 31 levels.
  'EPSG:3857': {
    extent: [-20037508.34, -20037508.34, 20037508.34, 20037508.34],
    baseResolution: 156543.03390625,
    levels: 31,
  },
  // Custom Arctic gridset created by the backend (`_default_gridset_levels`),
  // extent from GWC_3413_EXTENT and 22 levels.
  'EPSG:3413': {
    extent: [-4194304, -4194304, 4194304, 4194304],
    baseResolution: 32768,
    levels: 22,
  },
}

/** Build the exact GWC tile grid for a CRS, or null when no grid is known. */
export function createGwcTileGrid(crs: string): TileGrid | null {
  const spec = GWC_GRIDS[normalizeCrsName(crs)]
  if (!spec) return null
  const resolutions = Array.from(
    { length: spec.levels },
    (_, level) => spec.baseResolution / 2 ** level,
  )
  return new TileGrid({
    extent: spec.extent,
    origin: [spec.extent[0], spec.extent[3]],
    resolutions,
    tileSize: 256,
  })
}

/** True when a WMTS/XYZ url template can be used without GetCapabilities. */
export function isDirectTileTemplate(url: string): boolean {
  return /\{z\}/i.test(url) && /\{x\}/i.test(url) && /\{y\}/i.test(url)
}

/**
 * Extract the message from an OWS ExceptionReport body. GeoServer/GWC return
 * these with HTTP 200, so `response.ok` alone does not mean success.
 */
export function extractOwsException(text: string): string | null {
  if (!/<(?:[\w.-]+:)?ExceptionReport\b/i.test(text)) return null
  const match =
    /<(?:[\w.-]+:)?ExceptionText[^>]*>([\s\S]*?)<\/(?:[\w.-]+:)?ExceptionText>/i.exec(text)
  const message = decodeXmlEntities(match?.[1]?.trim() || '')
  return message || 'WMTS 服务返回异常'
}

function decodeXmlEntities(value: string): string {
  return value
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&')
}

export function normalizeCrsName(value: string | null | undefined): string {
  const raw = String(value ?? '').trim()
  if (!raw) return ''
  if (/^CRS:84$/i.test(raw)) return 'EPSG:4326'
  if (/^EPSG:900913$/i.test(raw)) return 'EPSG:3857'
  const direct = /^EPSG:(\d{3,6})$/i.exec(raw)
  if (direct) return `EPSG:${direct[1]}`
  const match = /EPSG.*?(\d{4,6})\s*$/i.exec(raw)
  return match ? `EPSG:${match[1]}` : raw
}

function asArray<T>(value: T | T[] | undefined | null): T[] {
  if (value == null) return []
  return Array.isArray(value) ? value : [value]
}

/** Rewrite URN/URL SupportedCRS values to EPSG:xxxx for OL's projection lookup. */
export function normalizeCapabilitiesCrs(capabilities: any): void {
  const matrixSets = asArray(capabilities?.Contents?.TileMatrixSet)
  for (const matrixSet of matrixSets) {
    if (matrixSet?.SupportedCRS) {
      matrixSet.SupportedCRS = normalizeCrsName(matrixSet.SupportedCRS)
    }
  }
}

/**
 * Choose the layer + matrix set matching `targetCrs`. Returns null when no
 * matrix set matches, or when several layers match and no preferred layer
 * name disambiguates them. Never falls back to a different CRS.
 */
export function selectWmtsLayerAndMatrix(
  capabilities: any,
  targetCrs: string,
  preferredName?: string,
): WmtsSelection | null {
  const desired = normalizeCrsName(targetCrs)
  if (!desired) return null
  const matrixCrs = new Map<string, string>()
  for (const matrixSet of asArray(capabilities?.Contents?.TileMatrixSet)) {
    if (matrixSet?.Identifier) {
      matrixCrs.set(String(matrixSet.Identifier), normalizeCrsName(matrixSet.SupportedCRS))
    }
  }
  const candidates: WmtsSelection[] = []
  const seen = new Set<string>()
  for (const layer of asArray(capabilities?.Contents?.Layer)) {
    const layerId = String(layer?.Identifier ?? '')
    if (!layerId) continue
    for (const link of asArray(layer?.TileMatrixSetLink)) {
      const matrixSetId = String(link?.TileMatrixSet ?? '')
      if (!matrixSetId) continue
      if (matrixCrs.get(matrixSetId) !== desired) continue
      const key = `${layerId}|${matrixSetId}`
      if (seen.has(key)) continue
      seen.add(key)
      candidates.push({ layer: layerId, matrixSet: matrixSetId })
    }
  }
  if (candidates.length === 0) return null
  if (preferredName) {
    const preferred = preferredName.toLowerCase()
    const preferredCandidates = candidates.filter((candidate) =>
      candidate.layer.toLowerCase().includes(preferred),
    )
    if (preferredCandidates.length === 1) return preferredCandidates[0]
    if (preferredCandidates.length > 1) return null
  }
  return candidates.length === 1 ? candidates[0] : null
}

export interface FetchCapabilitiesOptions {
  fetchImpl?: typeof fetch
  attempts?: number
  baseDelayMs?: number
  timeoutMs?: number
}

const RETRYABLE_STATUS = new Set([408, 425, 429, 500, 502, 503, 504])

/**
 * Refuse to download an oversized capabilities document. On ~5.8k GWC layers
 * the instance-wide document reaches ~700 MB — enough to hang or crash the
 * browser long before OpenLayers can parse it.
 */
const MAX_CAPABILITIES_BYTES = 32 * 1024 * 1024

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Fetch WMTS capabilities with bounded retry. 404/403 fail immediately;
 * transient statuses and timeouts retry with a short backoff.
 */
export async function fetchWmtsCapabilitiesWithRetry(
  url: string,
  options: FetchCapabilitiesOptions = {},
): Promise<string> {
  const fetchImpl = options.fetchImpl ?? fetch
  const attempts = Math.max(1, options.attempts ?? 3)
  const baseDelayMs = Math.max(0, options.baseDelayMs ?? 500)
  const timeoutMs = Math.max(1, options.timeoutMs ?? 15000)
  let lastError: unknown
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const controller = new AbortController()
    let timer: number | undefined
    try {
      const timeout = new Promise<never>((_, reject) => {
        timer = window.setTimeout(() => {
          controller.abort()
          reject(new DOMException('WMTS capabilities timeout', 'TimeoutError'))
        }, timeoutMs)
      })
      const response = await Promise.race([
        fetchImpl(url, { signal: controller.signal }),
        timeout,
      ])
      if (response.ok) {
        const declaredLength = Number(response.headers?.get?.('content-length') ?? '')
        if (Number.isFinite(declaredLength) && declaredLength > MAX_CAPABILITIES_BYTES) {
          const tooLarge = new Error(
            `WMTS capabilities 体积过大（${Math.round(declaredLength / 1024 / 1024)} MB），` +
              '请改用 GetTile 瓦片模板',
          )
          ;(tooLarge as Error & { retryable?: boolean }).retryable = false
          throw tooLarge
        }
        const text = await response.text()
        const owsError = extractOwsException(text)
        if (owsError) {
          // GeoServer reports OOM/other server errors inside a 200 OWS
          // ExceptionReport. Retrying only adds load; fail fast with the
          // server's message instead of parsing an empty document.
          const serviceError = new Error(`WMTS 服务异常: ${owsError}`)
          ;(serviceError as Error & { retryable?: boolean }).retryable = false
          throw serviceError
        }
        return text
      }
      const statusError = new Error(`WMTS capabilities HTTP ${response.status}`)
      if (!RETRYABLE_STATUS.has(response.status)) {
        ;(statusError as Error & { retryable?: boolean }).retryable = false
        throw statusError
      }
      lastError = statusError
    } catch (error) {
      if ((error as { retryable?: boolean } | null)?.retryable === false) throw error
      lastError = error
    } finally {
      if (timer !== undefined) clearTimeout(timer)
    }
    if (attempt < attempts) await wait(baseDelayMs * attempt)
  }
  throw lastError instanceof Error ? lastError : new Error('WMTS capabilities unavailable')
}

/** Keep a per-CRS remembered selection when it is still available. */
export function resolveActiveBaseMapId(availableIds: string[], remembered?: string): string {
  if (remembered && availableIds.includes(remembered)) return remembered
  return availableIds[0] ?? ''
}
