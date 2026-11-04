/**
 * Tile request queue with concurrency limiting and two priority lanes.
 *
 * The queue is shared by S-57 WMS, ice and environment tile loaders. Ice
 * requests use the high-priority lane so a large S-57 batch cannot starve the
 * currently selected ice date. A fairness rule starts at most three
 * consecutive high-priority requests before serving one waiting normal
 * request, so normal traffic is delayed but never permanently starved.
 *
 * Returns the raw fetch Response — the caller handles blob extraction,
 * caching, status checking, and retry logic.
 */

export type TilePriority = 'high' | 'normal'

export interface TileQueueFetchOptions {
  priority?: TilePriority
  /** 0 disables the per-attempt timeout (keeps the legacy two-arg contract). */
  timeoutMs?: number
}

interface QueuedRequest {
  src: string
  signal: AbortSignal
  priority: TilePriority
  timeoutMs: number
  resolve: (value: Response) => void
  reject: (reason?: unknown) => void
}

const HIGH_PRIORITY_STREAK = 3

export class TileRequestQueue {
  private maxConcurrent: number
  private maxQueue: number
  private inFlight = 0
  private highQueue: QueuedRequest[] = []
  private normalQueue: QueuedRequest[] = []
  private highStreak = 0

  constructor(maxConcurrent = 16, maxQueue = 512) {
    this.maxConcurrent = maxConcurrent
    this.maxQueue = maxQueue
  }

  /**
   * Enqueue a tile fetch request.
   *
   * Rejects if the signal is already aborted, on queue overflow (the NEWEST
   * request is rejected so its tile errors/retries later), on timeout, or on
   * network failure. HTTP errors (4xx, 5xx) resolve successfully — the caller
   * inspects response.status for retry decisions.
   */
  fetch(
    src: string,
    signal: AbortSignal,
    options: TileQueueFetchOptions = {},
  ): Promise<Response> {
    const priority = options.priority ?? 'normal'
    const timeoutMs = Math.max(0, options.timeoutMs ?? 0)
    return new Promise<Response>((resolve, reject) => {
      if (signal.aborted) {
        reject(new DOMException('Tile request aborted', 'AbortError'))
        return
      }

      const request: QueuedRequest = {
        src,
        signal,
        priority,
        timeoutMs,
        resolve,
        reject,
      }

      const onAbort = () => {
        if (this.removeQueued(request)) {
          request.reject(new DOMException('Tile request aborted', 'AbortError'))
        }
      }
      signal.addEventListener('abort', onAbort, { once: true })

      const wrappedResolve = (value: Response) => {
        signal.removeEventListener('abort', onAbort)
        resolve(value)
      }
      const wrappedReject = (reason?: unknown) => {
        signal.removeEventListener('abort', onAbort)
        reject(reason)
      }
      request.resolve = wrappedResolve
      request.reject = wrappedReject

      if (this.inFlight < this.maxConcurrent) {
        this.startRequest(request)
      } else if (this.queued >= this.maxQueue) {
        request.reject(new DOMException('Tile queue overflow', 'QuotaExceededError'))
      } else if (priority === 'high') {
        this.highQueue.push(request)
      } else {
        this.normalQueue.push(request)
      }
    })
  }

  get pending(): number {
    return this.inFlight
  }

  get queued(): number {
    return this.highQueue.length + this.normalQueue.length
  }

  get queuedHigh(): number {
    return this.highQueue.length
  }

  get queuedNormal(): number {
    return this.normalQueue.length
  }

  get stats(): {
    pending: number
    queued: number
    queuedHigh: number
    queuedNormal: number
  } {
    return {
      pending: this.pending,
      queued: this.queued,
      queuedHigh: this.queuedHigh,
      queuedNormal: this.queuedNormal,
    }
  }

  /**
   * Reject all queued requests. In-flight requests continue; callers abort
   * them through their AbortSignal.
   */
  abortAll(): void {
    const abortError = () => new DOMException('Queue aborted', 'AbortError')
    for (const request of [...this.highQueue, ...this.normalQueue]) {
      request.reject(abortError())
    }
    this.highQueue.length = 0
    this.normalQueue.length = 0
    this.highStreak = 0
  }

  /** Full reset: abort queued requests only; in-flight accounting is kept. */
  reset(): void {
    this.abortAll()
  }

  // ── Private ─────────────────────────────────────────────────────────

  private removeQueued(request: QueuedRequest): boolean {
    const queue = request.priority === 'high' ? this.highQueue : this.normalQueue
    const index = queue.indexOf(request)
    if (index < 0) return false
    queue.splice(index, 1)
    return true
  }

  private nextRequest(): QueuedRequest | null {
    const canTakeHigh =
      this.highQueue.length > 0 &&
      (this.highStreak < HIGH_PRIORITY_STREAK || this.normalQueue.length === 0)
    if (canTakeHigh) {
      return this.highQueue.shift() ?? null
    }
    if (this.normalQueue.length > 0) {
      return this.normalQueue.shift() ?? null
    }
    if (this.highQueue.length > 0) {
      return this.highQueue.shift() ?? null
    }
    return null
  }

  private startRequest(request: QueuedRequest): void {
    if (request.signal.aborted) {
      request.reject(new DOMException('Tile request aborted', 'AbortError'))
      this.tryDequeue()
      return
    }

    if (request.priority === 'high') {
      this.highStreak += 1
    } else {
      this.highStreak = 0
    }
    this.inFlight += 1
    let settled = false
    const controller = new AbortController()
    let timeoutTimer: number | undefined
    let timedOut = false

    const cleanup = () => {
      if (timeoutTimer !== undefined) {
        clearTimeout(timeoutTimer)
        timeoutTimer = undefined
      }
      request.signal.removeEventListener('abort', onCallerAbort)
    }

    const settleResolve = (response: Response) => {
      if (settled) return
      settled = true
      cleanup()
      this.inFlight -= 1
      this.tryDequeue()
      request.resolve(response)
    }

    const settleReject = (reason: unknown) => {
      if (settled) return
      settled = true
      cleanup()
      this.inFlight -= 1
      this.tryDequeue()
      request.reject(reason)
    }

    const onCallerAbort = () => {
      if (settled) return
      controller.abort()
      settleReject(new DOMException('Tile request aborted', 'AbortError'))
    }
    request.signal.addEventListener('abort', onCallerAbort, { once: true })

    if (request.timeoutMs > 0) {
      timeoutTimer = window.setTimeout(() => {
        if (settled) return
        timedOut = true
        controller.abort()
        settleReject(new DOMException('Tile request timeout', 'TimeoutError'))
      }, request.timeoutMs)
    }

    let fetchPromise: Promise<Response>
    try {
      fetchPromise = fetch(request.src, { mode: 'cors', signal: controller.signal })
    } catch (error) {
      settleReject(error)
      return
    }

    fetchPromise
      .then((response) => {
        if (settled) return
        if (timedOut) {
          settleReject(new DOMException('Tile request timeout', 'TimeoutError'))
          return
        }
        settleResolve(response)
      })
      .catch((error) => {
        if (settled) return
        if (timedOut) {
          settleReject(new DOMException('Tile request timeout', 'TimeoutError'))
          return
        }
        if (request.signal.aborted) {
          settleReject(new DOMException('Tile request aborted', 'AbortError'))
          return
        }
        settleReject(error)
      })
  }

  private tryDequeue(): void {
    while (this.inFlight < this.maxConcurrent) {
      const next = this.nextRequest()
      if (!next) return
      if (next.signal.aborted) {
        next.reject(new DOMException('Tile request aborted', 'AbortError'))
        continue
      }
      this.startRequest(next)
    }
  }
}
