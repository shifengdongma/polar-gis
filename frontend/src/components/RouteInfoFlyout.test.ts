/**
 * 航线信息浮窗关键属性回归防护。
 *
 * 组件级测试环境(真实 DOM + 指针事件)在本项目无先例,这里沿用既有先例:
 * 读取 .vue 源码与 styles.css 做源码断言,守护三类不可回退的约束 ——
 * 1. 浮窗是**只读**的:不得出现任何航路写接口(改名/加点/删点/删除航路);
 * 2. 方位角必须写明「初始真方位」,不得暗示磁方位或整段恒定航向;
 * 3. 指针事件边界:容器不吞地图事件,浮窗面板本身可交互,坐标提示不拦事件。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ROUTE_END_COLOR, ROUTE_START_COLOR, ROUTE_VIA_COLOR } from '../utils/mapRoute'

// jsdom 环境下 import.meta.url 为 http 协议,无法用于 fs;vitest cwd 即项目根目录
const source = readFileSync(join(process.cwd(), 'src/components/RouteInfoFlyout.vue'), 'utf-8')
const styles = readFileSync(join(process.cwd(), 'src/styles.css'), 'utf-8')

describe('RouteInfoFlyout 展示内容', () => {
  it('必须展示航路名、总长度(km 与 NM)、航路点数、起点与终点', () => {
    expect(source).toContain('route-flyout-title')
    expect(source).toContain('总长度')
    expect(source).toContain('航路点数')
    expect(source).toContain('起点')
    expect(source).toContain('终点')
    expect(source).toContain('formatDistance')
  })

  it('航点列表必须按 seq 排序并分列标注经度 / 纬度', () => {
    expect(source).toContain('sort((a, b) => a.seq - b.seq)')
    expect(source).toContain('经度(°)')
    expect(source).toContain('纬度(°)')
  })

  it('选中航段时展示段序号、起终航点、段距离、累计距离与初始真方位', () => {
    expect(source).toContain('该段距离')
    expect(source).toContain('累计距离')
    expect(source).toContain('初始真方位')
    expect(source).toContain('activeSegment.from.seq')
    expect(source).toContain('activeSegment.to.seq')
  })

  it('声明距离含义,且不再显示模拟/安全提示', () => {
    expect(source).toContain('大圆')
    expect(source).not.toContain('不作为实际导航依据')
    expect(source).not.toContain('仅供展示与交互验证')
  })

  it('提供关闭 / 定位整条航路 / 定位所选航点操作', () => {
    expect(source).toContain('定位整条航路')
    expect(source).toContain('定位所选航点')
    expect(source).toContain("emit('close')")
    expect(source).toContain('fitRoute')
    expect(source).toContain('locateRoutePoint')
  })
})

describe('RouteInfoFlyout 只读约束', () => {
  it('不得调用任何航路写接口(浮窗不能改写航路数据)', () => {
    for (const forbidden of [
      'replaceRoutePoints',
      'updateRoutePoint',
      'addRoutePoint',
      'removeRoutePoint',
      'updateRouteName',
      'createRoute',
      'deleteRoute',
      'toggleRouteVisibility',
    ]) {
      expect(source).not.toContain(forbidden)
    }
  })

  it('不得进入绘制 / 编辑模式', () => {
    expect(source).not.toContain('setInteractionMode')
    expect(source).not.toContain('startRouteDraw')
    expect(source).not.toContain('startRouteModify')
  })
})

describe('浮层指针事件与配色', () => {
  it('浮层容器与坐标提示不得吞掉地图指针事件,浮窗面板本身可交互', () => {
    expect(styles).toContain('.map-overlay-root { position: absolute; inset: 0; z-index: 30; pointer-events: none; }')
    expect(styles).toMatch(/\.map-hover-coord\s*\{[^}]*pointer-events: none/)
    expect(styles).toMatch(/\.route-info-flyout\s*\{[^}]*pointer-events: auto/)
  })

  it('浮窗方向色必须与地图标记色一致(不允许两套色)', () => {
    expect(styles).toContain(`.route-flyout-role.is-start { color: ${ROUTE_START_COLOR}; }`)
    expect(styles).toContain(`.route-flyout-role.is-end { color: ${ROUTE_END_COLOR}; }`)
    expect(styles).toContain(`.route-flyout-role.is-via { color: ${ROUTE_VIA_COLOR}; }`)
  })

  it('浮层不得进入打印 / 截图输出', () => {
    expect(styles).toContain('.map-overlay-root { display: none !important; }')
  })
})
