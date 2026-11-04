import { describe, expect, it } from 'vitest'
import { BaseMapHealthMonitor } from './basemapHealth'

describe('BaseMapHealthMonitor', () => {
  it('does not request recovery below the failure threshold', () => {
    const health = new BaseMapHealthMonitor({ failureThreshold: 3, now: () => 1000 })
    health.record(false)
    health.record(false)
    expect(health.canRecover()).toBe(false)
    health.record(false)
    expect(health.canRecover()).toBe(true)
  })

  it('requires a high error ratio, not just a few errors among successes', () => {
    const health = new BaseMapHealthMonitor({ failureThreshold: 3, errorRatio: 0.6, now: () => 1000 })
    health.record(false)
    health.record(false)
    for (let i = 0; i < 10; i += 1) health.record(true)
    expect(health.errorRate).toBeLessThan(0.6)
    expect(health.canRecover()).toBe(false)
  })

  it('honours cooldown and a maximum recovery budget, then stops automatically', () => {
    let now = 1000
    const health = new BaseMapHealthMonitor({
      failureThreshold: 1,
      errorRatio: 0.1,
      cooldownMs: 1000,
      maxRecoveries: 2,
      now: () => now,
    })
    health.record(false)
    expect(health.canRecover()).toBe(true)
    health.markRecovered()
    health.record(false)
    expect(health.canRecover()).toBe(false)
    now += 1000
    expect(health.canRecover()).toBe(true)
    health.markRecovered()
    health.record(false)
    now += 5000
    expect(health.canRecover()).toBe(false)
    expect(health.exhausted).toBe(true)
  })

  it('clears failures after a success window and supports manual reset', () => {
    const health = new BaseMapHealthMonitor({ failureThreshold: 2, errorRatio: 0.5, now: () => 1000 })
    health.record(false)
    health.record(false)
    expect(health.canRecover()).toBe(true)
    health.reset()
    expect(health.canRecover()).toBe(false)
    expect(health.exhausted).toBe(false)
  })

  it('prunes events outside the rolling window', () => {
    let now = 1000
    const health = new BaseMapHealthMonitor({ windowMs: 1000, failureThreshold: 1, now: () => now })
    health.record(false)
    now += 2000
    expect(health.failureCount).toBe(0)
    expect(health.canRecover()).toBe(false)
  })
})
