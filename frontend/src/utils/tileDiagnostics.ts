/**
 * Development-only tile request diagnostics.
 *
 * Records a bounded ring buffer of tile events plus aggregate counters. It is
 * intentionally disabled in production unless VITE_TILE_DIAGNOSTICS=true.
 * URLs are sanitized: only the path and the ice date parameter are kept, so
 * credentials, WMS LAYERS/BBOX parameters and other query values never enter
 * logs.
 */

export interface TileDiagnosticEvent {
  layer: string
  sourceKey: string
  date?: string
  projection?: string
  generation?: number
  url: string
  status: string
  attempts: number
  durationMs: number
  aborted: boolean
  error?: string
  at: number
}

export interface TilePipelineSnapshot {
  pending: number
  queued: number
  queuedHigh: number
  queuedNormal: number
  cacheSize: number
  cacheBytes: number
}

interface PipelineSource {
  queue: {
    pending: number
    queued: number
    queuedHigh: number
    queuedNormal: number
  }
  cache: {
    size: number
    bytes: number
  }
}

interface TileDiagnosticInput extends Omit<TileDiagnosticEvent, 'url' | 'attempts' | 'durationMs' | 'aborted' | 'at'> {
  url?: string
  attempts?: number
  durationMs?: number
  aborted?: boolean
  at?: number
}

interface TileDiagnosticsOptions {
  enabled?: boolean
  maxEvents?: number
}

interface TileCounters {
  started: number
  settled: number
  aborted: number
  failed: number
  cancelled: number
  retries: number
}

const DEFAULT_MAX_EVENTS = 400
const DATE_PARAM = /[?&]date=(\d{8})/

/** Strip query parameters except a benign date; never include tokens. */
export function sanitizeTileUrl(raw: string): string {
  if (!raw) return ''
  const withoutQuery = (raw.split('?')[0] ?? '').trim()
  const dateMatch = DATE_PARAM.exec(raw)
  return dateMatch ? `${withoutQuery}?date=${dateMatch[1]}` : withoutQuery
}

function isEnabled(options: TileDiagnosticsOptions): boolean {
  if (typeof options.enabled === 'boolean') return options.enabled
  if (typeof import.meta !== 'undefined') {
    const env = (import.meta as unknown as { env?: Record<string, string | boolean> }).env
    if (env?.VITE_TILE_DIAGNOSTICS === 'true') return true
    if (env?.DEV === true) return true
  }
  return false
}

export class TileDiagnostics {
  private readonly enabled: boolean
  private readonly maxEvents: number
  private readonly events: TileDiagnosticEvent[] = []
  private counters: TileCounters = {
    started: 0,
    settled: 0,
    aborted: 0,
    failed: 0,
    cancelled: 0,
    retries: 0,
  }
  private pipelineSource: PipelineSource | null = null

  constructor(options: TileDiagnosticsOptions = {}) {
    this.enabled = isEnabled(options)
    this.maxEvents = Math.max(1, options.maxEvents ?? DEFAULT_MAX_EVENTS)
    if (this.enabled && typeof window !== 'undefined') {
      ;(window as unknown as { __polarTileDiagnostics?: TileDiagnostics }).__polarTileDiagnostics = this
    }
  }

  get isEnabled(): boolean {
    return this.enabled
  }

  registerPipeline(source: PipelineSource): void {
    this.pipelineSource = source
  }

  record(input: TileDiagnosticInput): void {
    if (!this.enabled) return
    if (input.status === 'started') this.counters.started += 1
    if (input.status === 'retry') this.counters.retries += 1
    if (input.status === 'loaded') this.counters.settled += 1
    if (input.status === 'failed') {
      this.counters.settled += 1
      this.counters.failed += 1
    }
    if (input.status === 'cancelled') {
      this.counters.settled += 1
      this.counters.cancelled += 1
    }
    if (input.aborted) this.counters.aborted += 1
    const event: TileDiagnosticEvent = {
      layer: input.layer,
      sourceKey: input.sourceKey,
      date: input.date,
      projection: input.projection,
      generation: input.generation,
      url: sanitizeTileUrl(input.url ?? ''),
      status: input.status,
      attempts: input.attempts ?? 0,
      durationMs: input.durationMs ?? 0,
      aborted: input.aborted ?? false,
      error: input.error,
      at: input.at ?? Date.now(),
    }
    this.events.push(event)
    while (this.events.length > this.maxEvents) this.events.shift()
  }

  snapshot(): {
    events: TileDiagnosticEvent[]
    counters: TileCounters & { stuck: number }
    pipeline: TilePipelineSnapshot | null
  } {
    const pipeline = this.pipelineSource
      ? {
          pending: this.pipelineSource.queue.pending,
          queued: this.pipelineSource.queue.queued,
          queuedHigh: this.pipelineSource.queue.queuedHigh,
          queuedNormal: this.pipelineSource.queue.queuedNormal,
          cacheSize: this.pipelineSource.cache.size,
          cacheBytes: this.pipelineSource.cache.bytes,
        }
      : null
    return {
      events: [...this.events],
      counters: {
        ...this.counters,
        stuck: this.counters.started - this.counters.settled,
      },
      pipeline,
    }
  }

  clear(): void {
    this.events.length = 0
    this.counters = {
      started: 0,
      settled: 0,
      aborted: 0,
      failed: 0,
      cancelled: 0,
      retries: 0,
    }
  }
}

export const tileDiagnostics = new TileDiagnostics()
