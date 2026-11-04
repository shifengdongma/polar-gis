import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TileQueue from 'ol/TileQueue'
import TileState from 'ol/TileState'
import { LRUTileCache } from './tileCache'
import {
  cancelTile,
  createNativeRetryTileLoadFunction,
  createQueuedTileLoadFunction,
  createTileLoadLifecycle,
  deactivateTileLoadLifecycle,
  failTile,
} from './tileLoader'

class FakeImage extends EventTarget {
  src = ''
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  naturalWidth = 1
  naturalHeight = 1
}

class FakeTile extends EventTarget {
  state = TileState.IDLE
  image = new FakeImage()
  loadCalls = 0
  constructor(private readonly key: string) {
    super()
  }
  getKey() { return this.key }
  getState() { return this.state }
  setState(state: number) {
    this.state = state
    this.dispatchEvent(new Event('change'))
  }
  getImage() { return this.image }
  load() {
    this.loadCalls += 1
    this.setState(TileState.LOADING)
  }
}

type QueueRequest = {
  src: string
  signal: AbortSignal
  options: { priority?: string; timeoutMs?: number }
  resolve: (response: unknown) => void
  reject: (error: unknown) => void
}

class DeferredQueue {
  requests: QueueRequest[] = []
  fetch(src: string, signal: AbortSignal, options: { priority?: string; timeoutMs?: number } = {}) {
    return new Promise((resolve, reject) => {
      const request: QueueRequest = { src, signal, options, resolve, reject }
      this.requests.push(request)
      signal.addEventListener(
        'abort',
        () => reject(new DOMException('Tile request aborted', 'AbortError')),
        { once: true },
      )
    })
  }
}

const pngBlob = () => new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' })

function response(status = 200, contentType = 'image/png', body: Blob = pngBlob()) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => (name.toLowerCase() === 'content-type' ? contentType : null) },
    blob: async () => body,
    body: { cancel: vi.fn() },
  }
}

function queuedLoader(
  lifecycle = createTileLoadLifecycle('test', 1),
  queue = new DeferredQueue(),
  cache = new LRUTileCache(20, 1024 * 1024),
  retry = {},
) {
  const loader = createQueuedTileLoadFunction({
    cache,
    queue: queue as never,
    lifecycle,
    layer: 'ice:concentration',
    date: '20220101',
    projection: 'EPSG:3413',
    priority: 'high',
    retry: { maxAttempts: 3, baseDelayMs: 10, decodeTimeoutMs: 100, jitterRatio: 0, ...retry } as never,
  })
  return { loader, lifecycle, queue, cache }
}

function flushMicrotasks() {
  return new Promise((resolve) => queueMicrotask(() => resolve(undefined)))
}

async function settle() {
  await flushMicrotasks()
  await flushMicrotasks()
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:test'),
    revokeObjectURL: vi.fn(),
  })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('tile terminal state helpers', () => {
  it('releases the real OpenLayers TileQueue loading slot on cancel', () => {
    const queue = new TileQueue(() => 0, () => {})
    const first = new FakeTile('first')
    const second = new FakeTile('second')
    queue.enqueue([first as never, 'src', [0, 0, 0], 0])
    queue.loadMoreTiles(1, 1)
    expect(queue.getTilesLoading()).toBe(1)

    // Simulate the legacy loader: tile is LOADING but the abort path never
    // sets a terminal state. The global slot is now stuck.
    queue.enqueue([second as never, 'src2', [0, 0, 1], 0])
    queue.loadMoreTiles(1, 1)
    expect(second.loadCalls).toBe(0)

    cancelTile(first)
    expect(first.getState()).toBe(TileState.EMPTY)
    expect(queue.getTilesLoading()).toBe(0)
    queue.loadMoreTiles(1, 1)
    expect(second.loadCalls).toBe(1)
  })

  it('does not overwrite LOADED or ERROR when cancelling', () => {
    const loaded = new FakeTile('loaded')
    loaded.setState(TileState.LOADED)
    cancelTile(loaded)
    expect(loaded.getState()).toBe(TileState.LOADED)
    const failed = new FakeTile('failed')
    failed.setState(TileState.ERROR)
    cancelTile(failed)
    expect(failed.getState()).toBe(TileState.ERROR)
    const loading = new FakeTile('loading')
    loading.setState(TileState.LOADING)
    failTile(loading)
    expect(loading.getState()).toBe(TileState.ERROR)
  })
})

describe('createQueuedTileLoadFunction', () => {
  it('loads a valid image through the queue, caches it and revokes the object URL', async () => {
    const { loader, queue, cache } = queuedLoader()
    const tile = new FakeTile('t1')
    tile.setState(TileState.LOADING)
    loader(tile, '/tile.png')
    await settle()
    expect(queue.requests).toHaveLength(1)
    expect(queue.requests[0].options.priority).toBe('high')
    queue.requests[0].resolve(response(200))
    await settle()
    expect(tile.image.src).toBe('blob:test')
    expect(cache.has('/tile.png')).toBe(true)
    tile.image.onload?.()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
    expect(tile.getState()).not.toBe(TileState.ERROR)
  })

  it('retries a recoverable HTTP status and then succeeds', async () => {
    const { loader, queue } = queuedLoader()
    const tile = new FakeTile('t2')
    tile.setState(TileState.LOADING)
    loader(tile, '/retry.png')
    await settle()
    queue.requests[0].resolve(response(429))
    await settle()
    await vi.advanceTimersByTimeAsync(10)
    expect(queue.requests).toHaveLength(2)
    queue.requests[1].resolve(response(200))
    await settle()
    expect(tile.image.src).toBe('blob:test')
  })

  it('marks ERROR after the retry budget is exhausted', async () => {
    const { loader, queue } = queuedLoader()
    const tile = new FakeTile('t3')
    tile.setState(TileState.LOADING)
    loader(tile, '/fail.png')
    await settle()
    queue.requests[0].resolve(response(503))
    await settle()
    await vi.advanceTimersByTimeAsync(20)
    queue.requests[1]?.resolve(response(503))
    await settle()
    await vi.advanceTimersByTimeAsync(40)
    queue.requests[2]?.resolve(response(503))
    await settle()
    expect(tile.getState()).toBe(TileState.ERROR)
  })

  it('honours an ice-style 404 -> EMPTY classifier without retrying', async () => {
    const { loader, queue } = queuedLoader(
      createTileLoadLifecycle('ice', 1),
      new DeferredQueue(),
      new LRUTileCache(),
      { classifyStatus: (status: number) => (status === 404 ? 'empty' : 'retry') },
    )
    const tile = new FakeTile('t4')
    tile.setState(TileState.LOADING)
    loader(tile, '/missing.png')
    await settle()
    queue.requests[0].resolve(response(404, 'text/html'))
    await settle()
    expect(tile.getState()).toBe(TileState.EMPTY)
    expect(queue.requests).toHaveLength(1)
  })

  it('marks a default 404 as ERROR', async () => {
    const { loader, queue } = queuedLoader()
    const tile = new FakeTile('t5')
    tile.setState(TileState.LOADING)
    loader(tile, '/missing.png')
    await settle()
    queue.requests[0].resolve(response(404, 'text/html'))
    await settle()
    expect(tile.getState()).toBe(TileState.ERROR)
  })

  it('treats 204 as EMPTY', async () => {
    const { loader, queue } = queuedLoader()
    const tile = new FakeTile('t6')
    tile.setState(TileState.LOADING)
    loader(tile, '/empty.png')
    await settle()
    queue.requests[0].resolve(response(204, ''))
    await settle()
    expect(tile.getState()).toBe(TileState.EMPTY)
  })

  it('retries a timeout and then succeeds', async () => {
    const { loader, queue } = queuedLoader()
    const tile = new FakeTile('t7')
    tile.setState(TileState.LOADING)
    loader(tile, '/slow.png')
    await settle()
    queue.requests[0].reject(new DOMException('Tile request timeout', 'TimeoutError'))
    await settle()
    await vi.advanceTimersByTimeAsync(10)
    expect(queue.requests).toHaveLength(2)
    queue.requests[1].resolve(response(200))
    await settle()
    expect(tile.image.src).toBe('blob:test')
  })

  it('cancels an in-flight request when the lifecycle is deactivated', async () => {
    const { loader, queue, lifecycle, cache } = queuedLoader()
    const tile = new FakeTile('t8')
    tile.setState(TileState.LOADING)
    loader(tile, '/abort.png')
    await settle()
    deactivateTileLoadLifecycle(lifecycle)
    await settle()
    expect(tile.getState()).toBe(TileState.EMPTY)
    expect(cache.has('/abort.png')).toBe(false)
    // A late response must not enter the cache or the DOM.
    queue.requests[0].resolve(response(200))
    await settle()
    expect(tile.image.src).toBe('')
  })

  it('cancels a tile waiting in retry backoff when deactivated', async () => {
    const { loader, queue, lifecycle } = queuedLoader()
    const tile = new FakeTile('t9')
    tile.setState(TileState.LOADING)
    loader(tile, '/backoff.png')
    await settle()
    queue.requests[0].resolve(response(503))
    await settle()
    deactivateTileLoadLifecycle(lifecycle)
    expect(tile.getState()).toBe(TileState.EMPTY)
    await vi.advanceTimersByTimeAsync(1000)
    expect(queue.requests).toHaveLength(1)
  })

  it('rejects a 200 HTML body, retries and does not poison the cache', async () => {
    const { loader, queue, cache } = queuedLoader()
    const tile = new FakeTile('t10')
    tile.setState(TileState.LOADING)
    loader(tile, '/html.png')
    await settle()
    queue.requests[0].resolve(response(200, 'text/html'))
    await settle()
    expect(cache.has('/html.png')).toBe(false)
    await vi.advanceTimersByTimeAsync(10)
    expect(queue.requests).toHaveLength(2)
    queue.requests[1].resolve(response(200))
    await settle()
    expect(tile.image.src).toBe('blob:test')
  })

  it('revokes the URL, removes the poisoned cache entry and marks ERROR on decode failure', async () => {
    const { loader, queue, cache } = queuedLoader()
    const tile = new FakeTile('t11')
    tile.setState(TileState.LOADING)
    loader(tile, '/decode.png')
    await settle()
    queue.requests[0].resolve(response(200))
    await settle()
    expect(cache.has('/decode.png')).toBe(true)
    tile.image.onerror?.()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
    expect(cache.has('/decode.png')).toBe(false)
    expect(tile.getState()).toBe(TileState.ERROR)
  })
})

describe('createNativeRetryTileLoadFunction', () => {
  function nativeLoader(lifecycle = createTileLoadLifecycle('base', 1)) {
    const onSuccess = vi.fn()
    const onFailure = vi.fn()
    const loader = createNativeRetryTileLoadFunction({
      lifecycle,
      layer: 'basemap:test',
      retry: { maxAttempts: 3, baseDelayMs: 10, decodeTimeoutMs: 100, jitterRatio: 0 } as never,
      onSuccess,
      onFailure,
    })
    return { loader, lifecycle, onSuccess, onFailure }
  }

  it('loads and reports success', () => {
    const { loader, onSuccess } = nativeLoader()
    const tile = new FakeTile('n1')
    tile.setState(TileState.LOADING)
    loader(tile, '/base.png')
    expect(tile.image.src).toBe('/base.png')
    tile.image.dispatchEvent(new Event('load'))
    expect(onSuccess).toHaveBeenCalledTimes(1)
  })

  it('retries through tile.load and eventually reports failure', async () => {
    const { loader, lifecycle, onFailure } = nativeLoader()
    const tile = new FakeTile('n2')
    let currentImage = tile.image
    tile.setState(TileState.LOADING)
    loader(tile, '/base-fail.png')
    tile.setState(TileState.ERROR)
    currentImage.dispatchEvent(new Event('error'))
    await vi.advanceTimersByTimeAsync(10)
    expect(tile.loadCalls).toBe(1)

    // The consumer (OL) creates a new image on tile.load(); simulate the next
    // loader invocation with a fresh image/ERROR transition.
    tile.image = new FakeImage()
    currentImage = tile.image
    tile.setState(TileState.LOADING)
    loader(tile, '/base-fail.png')
    tile.setState(TileState.ERROR)
    currentImage.dispatchEvent(new Event('error'))
    await vi.advanceTimersByTimeAsync(20)
    expect(tile.loadCalls).toBe(2)

    tile.image = new FakeImage()
    currentImage = tile.image
    tile.setState(TileState.LOADING)
    loader(tile, '/base-fail.png')
    tile.setState(TileState.ERROR)
    currentImage.dispatchEvent(new Event('error'))
    await vi.advanceTimersByTimeAsync(100)
    expect(onFailure).toHaveBeenCalled()
    expect(tile.loadCalls).toBe(2)
    // Lifecycle still alive but the retry budget is exhausted.
    expect(lifecycle.active).toBe(true)
  })

  it('cancels a retry when the lifecycle is deactivated', async () => {
    const { loader, lifecycle } = nativeLoader()
    const tile = new FakeTile('n3')
    tile.setState(TileState.LOADING)
    loader(tile, '/base-abort.png')
    tile.setState(TileState.ERROR)
    tile.image.dispatchEvent(new Event('error'))
    deactivateTileLoadLifecycle(lifecycle)
    // The image already errored, so OL has already released its loading slot;
    // cancel must not overwrite the terminal ERROR state.
    expect(tile.getState()).toBe(TileState.ERROR)
    await vi.advanceTimersByTimeAsync(100)
    expect(tile.loadCalls).toBe(0)
  })

  it('releases the tile on an image load timeout', async () => {
    const { loader } = nativeLoader()
    const tile = new FakeTile('n4')
    tile.setState(TileState.LOADING)
    loader(tile, '/base-hang.png')
    await vi.advanceTimersByTimeAsync(100)
    expect(tile.getState()).toBe(TileState.EMPTY)
  })
})
