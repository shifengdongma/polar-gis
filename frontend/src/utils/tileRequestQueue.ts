/**
 * Tile request queue with concurrency limiting.
 *
 * Prevents the browser connection pool from being overwhelmed when many
 * TileWMS sources request tiles simultaneously. Caps in-flight fetch()
 * calls and queues excess requests in FIFO order.
 *
 * The queue is shared across ALL WMS sources (per-layer, merged, bundle)
 * so the total concurrent tile fetches stay within the configured limit.
 *
 * Returns the raw fetch Response — the caller handles blob extraction,
 * caching, status checking, and retry logic.
 */

interface QueuedRequest {
  src: string
  signal: AbortSignal
  resolve: (value: Response) => void
  reject: (reason?: unknown) => void
}

export class TileRequestQueue {
  private maxConcurrent: number
  private maxQueue: number
  private inFlight = 0
  private queue: QueuedRequest[] = []

  constructor(maxConcurrent = 16, maxQueue = 512) {
    this.maxConcurrent = maxConcurrent
    this.maxQueue = maxQueue
  }

  /**
   * Enqueue a tile fetch request.
   *
   * Returns a Promise<Response> that resolves with the raw fetch Response.
   * Rejects if the signal is already aborted, on queue overflow (the NEWEST
   * request is rejected so its tile errors and is re-requested later), or on
   * network failure. HTTP errors (4xx, 5xx) DO resolve successfully —
   * the caller inspects response.status for retry decisions.
   */
  fetch(src: string, signal: AbortSignal): Promise<Response> {
    return new Promise<Response>((resolve, reject) => {
      if (signal.aborted) {
        reject(new DOMException('Tile request aborted', 'AbortError'))
        return
      }

      const request: QueuedRequest = { src, signal, resolve, reject }

      // Clean up abort listener when request completes
      const onAbort = () => {
        const idx = this.queue.indexOf(request)
        if (idx >= 0) {
          this.queue.splice(idx, 1)
        }
        reject(new DOMException('Tile request aborted', 'AbortError'))
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

      // Start immediately if under limit; otherwise queue
      if (this.inFlight < this.maxConcurrent) {
        this.startRequest(request)
      } else if (this.queue.length >= this.maxQueue) {
        // Reject the newest request: its tile transitions to ERROR and
        // OpenLayers re-requests it on the next render (pan-back/toggle).
        // Dropping the oldest would strand already-loading tiles forever
        // (blank tiles with no retry path).
        request.reject(new DOMException('Tile queue overflow', 'QuotaExceededError'))
      } else {
        this.queue.push(request)
      }
    })
  }

  /** Number of currently in-flight fetches. */
  get pending(): number {
    return this.inFlight
  }

  /** Number of queued requests. */
  get queued(): number {
    return this.queue.length
  }

  /**
   * Reject all pending queued requests. In-flight requests continue
   * to completion (they are aborted via their AbortSignal by the caller).
   */
  abortAll(): void {
    for (const req of this.queue) {
      req.reject(new DOMException('Queue aborted', 'AbortError'))
    }
    this.queue.length = 0
  }

  /**
   * Full reset: abort queued requests only. In-flight fetches keep their
   * concurrency accounting — zeroing the counter would let tryDequeue()
   * overshoot maxConcurrent after unmount/projection switches.
   */
  reset(): void {
    this.abortAll()
  }

  // ── Private ─────────────────────────────────────────────────────────

  private startRequest(request: QueuedRequest): void {
    if (request.signal.aborted) {
      request.reject(new DOMException('Tile request aborted', 'AbortError'))
      this.tryDequeue()
      return
    }

    this.inFlight++

    fetch(request.src, { mode: 'cors', signal: request.signal })
      .then((response) => {
        this.inFlight--
        this.tryDequeue()
        request.resolve(response)
      })
      .catch((err) => {
        this.inFlight--
        this.tryDequeue()
        if (request.signal.aborted) {
          request.reject(new DOMException('Tile request aborted', 'AbortError'))
        } else {
          request.reject(err)
        }
      })
  }

  private tryDequeue(): void {
    while (this.queue.length > 0 && this.inFlight < this.maxConcurrent) {
      const next = this.queue.shift()!
      if (next.signal.aborted) {
        next.reject(new DOMException('Tile request aborted', 'AbortError'))
        continue
      }
      this.startRequest(next)
    }
  }
}
