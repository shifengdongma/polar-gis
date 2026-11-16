import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(join(process.cwd(), 'src/views/MapWorkspaceView.vue'), 'utf-8')

describe('S-57 waterway integration', () => {
  it('mounts a dedicated panel and menu entry without a second map/listener', () => {
    expect(source).toContain('S57WaterwayPanel')
    expect(source).toContain('useS57Waterways')
    expect(source).toContain('航道专题')
    expect((source.match(/new OlMap\(/g) ?? []).length).toBe(1)
    expect((source.match(/map\.on\('singleclick'/g) ?? []).length).toBe(1)
    expect((source.match(/map\.on\('pointermove'/g) ?? []).length).toBe(1)
  })

  it('picks waterway features inside the existing singleclick handler without an extra mode', () => {
    const clickBlock = source.slice(
      source.indexOf("map.on('singleclick'"),
      source.indexOf("map.on('moveend'"),
    )
    expect(clickBlock).not.toContain('selectionMode.value')
    expect(clickBlock).toContain('s57Waterways.pickAtPixel(event.pixel)')
    expect(clickBlock).toContain('waterwayPanelOpen.value')
    expect(clickBlock).toContain('!layerPanelCollapsed.value')
    // Explicit weather/identify modes and higher-z route overlays keep priority.
    expect(clickBlock.indexOf('weatherMode.value')).toBeLessThan(
      clickBlock.indexOf('s57Waterways.pickAtPixel'),
    )
    expect(clickBlock.indexOf('routeDrawing.pickRouteAtPixel')).toBeLessThan(
      clickBlock.indexOf('s57Waterways.pickAtPixel'),
    )
    expect(clickBlock.indexOf('planningRouteLayer.pickRouteAtPixel')).toBeLessThan(
      clickBlock.indexOf('s57Waterways.pickAtPixel'),
    )
  })

  it('reserves space for side panels so the waterway footer is not clipped', () => {
    expect(source).toContain(
      "'has-side-panel': waterwayPanelOpen || icePanelOpen || environmentPanelOpen",
    )
  })

  it('keeps the thematic overlay out of S-57 runtime/bundle/route state', () => {
    expect(source).toContain('s57Waterways.attach()')
    expect(source).toContain('s57Waterways.reloadForProjection()')
    expect(source).toContain('s57Waterways.dispose()')
    expect(source).toContain('s57ThematicPreview.dispose()')
    expect(source).not.toContain('runtimeLayers.value.add(s57Waterways')
    expect(source).not.toContain('routesStore.addWaterway')
  })
})
