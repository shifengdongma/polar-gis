import { describe, expect, it } from 'vitest'
import { LRUTileCache } from './tileCache'

function blob(size: number, type = 'image/png'): Blob {
  return new Blob([new Uint8Array(size)], { type })
}

describe('LRUTileCache', () => {
  it('evicts the least recently used entry when the entry limit is exceeded', () => {
    const cache = new LRUTileCache(2, 1024)
    cache.set('a', blob(2))
    cache.set('b', blob(2))
    expect(cache.get('a')).toBeDefined()
    cache.set('c', blob(2))
    expect(cache.has('a')).toBe(true)
    expect(cache.has('b')).toBe(false)
    expect(cache.has('c')).toBe(true)
    expect(cache.size).toBe(2)
  })

  it('evicts by byte budget and keeps totalBytes accurate', () => {
    const cache = new LRUTileCache(10, 10)
    cache.set('a', blob(6))
    cache.set('b', blob(6))
    expect(cache.size).toBe(1)
    expect(cache.has('a')).toBe(false)
    expect(cache.has('b')).toBe(true)
    expect(cache.bytes).toBe(6)
  })

  it('deletes a poisoned entry and adjusts byte accounting', () => {
    const cache = new LRUTileCache(10, 1024)
    cache.set('bad', blob(5))
    expect(cache.bytes).toBe(5)
    expect(cache.delete('bad')).toBe(true)
    expect(cache.has('bad')).toBe(false)
    expect(cache.bytes).toBe(0)
    expect(cache.delete('bad')).toBe(false)
  })

  it('clear removes entries and resets bytes', () => {
    const cache = new LRUTileCache(10, 1024)
    cache.set('a', blob(3))
    cache.clear()
    expect(cache.size).toBe(0)
    expect(cache.bytes).toBe(0)
  })
})
