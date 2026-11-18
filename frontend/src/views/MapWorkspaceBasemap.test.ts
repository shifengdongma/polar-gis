/**
 * Basemap stability contracts (source-level, matching this repo's existing
 * view-test convention). The runtime WMTS/health/loader logic is covered by
 * utils/basemapLayers.test.ts, utils/basemapHealth.test.ts and
 * utils/tileLoader.test.ts.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(join(process.cwd(), 'src/views/MapWorkspaceView.vue'), 'utf-8')

describe('basemap tile recovery', () => {
  it('uses the bounded native retry loader and loader-final health callbacks', () => {
    expect(source).toContain('createNativeRetryTileLoadFunction')
    expect(source).toContain('onFailure: (caught) => recordBaseMapHealth')
    expect(source).toContain('onSuccess: () => recordBaseMapHealth')
    expect(source).toContain('scheduleBaseMapRecovery')
    expect(source).toContain('getSource()?.refresh()')
  })

  it('selects the WMTS matrix set by CRS and retries capabilities instead of taking Layer[0]', () => {
    expect(source).toContain('fetchWmtsCapabilitiesWithRetry')
    expect(source).toContain('selectWmtsLayerAndMatrix')
    expect(source).toContain('normalizeCapabilitiesCrs')
    expect(source).not.toContain('capabilities.Contents?.Layer?.[0]')
    expect(source).not.toContain('TileMatrixSetLink?.[0]?.TileMatrixSet')
  })

  it('uses direct GWC GetTile templates and never blocks map build on capabilities', () => {
    expect(source).toContain('isDirectTileTemplate')
    expect(source).toContain('createGwcTileGrid')
    expect(source).toContain('void loadConfiguredBaseLayers()')
    expect(source).not.toContain('...(await createConfiguredBaseLayers())')
  })

  it('offers a manual reload and surfaces configuration failures', () => {
    expect(source).toContain('reloadActiveBaseMap')
    expect(source).toContain('retryBaseMapConfigs')
    expect(source).toContain('baseMapConfigErrors')
    expect(source).toContain('当前投影暂无可用配置底图')
  })

  it('remembers a basemap per CRS and never forces 3857 fallback in 3413', () => {
    expect(source).toContain('activeBaseMapByCrs')
    expect(source).toContain('resolveActiveBaseMapId')
    expect(source).toContain("currentCrs.value === 'EPSG:3857'")
  })

  it('does not let the overview auto-toggle override a user-selected basemap', () => {
    expect(source).toContain("activeBaseMapId.value === overview.id")
    expect(source).toContain('layer.setVisible(false)')
  })
})

describe('map long-run cleanup', () => {
  it('cleans bundles, map event keys, timers and basemap lifecycles on unmount', () => {
    expect(source).toContain('disposeAllBundles(map)')
    expect(source).toContain('unByKey(key')
    expect(source).toContain('window.clearTimeout(reconcileTimer)')
    expect(source).toContain('window.clearTimeout(evictTimer)')
    expect(source).toContain('window.clearTimeout(layerSearchTimer)')
    expect(source).toContain('deactivateTileLoadLifecycle')
    expect(source).toContain('__polarMapTileQueueStats')
  })
})
