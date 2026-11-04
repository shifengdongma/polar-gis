/**
 * Bounded health tracking for a basemap tile source.
 *
 * Only final outcomes from the native tile loader feed this monitor (not the
 * intermediate retries), so a transient error that the loader recovers from
 * does not trigger an unnecessary source refresh.
 */
export interface BaseMapHealthOptions {
  failureThreshold?: number
  errorRatio?: number
  windowMs?: number
  cooldownMs?: number
  maxRecoveries?: number
  now?: () => number
}

interface HealthEvent {
  at: number
  ok: boolean
}

export class BaseMapHealthMonitor {
  private readonly failureThreshold: number
  private readonly errorRatioThreshold: number
  private readonly windowMs: number
  private readonly cooldownMs: number
  private readonly maxRecoveries: number
  private readonly now: () => number
  private events: HealthEvent[] = []
  private recoveries: number[] = []

  constructor(options: BaseMapHealthOptions = {}) {
    this.failureThreshold = Math.max(1, options.failureThreshold ?? 8)
    this.errorRatioThreshold = Math.min(1, Math.max(0, options.errorRatio ?? 0.6))
    this.windowMs = Math.max(1, options.windowMs ?? 15000)
    this.cooldownMs = Math.max(0, options.cooldownMs ?? 30000)
    this.maxRecoveries = Math.max(1, options.maxRecoveries ?? 3)
    this.now = options.now ?? (() => Date.now())
  }

  private prune(now: number) {
    const cutoff = now - this.windowMs
    if (this.events.length > 0 && this.events[0].at < cutoff) {
      this.events = this.events.filter((event) => event.at >= cutoff)
    }
  }

  record(ok: boolean): void {
    const now = this.now()
    this.prune(now)
    this.events.push({ at: now, ok })
  }

  private get failureCountInternal(): number {
    this.prune(this.now())
    return this.events.filter((event) => !event.ok).length
  }

  get failureCount(): number {
    return this.failureCountInternal
  }

  get errorRate(): number {
    this.prune(this.now())
    if (this.events.length === 0) return 0
    const failures = this.events.filter((event) => !event.ok).length
    return failures / this.events.length
  }

  get recoveryCount(): number {
    return this.recoveries.length
  }

  get exhausted(): boolean {
    return this.recoveries.length >= this.maxRecoveries
  }

  get hasRecentFailures(): boolean {
    return this.failureCountInternal > 0
  }

  canRecover(): boolean {
    if (this.exhausted) return false
    if (this.failureCountInternal < this.failureThreshold) return false
    if (this.errorRate < this.errorRatioThreshold) return false
    const now = this.now()
    const last = this.recoveries[this.recoveries.length - 1]
    return last === undefined || now - last >= this.cooldownMs
  }

  markRecovered(): void {
    this.recoveries.push(this.now())
  }

  /** Manual user reload resets both failure and recovery counters. */
  reset(): void {
    this.events = []
    this.recoveries = []
  }
}
