# Basemap Switcher — Built-in Multi-Source Basemap

**Date**: 2026-07-28
**Status**: approved → implementing

## Problem

The current map workspace only uses OpenStreetMap tiles as the default basemap. OSM's tile server
(`tile.openstreetmap.org`) is frequently unreachable from within China, causing `ERR_CONNECTION_ABORTED`
errors and blank maps. Users have no alternative basemap source to switch to.

Secondary frontend errors (`runtime.lastError`, `message channel closed`) are caused by browser
extensions and are not addressable in application code. The `requestAnimationFrame` violation is
an OpenLayers rendering performance warning — non-critical.

## Solution

Add 4 built-in basemap sources directly in the frontend, always available without database
configuration. Merge them with any database-configured basemaps in the existing dropdown selector.
Add a colored indicator per source for quick visual identification.

## Built-in Sources

| Name | Type | Tile URL | CRS |
|------|------|----------|-----|
| OpenStreetMap | XYZ | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | EPSG:3857 |
| 高德地图 | XYZ | `https://webrd0{1-4}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}` | EPSG:3857 |
| Google Maps | XYZ | `https://mt{0-3}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}` | EPSG:3857 |
| 腾讯地图 | XYZ | `https://rt{0-3}.map.gtimg.com/tile?z={z}&x={x}&y={y}&type=vector&styleid=0` | EPSG:3857 |

## Design Decisions

1. **Frontend-only constants** — no backend changes, no database migration needed
2. **Built-in sources always appear first** in the dropdown, DB sources follow
3. **EPSG:3857 only** — built-in sources are hidden when Arctic projection (EPSG:3413) is active
4. **Silent failure** — if a built-in tile source fails to load, no error toast is shown (the tile
   simply doesn't render), and the user can switch to another source
5. **Color indicator** — each source has a small colored dot/badge in the dropdown for quick
   identification: OSM=blue, Gaode=green, Google=yellow, Tencent=blue-gray
6. **Preserves existing OSM fallback** — the hardcoded `fallbackBaseLayer` remains as the ultimate
   fallback when no basemap is selected

## Files Changed

- **NEW** `frontend/src/utils/basemaps.ts` — built-in basemap constant definitions
- **MODIFIED** `frontend/src/views/MapWorkspaceView.vue` — merge built-in basemaps, enhanced dropdown
- **MODIFIED** `frontend/src/styles.css` — basemap color indicator styles

## Acceptance Criteria

- [ ] 4 built-in basemaps appear in the dropdown alongside any DB-configured ones
- [ ] Switching basemaps works instantly without page reload
- [ ] Built-in basemaps disappear when switching to EPSG:3413 Arctic projection
- [ ] Tile load failures from one source don't prevent switching to another
- [ ] Color indicators differentiate each source in the dropdown
- [ ] Existing DB basemap functionality is preserved
