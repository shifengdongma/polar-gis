/**
 * LRU (Least Recently Used) cache for WMS tile blob responses.
 *
 * Tiles at a given URL (which encodes layer, zoom, BBOX, CRS, etc.) are
 * immutable — caching them eliminates redundant fetch() calls when:
 *   - The map pans back to a previously viewed area
 *   - Layers are toggled on/off
 *   - Multiple TileWMS sources request overlapping tile URLs
 *
 * Uses JavaScript Map insertion-order semantics for O(1) get/set/evict.
 */

export class LRUTileCache {
  private cache = new Map<string, Blob>()
  private maxEntries: number
  private maxBytes: number
  private totalBytes = 0

  constructor(maxEntries = 2048, maxBytes = 50 * 1024 * 1024) {
    this.maxEntries = maxEntries
    this.maxBytes = maxBytes
  }

  /**
   * Retrieve a cached tile blob. Returns undefined on miss.
   * On hit, promotes the entry to "most recently used" position.
   */
  get(url: string): Blob | undefined {
    const entry = this.cache.get(url)
    if (!entry) return undefined
    // Promote to most-recently-used: delete + re-insert
    this.cache.delete(url)
    this.cache.set(url, entry)
    return entry
  }

  /**
   * Store a tile blob. On overflow, evicts the least recently used entries.
   */
  set(url: string, blob: Blob): void {
    // If key already exists, remove it first so re-insertion moves it to end
    if (this.cache.has(url)) {
      this.totalBytes -= this.cache.get(url)!.size
      this.cache.delete(url)
    }

    this.cache.set(url, blob)
    this.totalBytes += blob.size

    // Evict LRU entries if over the entry limit
    while (this.cache.size > this.maxEntries) {
      this.evictOldest()
    }

    // Evict LRU entries if over the byte limit
    while (this.totalBytes > this.maxBytes && this.cache.size > 0) {
      this.evictOldest()
    }
  }

  /** Remove all cached entries. */
  clear(): void {
    this.cache.clear()
    this.totalBytes = 0
  }

  /** Number of cached entries. */
  get size(): number {
    return this.cache.size
  }

  /** Approximate memory usage in bytes. */
  get bytes(): number {
    return this.totalBytes
  }

  /** Whether the cache contains a given URL. */
  has(url: string): boolean {
    return this.cache.has(url)
  }

  /**
   * Evict the least recently used entry (first inserted key in the Map).
   */
  private evictOldest(): void {
    const oldestKey = this.cache.keys().next().value as string | undefined
    if (oldestKey !== undefined) {
      const blob = this.cache.get(oldestKey)
      if (blob) {
        this.totalBytes -= blob.size
      }
      this.cache.delete(oldestKey)
    }
  }
}
