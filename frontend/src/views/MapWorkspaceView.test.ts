/**
 * MapWorkspaceView 关键行为回归防护(源码断言)。
 *
 * 该视图 2400+ 行且强依赖真实 OpenLayers 容器与后端接口,本项目没有组件级
 * 挂载测试的先例(见 RoutePlannerPanel.test.ts 说明),因此这里以源码断言锁定
 * 三类「改回去就会重新变 bug」的约束:
 * 1. 测量与识别/气象的双向互斥(原实现只剩航路一侧,残余测量 Draw 会静默吃掉
 *    所有点击);
 * 2. 投影切换必须同步测量(原实现只重建 AIS 与航路,测量几何留在旧投影);
 * 3. 悬停坐标提示复用 pointermove 且经 requestAnimationFrame 合帧。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// jsdom 环境下 import.meta.url 为 http 协议,无法用于 fs;vitest cwd 即项目根目录
const source = readFileSync(join(process.cwd(), 'src/views/MapWorkspaceView.vue'), 'utf-8')

function functionBody(name: string): string {
  return source.match(new RegExp(`function ${name}\\([\\s\\S]*?\\n\\}`))?.[0] ?? ''
}

describe('测量与其余地图交互的互斥', () => {
  it('singleclick 必须用响应式的 measureMode 判定测量态(而非模块级 let)', () => {
    expect(source).toContain("if (routesStore.interactionMode !== 'idle' || measureMode.value !== 'none') return")
  })

  it('开启要素识别 / 气象查询时必须结束测量 Draw,否则点击被静默吞掉', () => {
    expect(functionBody('toggleQueryMode')).toContain('stopMeasureInteraction()')
    expect(functionBody('toggleWeatherMode')).toContain('stopMeasureInteraction()')
  })

  it('开始测量时必须关闭要素识别与气象,并关掉航路浮窗', () => {
    const body = functionBody('activateMeasure')
    expect(body).toContain('queryMode.value = false')
    expect(body).toContain('weatherMode.value = false')
    expect(body).toContain('closeRouteFlyout()')
  })

  it('测量按钮必须能显示激活态', () => {
    expect(source).toContain(":class=\"{ active: measureMode === 'LineString' }\"")
    expect(source).toContain(":class=\"{ active: measureMode === 'Polygon' }\"")
  })
})

describe('测量在投影切换时的生命周期', () => {
  it('switchProjection 必须同步测量(与 AIS / 航路同范式)', () => {
    const body = functionBody('switchProjection')
    expect(body).toContain('syncMeasureForProjection()')
    expect(body).toContain('reloadAisGeometry()')
    expect(body).toContain('routeDrawing.reloadRouteGeometry()')
  })

  it('绘制中切换投影:结束 Draw 并提示重新测量,不把旧 CRS 几何当新 CRS', () => {
    const body = functionBody('syncMeasureForProjection')
    expect(body).toContain('stopMeasureInteraction()')
    expect(body).toContain('请重新测量')
  })

  it('结果文本一律由 WGS84 真值生成,不从当前投影几何重算', () => {
    const body = functionBody('setMeasureDraft')
    // 文本来自真值 → 投影无关
    expect(body).toContain('formatMeasureResult(draft)')
    // 不再直接对「当前投影几何」调用 ol/sphere(这正是原实现的错值来源)
    expect(source).not.toContain('getLength(')
    expect(source).not.toContain('getArea(')
  })

  it('绘制结束时把投影几何转成 WGS84 真值再计算', () => {
    expect(functionBody('activateMeasure')).toContain('measureGeometryToDraft(')
  })

  it('drawend 回调里不得清空 measureSource(ol 是在 drawend 之后才把要素加入 source 的)', () => {
    const drawEndHandler =
      source.match(/measureInteraction\.on\('drawend'[\s\S]*?map\.addInteraction\(measureInteraction\)/)?.[0] ?? ''
    expect(drawEndHandler).not.toBe('')
    expect(drawEndHandler).not.toContain('measureSource.clear()')
    expect(drawEndHandler).toContain('measureGeometryToDraft(')
    // 重建只发生在投影切换路径上
    expect(functionBody('rebuildMeasureGeometry')).toContain('measureSource.clear()')
    expect(functionBody('syncMeasureForProjection')).toContain('rebuildMeasureGeometry()')
  })
})

describe('地图内坐标提示', () => {
  it('复用 pointermove 监听并经 requestAnimationFrame 合帧', () => {
    expect(source).toContain("map.on('pointermove'")
    expect(source).toContain('requestAnimationFrame(flushHover)')
    expect(source).toContain('cancelAnimationFrame(hoverRaf)')
  })

  it('门槛用 getPointResolution 的地面分辨率,不用 zoom 数字', () => {
    const body = functionBody('groundResolutionMeters')
    expect(body).toContain('getPointResolution')
    expect(source).toContain('HOVER_MIN_GROUND_RESOLUTION_METERS')
  })

  it('坐标文本必须标注经纬度顺序与方位字母', () => {
    expect(source).toContain('formatLonLat(')
  })

  it('拖动期间 / 指针离开地图 / 卸载时必须隐藏并清理', () => {
    expect(source).toContain('event.dragging')
    expect(source).toContain("addEventListener('pointerleave', hideHover)")
    expect(source).toContain("removeEventListener('pointerleave', hideHover)")
  })

  it('提示不写 Store、不创建航点', () => {
    const body = functionBody('flushHover')
    expect(body).not.toContain('routesStore')
    expect(body).not.toContain('addRoutePoint')
  })
})

describe('航路选中与浮窗', () => {
  it('选线仍走 pickRouteAtPixel(不新增 Select interaction)', () => {
    expect(source).toContain('pickRouteAtPixel')
    expect(source).not.toContain('new Select(')
  })

  it('点击空白只关浮窗,不改动选中航路', () => {
    expect(source).toContain('closeRouteFlyout()')
    expect(source).not.toContain('setActiveRoute(null)')
  })

  it('航路点选不再依赖面板可见:singleclick 始终尝试命中(随时可点选)', () => {
    expect(source).not.toContain('isSelectionEnabled')
    const handler = source.match(/map\.on\('singleclick'[\s\S]*?\n  \}\)/)?.[0] ?? ''
    expect(handler).not.toBe('')
    expect(handler).toContain('pickRouteAtPixel')
    expect(handler).not.toContain('routePanelVisible')
  })

  it('折叠/关闭航路面板不再强制关闭浮窗(仅重算锚点让位)', () => {
    const body = functionBody('syncRouteFlyout')
    expect(body).not.toBe('')
    expect(body).not.toContain('routePanelVisible')
    expect(body).toContain('updateRouteFlyoutPixel()')
  })

  it('可发现性提示:有可见航路即提示,不再以面板打开为条件', () => {
    const line = source.split('\n').find((item) => item.includes('route-select-hint')) ?? ''
    expect(line).not.toBe('')
    expect(line).toContain('点击地图上的航路可查看详情')
    expect(line).not.toContain('routePanelVisible')
    expect(line).toContain('routesStore.routes.some')
    // 工具栏 tooltip 同步说明「随时可点选」
    expect(source).toContain('地图上随时可点选航路查看详情')
  })

  it('定位让位 padding 随面板折叠状态动态注入(折叠后利用全屏)', () => {
    expect(source).toContain('getFitPadding')
  })

  it('浮层容器不吞地图指针事件', () => {
    expect(source).toContain('class="map-overlay-root"')
  })
})

/**
 * 冰情叠加集成(会话 #26):
 * 冰情是独立环境叠加层 —— 复用地图、复用唯一 pointermove、随投影切换同步,
 * 但绝不进入 S-57 的批量加载/卸载与渲染调度路径。
 */
describe('冰情叠加集成', () => {
  it('switchProjection 同步冰情(与 AIS / 航路 / 测量同范式)', () => {
    const body = functionBody('switchProjection')
    expect(body).toContain('iceOverlay.reloadForProjection()')
  })

  it('冰情 hover 复用唯一 pointermove 分发,冰情浮窗显示期间抑制坐标提示', () => {
    const handler = source.match(/map\.on\('pointermove'[\s\S]*?\n  \}\)/)?.[0] ?? ''
    expect(handler).not.toBe('')
    expect(handler).toContain('iceOverlay.handlePointerMove(')
    expect(functionBody('flushHover')).toContain('iceOverlay.hover.value')
    // 仍然只有一处 pointermove 注册
    expect((source.match(/map\.on\('pointermove'/g) ?? []).length).toBe(1)
  })

  it('指针离开地图与卸载时彻底清理冰情 hover / 图层', () => {
    expect(source).toContain("addEventListener('pointerleave', iceOverlay.clearHover)")
    expect(source).toContain("removeEventListener('pointerleave', iceOverlay.clearHover)")
    const unmount = source.match(/onBeforeUnmount\(\(\) => \{[\s\S]*?\n\}\)/)?.[0] ?? ''
    expect(unmount).toContain('iceOverlay.dispose()')
  })

  it('环境叠加菜单含冰情入口;时间轴挂载且让位随面板状态', () => {
    expect(source).toContain('command="ice"')
    expect(source).toContain('<IceTimeline')
    expect(source).toContain('iceTimelineLeft')
    expect(source).toContain('iceTimelineRight')
  })

  it('冰情不进入 S-57 批量加载/卸载路径(独立环境叠加层)', () => {
    for (const name of [
      'unloadAllChartLayers',
      'unloadSelectedDatasets',
      'unloadCurrentFilteredLayers',
      'unloadLastBulkBatch',
    ]) {
      expect(functionBody(name)).not.toContain('iceOverlay')
    }
  })

  it('冰情瓦片接入共享请求队列与 LRU 瓦片缓存(选项注入)', () => {
    const block = source.match(/useIceOverlay\(\{[\s\S]*?\n\}\)/)?.[0] ?? ''
    expect(block).not.toBe('')
    expect(block).toContain('tileCache')
    expect(block).toContain('tileRequestQueue')
  })
})
