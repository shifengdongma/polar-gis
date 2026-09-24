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

  it('航路面板关闭时仍不可选线,但界面必须说明该条件(可发现性)', () => {
    expect(source).toContain('isSelectionEnabled: () => routePanelVisible.value')
    expect(source).toContain('点击地图上的航路可查看详情')
    expect(source).toContain('可在地图上点选航路查看详情')
  })

  it('浮层容器不吞地图指针事件', () => {
    expect(source).toContain('class="map-overlay-root"')
  })
})
