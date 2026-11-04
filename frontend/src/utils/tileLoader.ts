/**
 * Reliable tile load lifecycle for custom OpenLayers tileLoadFunctions.
 *
 * OpenLayers 10 sets a tile to LOADING before invoking the custom loader and
 * decrements the map-wide TileQueue loading counter only on LOADED / ERROR /
 * EMPTY. A loader that aborts and returns without a terminal state therefore
 * leaks a global loading slot; after 16 leaks no layer (including the native
 * basemap loader) can start a tile.
 *
 * Rules enforced here:
 * - intentional cancellation / source replacement -> TileState.EMPTY
 * - exhausted retries / genuine failure            -> TileState.ERROR
 * - success                                         -> OL image load -> LOADED
 * Every path removes its controller, timers, image listeners and object URL.
 */
import TileState from 'ol/TileState'
import type { LRUTileCache } from './tileCache'
import type { TileDiagnostics } from './tileDiagnostics'
import type { TilePriority, TileRequestQueue } from './tileRequestQueue'

export type { TilePriority }

export interface TileImageLike {
  src: string
  onload: (() => void) | null
  onerror: (() => void) | null
  addEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ) => void
  removeEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | EventListenerOptions,
  ) => void
}

export interface TileLike {
  getState?: () => number
  setState: (state: number) => void
  getImage: () => TileImageLike
  addEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ) => void
  removeEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | EventListenerOptions,
  ) => void
}

export interface TileLoadLifecycle {
  key: string
  generation: number
  active: boolean
  controllers: Set<AbortController>
  timers: Set<number>
  tiles: Set<TileLike>
  cleanups: Set<() => void>
}

export function createTileLoadLifecycle(key: string, generation: number): TileLoadLifecycle {
  return {
    key,
    generation,
    active: true,
    controllers: new Set(),
    timers: new Set(),
    tiles: new Set(),
    cleanups: new Set(),
  }
}

export function deactivateTileLoadLifecycle(lifecycle: TileLoadLifecycle): void {
  lifecycle.active = false
  for (const controller of lifecycle.controllers) controller.abort()
  lifecycle.controllers.clear()
  for (const timer of lifecycle.timers) clearTimeout(timer)
  lifecycle.timers.clear()
  // Cancel tiles before running cleanups: cleanup() removes the tile from
  // lifecycle.tiles, which would otherwise make the subsequent loop a no-op.
  for (const tile of [...lifecycle.tiles]) cancelTile(tile)
  lifecycle.tiles.clear()
  for (const cleanup of lifecycle.cleanups) cleanup()
  lifecycle.cleanups.clear()
}

export function cancelTile(tile: TileLike): void {
  const state = tile.getState?.()
  if (state === TileState.IDLE || state === TileState.LOADING || state === undefined) {
    tile.setState(TileState.EMPTY)
  }
}

export function failTile(tile: TileLike): void {
  const state = tile.getState?.()
  if (state === TileState.IDLE || state === TileState.LOADING || state === undefined) {
    tile.setState(TileState.ERROR)
  }
}

export interface TileRetryPolicy {
  maxAttempts: number
  baseDelayMs: number
  maxDelayMs: number
  retryStatuses: number[]
  retryNetwork: boolean
  decodeTimeoutMs: number
  jitterRatio: number
  classifyStatus?: (status: number) => 'retry' | 'error' | 'empty'
}

const DEFAULT_RETRY: TileRetryPolicy = {
  maxAttempts: 3,
  baseDelayMs: 400,
  maxDelayMs: 5000,
  retryStatuses: [408, 425, 429, 500, 502, 503, 504],
  retryNetwork: true,
  decodeTimeoutMs: 15000,
  jitterRatio: 0.2,
}

function resolveRetry(overrides: Partial<TileRetryPolicy> = {}): TileRetryPolicy {
  return { ...DEFAULT_RETRY, ...overrides }
}

function backoffDelay(attempt: number, policy: TileRetryPolicy): number {
  const base = Math.min(policy.maxDelayMs, policy.baseDelayMs * 2 ** Math.max(0, attempt - 1))
  const jitter = base * policy.jitterRatio * (Math.random() * 2 - 1)
  return Math.max(0, Math.round(base + jitter))
}

function isImageBlob(blob: Blob): boolean {
  if (!blob || blob.size <= 0) return false
  return !blob.type || blob.type.toLowerCase().startsWith('image/')
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  )
}

function cancelResponseBody(response: Response): void {
  try {
    const promise = response.body?.cancel()
    if (promise) void promise.catch(() => undefined)
  } catch {
    // A mocked/closed body must never break the loader.
  }
}

function isTimeoutError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'TimeoutError') ||
    (error instanceof Error && error.name === 'TimeoutError')
  )
}

function isQueueOverflow(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'QuotaExceededError') ||
    (error instanceof Error && error.name === 'QuotaExceededError')
  )
}

interface QueuedLoaderOptions {
  cache: LRUTileCache
  queue: TileRequestQueue
  lifecycle: TileLoadLifecycle
  layer: string
  date?: string
  projection?: string
  priority?: TilePriority
  retry?: Partial<TileRetryPolicy>
  diagnostics?: TileDiagnostics
  onRetry?: () => void
  onSuccess?: () => void
  onFailure?: (error?: unknown) => void
}

export function createQueuedTileLoadFunction(
  options: QueuedLoaderOptions,
): (tile: TileLike, src: string) => void {
  const policy = resolveRetry(options.retry)
  const diagnostics = options.diagnostics

  return (tile, src) => {
    if (!options.lifecycle.active) {
      cancelTile(tile)
      return
    }

    const startedAt = Date.now()
    let attempts = 0
    let settled = false
    let objectUrl: string | null = null
    const controller = new AbortController()
    const image = tile.getImage()
    const lifecycle = options.lifecycle
    lifecycle.controllers.add(controller)
    lifecycle.tiles.add(tile)

    diagnostics?.record({
      layer: options.layer,
      sourceKey: lifecycle.key,
      date: options.date,
      projection: options.projection,
      generation: lifecycle.generation,
      url: src,
      status: 'started',
    })

    const onChange = () => {
      if (tile.getState?.() === TileState.EMPTY) {
        controller.abort()
        finish('cancelled')
      }
    }
    tile.addEventListener('change', onChange)

    const clearDecodeTimer = () => {
      if (decodeTimer !== undefined) {
        clearTimeout(decodeTimer)
        lifecycle.timers.delete(decodeTimer)
        decodeTimer = undefined
      }
    }

    const revokeObjectUrl = () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
        objectUrl = null
      }
    }

    let decodeTimer: number | undefined

    const cleanup = () => {
      clearDecodeTimer()
      revokeObjectUrl()
      tile.removeEventListener('change', onChange)
      image.onload = null
      image.onerror = null
      lifecycle.cleanups.delete(cleanup)
      lifecycle.tiles.delete(tile)
    }
    lifecycle.cleanups.add(cleanup)

    const finish = (status: 'loaded' | 'failed' | 'cancelled', error?: unknown) => {
      if (settled) return
      settled = true
      cleanup()
      lifecycle.controllers.delete(controller)
      if (status === 'cancelled') cancelTile(tile)
      if (status === 'failed') failTile(tile)
      diagnostics?.record({
        layer: options.layer,
        sourceKey: lifecycle.key,
        date: options.date,
        projection: options.projection,
        generation: lifecycle.generation,
        url: src,
        status,
        attempts,
        durationMs: Date.now() - startedAt,
        aborted: status === 'cancelled',
        error: error instanceof Error ? error.message : error ? String(error) : undefined,
      })
      if (status === 'loaded') options.onSuccess?.()
      if (status === 'failed') options.onFailure?.(error)
    }

    const scheduleRetry = (error?: unknown) => {
      if (settled || !lifecycle.active) {
        finish('cancelled')
        return
      }
      if (attempts >= policy.maxAttempts) {
        finish('failed', error)
        return
      }
      diagnostics?.record({
        layer: options.layer,
        sourceKey: lifecycle.key,
        date: options.date,
        projection: options.projection,
        generation: lifecycle.generation,
        url: src,
        status: 'retry',
        attempts,
        durationMs: Date.now() - startedAt,
        error: error instanceof Error ? error.message : error ? String(error) : undefined,
      })
      options.onRetry?.()
      const timer = window.setTimeout(() => {
        lifecycle.timers.delete(timer)
        if (!lifecycle.active || settled) {
          finish('cancelled')
          return
        }
        tryLoad()
      }, backoffDelay(attempts, policy))
      lifecycle.timers.add(timer)
    }

    const useBlob = (blob: Blob) => {
      if (!lifecycle.active || settled) {
        finish('cancelled')
        return
      }
      objectUrl = URL.createObjectURL(blob)
      image.onload = () => {
        revokeObjectUrl()
        finish('loaded')
      }
      image.onerror = () => {
        options.cache.delete(src)
        revokeObjectUrl()
        finish('failed', new Error('image decode failed'))
      }
      clearDecodeTimer()
      decodeTimer = window.setTimeout(() => {
        lifecycle.timers.delete(decodeTimer as number)
        decodeTimer = undefined
        if (!settled) {
          revokeObjectUrl()
          finish('failed', new Error('image decode timeout'))
        }
      }, policy.decodeTimeoutMs)
      lifecycle.timers.add(decodeTimer)
      image.src = objectUrl
    }

    const handleResponse = async (response: Response) => {
      if (!lifecycle.active || settled) {
        finish('cancelled')
        return
      }
      if (response.status === 204) {
        cancelResponseBody(response)
        finish('cancelled')
        return
      }
      if (!response.ok) {
        cancelResponseBody(response)
        const classification = policy.classifyStatus?.(response.status) ?? 'retry'
        if (classification === 'empty') {
          finish('cancelled')
          return
        }
        if (
          classification === 'retry' &&
          policy.retryStatuses.includes(response.status)
        ) {
          scheduleRetry(new Error(`HTTP ${response.status}`))
          return
        }
        finish('failed', new Error(`HTTP ${response.status}`))
        return
      }
      const contentType = response.headers.get('content-type')?.toLowerCase() ?? ''
      if (contentType && !contentType.startsWith('image/')) {
        cancelResponseBody(response)
        scheduleRetry(new Error(`unexpected content-type ${contentType}`))
        return
      }
      let blob: Blob
      try {
        blob = await response.blob()
      } catch (error) {
        scheduleRetry(error)
        return
      }
      if (!isImageBlob(blob)) {
        scheduleRetry(new Error('response is not an image'))
        return
      }
      options.cache.set(src, blob)
      useBlob(blob)
    }

    const tryLoad = () => {
      if (!lifecycle.active || settled) {
        finish('cancelled')
        return
      }
      attempts += 1
      const cached = options.cache.get(src)
      if (cached) {
        if (isImageBlob(cached)) {
          useBlob(cached)
          return
        }
        options.cache.delete(src)
      }
      options.queue
        .fetch(src, controller.signal, {
          priority: options.priority ?? 'normal',
          timeoutMs: 30000,
        })
        .then((response) => handleResponse(response))
        .catch((error) => {
          if (!lifecycle.active || settled) {
            finish('cancelled')
            return
          }
          if (isAbortError(error)) {
            finish('cancelled')
            return
          }
          if (isTimeoutError(error) || isQueueOverflow(error) || error instanceof TypeError) {
            scheduleRetry(error)
            return
          }
          finish('failed', error)
        })
    }

    tryLoad()
  }
}

interface NativeLoaderOptions {
  lifecycle: TileLoadLifecycle
  layer: string
  retry?: Partial<TileRetryPolicy>
  diagnostics?: TileDiagnostics
  onRetry?: () => void
  onSuccess?: () => void
  onFailure?: (error?: unknown) => void
}

interface NativeAttemptState {
  lifecycleKey: string
  attempts: number
}

const nativeAttempts = new WeakMap<object, NativeAttemptState>()

export function createNativeRetryTileLoadFunction(
  options: NativeLoaderOptions,
): (tile: TileLike, src: string) => void {
  const policy = resolveRetry(options.retry)
  const diagnostics = options.diagnostics

  return (tile, src) => {
    if (!options.lifecycle.active) {
      cancelTile(tile)
      return
    }
    const lifecycle = options.lifecycle
    const image = tile.getImage()
    const startedAt = Date.now()
    let settled = false
    let state = nativeAttempts.get(tile)
    if (!state || state.lifecycleKey !== lifecycle.key) {
      state = { lifecycleKey: lifecycle.key, attempts: 0 }
      nativeAttempts.set(tile, state)
    }
    lifecycle.tiles.add(tile)
    // A retry re-enters this loader through tile.load(); only the first entry is
    // a new logical attempt, so the started/settled counters stay balanced.
    if (state.attempts === 0) {
      diagnostics?.record({
        layer: options.layer,
        sourceKey: lifecycle.key,
        generation: lifecycle.generation,
        url: src,
        status: 'started',
      })
    }

    let timeoutTimer: number | undefined
    const cleanupImage = () => {
      if (timeoutTimer !== undefined) {
        clearTimeout(timeoutTimer)
        lifecycle.timers.delete(timeoutTimer)
        timeoutTimer = undefined
      }
      image.removeEventListener('load', onLoad)
      image.removeEventListener('error', onError)
    }
    const cleanup = () => {
      cleanupImage()
      lifecycle.cleanups.delete(cleanup)
      lifecycle.tiles.delete(tile)
    }

    function finish(status: 'loaded' | 'failed' | 'cancelled', error?: unknown) {
      if (settled) return
      settled = true
      cleanup()
      if (status === 'cancelled') cancelTile(tile)
      if (status === 'failed') failTile(tile)
      if (status === 'loaded') {
        nativeAttempts.delete(tile)
        options.onSuccess?.()
      }
      if (status === 'failed') options.onFailure?.(error)
      diagnostics?.record({
        layer: options.layer,
        sourceKey: lifecycle.key,
        generation: lifecycle.generation,
        url: src,
        status,
        attempts: state?.attempts ?? 0,
        durationMs: Date.now() - startedAt,
        aborted: status === 'cancelled',
        error: error instanceof Error ? error.message : error ? String(error) : undefined,
      })
    }

    function onLoad() {
      finish('loaded')
    }

    function onError() {
      if (settled) return
      cleanupImage()
      if (!lifecycle.active || tile.getState?.() === TileState.EMPTY) {
        finish('cancelled')
        return
      }
      state = nativeAttempts.get(tile) ?? { lifecycleKey: lifecycle.key, attempts: 0 }
      state.attempts += 1
      nativeAttempts.set(tile, state)
      if (state.attempts >= policy.maxAttempts) {
        finish('failed', new Error('image load failed'))
        return
      }
      options.onRetry?.()
      diagnostics?.record({
        layer: options.layer,
        sourceKey: lifecycle.key,
        generation: lifecycle.generation,
        url: src,
        status: 'retry',
        attempts: state.attempts,
        durationMs: Date.now() - startedAt,
        error: 'image load failed',
      })
      const timer = window.setTimeout(() => {
        lifecycle.timers.delete(timer)
        if (!lifecycle.active || settled) {
          finish('cancelled')
          return
        }
        if (tile.getState?.() === TileState.ERROR) {
          ;(tile as unknown as { load: () => void }).load()
        } else {
          finish('cancelled')
        }
      }, backoffDelay(state.attempts, policy))
      lifecycle.timers.add(timer)
    }

    image.addEventListener('load', onLoad, { once: true })
    image.addEventListener('error', onError, { once: true })
    lifecycle.cleanups.add(cleanup)
    timeoutTimer = window.setTimeout(() => {
      lifecycle.timers.delete(timeoutTimer as number)
      timeoutTimer = undefined
      if (!settled) finish('cancelled', new Error('image load timeout'))
    }, policy.decodeTimeoutMs)
    lifecycle.timers.add(timeoutTimer)
    image.src = src
  }
}
