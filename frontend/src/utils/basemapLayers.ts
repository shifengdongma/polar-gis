/**
 * WMTS capabilities selection and basemap-id resolution.
 *
 * GWC / GeoServer capabilities vary in layer and matrix-set ordering. The old
 * implementation blindly took Contents.Layer[0] + TileMatrixSetLink[0], which
 * could pair a 3413 base map with a 3857 matrix set. These helpers select the
 * first matrix set whose SupportedCRS normalizes to the requested CRS and fail
 * closed when the choice is ambiguous.
 */

export interface WmtsSelection {
  layer: string
  matrixSet: string
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
      if (response.ok) return await response.text()
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
