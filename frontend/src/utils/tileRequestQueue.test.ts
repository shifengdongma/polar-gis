/**
 * Tests for TileRequestQueue — concurrency limiting with overflow/abort handling.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { TileRequestQueue } from './tileRequestQueue'

// ── Fetch mock helpers ────────────────────────────────────────────────

type Deferred = {
  resolve: (r: Response) => void
  reject: (e: unknown) => void
}

const okResponse = () => ({ ok: true } as Response)

function installFetchMock(): { deferreds: Deferred[]; fetchMock: ReturnType<typeof vi.fn> } {
  const deferreds: Deferred[] = []
  const fetchMock = vi.fn(() => {
    let resolve!: (r: Response) => void
    let reject!: (e: unknown) => void
    const p = new Promise<Response>((res, rej) => {
      resolve = res
      reject = rej
    })
    deferreds.push({ resolve, reject })
    return p
  })
  vi.stubGlobal('fetch', fetchMock)
  return { deferreds, fetchMock }
}

function flushMicrotasks(): Promise<void> {
  return new Promise((resolve) => queueMicrotask(() => resolve()))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ── Tests ──────────────────────────────────────────────────────────────

describe('TileRequestQueue.fetch', () => {
  it('starts immediately when under maxConcurrent', async () => {
    const { fetchMock } = installFetchMock()
    const q = new TileRequestQueue(2, 10)
    const p = q.fetch('/a', new AbortController().signal)
    await flushMicrotasks()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(q.pending).toBe(1)
    expect(q.queued).toBe(0)
    // Settle to avoid dangling promise
    fetchMock.mock.results[0] && expect(p).toBeDefined()
  })

  it('rejects the NEWEST request when the queue overflows (older queued requests survive)', async () => {
    const { deferreds } = installFetchMock()
    const q = new TileRequestQueue(1, 2)

    const sA = new AbortController()
    const sB = new AbortController()
    const sC = new AbortController()
    const sD = new AbortController()

    const pA = q.fetch('/a', sA.signal) // starts (inFlight=1)
    const pB = q.fetch('/b', sB.signal) // queued
    const pC = q.fetch('/c', sC.signal) // queued (queue full at 2)
    const pD = q.fetch('/d', sD.signal) // overflow → reject newest

    await expect(pD).rejects.toMatchObject({ name: 'QuotaExceededError' })
    expect(q.queued).toBe(2)

    // Resolve A → B starts; B and C still resolve in FIFO order
    deferreds[0].resolve(okResponse())
    await flushMicrotasks()
    expect(q.pending).toBe(1)

    deferreds[1].resolve(okResponse())
    await flushMicrotasks()
    expect(q.pending).toBe(1)

    deferreds[2].resolve(okResponse())
    await expect(pA).resolves.toBeDefined()
    await expect(pB).resolves.toBeDefined()
    await expect(pC).resolves.toBeDefined()
    await flushMicrotasks()
    expect(q.pending).toBe(0)
    expect(q.queued).toBe(0)
  })

  it('rejects immediately when the signal is already aborted', async () => {
    installFetchMock()
    const q = new TileRequestQueue(1, 10)
    const controller = new AbortController()
    controller.abort()
    await expect(q.fetch('/a', controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('TileRequestQueue.abortAll', () => {
  it('rejects queued requests only; in-flight requests still resolve', async () => {
    const { deferreds, fetchMock } = installFetchMock()
    const q = new TileRequestQueue(1, 10)

    const pA = q.fetch('/a', new AbortController().signal) // starts
    const pB = q.fetch('/b', new AbortController().signal) // queued
    await flushMicrotasks()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    q.abortAll()
    await expect(pB).rejects.toMatchObject({ name: 'AbortError' })
    expect(q.queued).toBe(0)

    deferreds[0].resolve(okResponse())
    await expect(pA).resolves.toBeDefined()
    await flushMicrotasks()
    expect(q.pending).toBe(0)
  })
})

describe('TileRequestQueue priority and timeout', () => {
  it('serves high-priority requests first without starving normal requests', async () => {
    const order: string[] = []
    const deferreds: Deferred[] = []
    const fetchMock = vi.fn((src: string) => {
      order.push(src)
      let resolve!: (r: Response) => void
      let reject!: (e: unknown) => void
      const promise = new Promise<Response>((res, rej) => {
        resolve = res
        reject = rej
      })
      deferreds.push({ resolve, reject })
      return promise
    })
    vi.stubGlobal('fetch', fetchMock)
    const q = new TileRequestQueue(1, 20)
    const signal = () => new AbortController().signal

    const high = ['/h1', '/h2', '/h3', '/h4'].map((src) =>
      q.fetch(src, signal(), { priority: 'high' }),
    )
    const normal = q.fetch('/n1', signal())
    await flushMicrotasks()
    expect(order).toEqual(['/h1'])
    expect(q.queuedHigh).toBe(3)
    expect(q.queuedNormal).toBe(1)

    for (let i = 0; i < 5; i += 1) {
      deferreds[i]?.resolve(okResponse())
      await flushMicrotasks()
    }
    await Promise.all([...high, normal])
    // highStreak=3 then one normal, then remaining high — normal is not starved.
    expect(order).toEqual(['/h1', '/h2', '/h3', '/n1', '/h4'])
  })

  it('times out a hung fetch, frees the slot, and starts the next request', async () => {
    vi.useFakeTimers()
    const deferreds: Deferred[] = []
    const fetchMock = vi.fn(() => {
      let resolve!: (r: Response) => void
      let reject!: (e: unknown) => void
      const promise = new Promise<Response>((res, rej) => {
        resolve = res
        reject = rej
      })
      deferreds.push({ resolve, reject })
      return promise
    })
    vi.stubGlobal('fetch', fetchMock)
    const q = new TileRequestQueue(1, 10)
    const pA = q.fetch('/a', new AbortController().signal, { timeoutMs: 100 })
    const aExpectation = expect(pA).rejects.toMatchObject({ name: 'TimeoutError' })
    const pB = q.fetch('/b', new AbortController().signal)
    await vi.advanceTimersByTimeAsync(0)
    expect(q.pending).toBe(1)
    await vi.advanceTimersByTimeAsync(100)
    await aExpectation
    expect(q.pending).toBe(1) // B started after A timed out
    deferreds[1].resolve(okResponse())
    await expect(pB).resolves.toBeDefined()
    expect(q.pending).toBe(0)
    vi.useRealTimers()
  })

  it('releases the in-flight slot when fetch throws synchronously', async () => {
    const fetchMock = vi.fn((): Promise<Response> => {
      throw new Error('synchronous boom')
    })
    vi.stubGlobal('fetch', fetchMock)
    const q = new TileRequestQueue(1, 10)
    await expect(q.fetch('/a', new AbortController().signal)).rejects.toThrow('synchronous boom')
    await flushMicrotasks()
    expect(q.pending).toBe(0)
    fetchMock.mockImplementation(() => Promise.resolve(okResponse()))
    const next = q.fetch('/b', new AbortController().signal)
    await flushMicrotasks()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await expect(next).resolves.toBeDefined()
  })
})

describe('TileRequestQueue.reset', () => {
  it('keeps in-flight accounting accurate — no concurrency overshoot after reset', async () => {
    const { deferreds, fetchMock } = installFetchMock()
    const q = new TileRequestQueue(2, 10)

    const pA = q.fetch('/a', new AbortController().signal)
    const pB = q.fetch('/b', new AbortController().signal)
    await flushMicrotasks()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(q.pending).toBe(2)

    q.reset()
    expect(q.queued).toBe(0)

    // New request must NOT start while A and B are still in flight
    const pC = q.fetch('/c', new AbortController().signal)
    await flushMicrotasks()
    expect(fetchMock).toHaveBeenCalledTimes(2) // C queued, not started
    expect(q.queued).toBe(1)

    // As in-flight requests finish, C starts and the counters drain to zero
    deferreds[0].resolve(okResponse())
    await flushMicrotasks()
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(q.pending).toBe(2)

    deferreds[1].resolve(okResponse())
    await flushMicrotasks()
    expect(q.pending).toBe(1)

    deferreds[2].resolve(okResponse())
    await expect(pA).resolves.toBeDefined()
    await expect(pB).resolves.toBeDefined()
    await expect(pC).resolves.toBeDefined()
    await flushMicrotasks()
    expect(q.pending).toBe(0)
    expect(q.queued).toBe(0)
  })
})
