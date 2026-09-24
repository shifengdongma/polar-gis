/**
 * RoutePlannerPanel 关键交互属性回归防护(会话 #22 根因)。
 *
 * el-drawer 的 :modal="false" 只去掉遮罩,抽屉的 overlay 仍是一个 position:fixed
 * 全屏 div,会拦截整个视口的指针事件(地图平移/缩放/自由绘制/拖拽编辑全部失效)。
 * Element Plus 官方机制:同时设置 modal-penetrable → overlay 获得 is-penetrable
 * 类(pointer-events:none),仅抽屉面板本身保留交互。
 *
 * 组件级测试环境(真实 DOM + 浏览器指针事件)在本项目无先例,这里以源码断言
 * 守护该关键属性组合,防止重构时被移除。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ROUTE_END_COLOR, ROUTE_START_COLOR } from '../utils/mapRoute'

// jsdom 环境下 import.meta.url 为 http 协议,无法用于 fs;vitest cwd 即项目根目录
const source = readFileSync(join(process.cwd(), 'src/components/RoutePlannerPanel.vue'), 'utf-8')
const styles = readFileSync(join(process.cwd(), 'src/styles.css'), 'utf-8')

describe('RoutePlannerPanel 交互关键属性', () => {
  it('el-drawer 必须同时设置 :modal="false" 与 modal-penetrable', () => {
    const drawerTag = source.match(/<el-drawer[\s\S]*?>/)?.[0] ?? ''
    expect(drawerTag).toContain(':modal="false"')
    expect(drawerTag).toContain('modal-penetrable')
  })

  it('经纬度列必须标注真实合法范围(经度 ±180 / 纬度 ±90)', () => {
    expect(source).toContain('经度(-180~180)')
    expect(source).toContain('纬度(-90~90)')
  })
})

/**
 * 航路方向标记:途经点先后顺序即航路方向 —— 首点起点、末点终点。
 * 地图侧标记由 mapRoute.ts 守护,此处守护面板必须把方向信息呈现给用户。
 */
describe('RoutePlannerPanel 航路方向标注', () => {
  it('点表必须有「说明」列展示方向角色', () => {
    expect(source).toContain('label="说明"')
    expect(source).toContain('routePointRoleLabel')
  })

  it('点表必须说明顺序即航路方向', () => {
    expect(source).toContain('按途经点先后顺序')
  })

  it('面板必须给出起点 / 终点图例', () => {
    expect(source).toContain('起点')
    expect(source).toContain('终点')
    expect(source).toContain('route-start-dot')
    expect(source).toContain('route-end-dot')
  })

  it('图例与点表角色标记的颜色必须与地图标记一致(不允许两套色)', () => {
    expect(styles).toContain(`.route-start-dot { background: ${ROUTE_START_COLOR}; }`)
    expect(styles).toContain(`.route-end-dot { background: ${ROUTE_END_COLOR}; }`)
    expect(styles).toContain(`.route-role-tag.is-start`)
    expect(styles).toContain(`.route-role-tag.is-end`)
    expect(styles).toContain(`.route-role-tag.is-via`)
  })
})

/**
 * 航段信息(任务 C1)与单位说明(任务 C3):
 * 航段必须与地图浮窗同源(mapRoute.routeSegments),起点没有入站航段要显示占位符,
 * 单位与方位口径必须写在界面上,不能只在代码里正确。
 */
describe('RoutePlannerPanel 航段与单位说明', () => {
  it('点表必须有「入站航段」与「累计」两列,且数据来自 routeSegments', () => {
    expect(source).toContain('label="入站航段"')
    expect(source).toContain('label="累计"')
    expect(source).toContain('routeSegments')
    expect(source).toContain('inboundLegText')
    expect(source).toContain('cumulativeDistanceText')
  })

  it('起点没有入站航段,必须显示占位符', () => {
    expect(source).toContain(": '—'")
  })

  it('方位角必须写明是「初始真方位」,不得暗示磁方位或整段恒定航向', () => {
    expect(source).toContain('初始真方位')
    expect(source).toContain('非磁方位')
    expect(source).not.toContain('磁方位角')
  })

  it('必须给出坐标系、经纬度顺序、km/NM 与 1 NM = 1852 m 的说明', () => {
    expect(source).toContain('WGS84')
    expect(source).toContain('经度, 纬度')
    expect(source).toContain('1 NM = 1852 m')
    expect(source).toContain('不作为实际导航依据')
  })

  it('点表可定位航路点,且定位路径只调用 locateRoutePoint(不改数据、不入编辑态、不触发测量)', () => {
    expect(source).toContain('@row-click="handleLocatePoint"')
    // 精确断言 locatePoint 函数体:定位不得写数据、不得进入绘制/编辑、不得触发测量
    const locateBody = source.match(/function locatePoint\([\s\S]*?\n\}/)?.[0] ?? ''
    expect(locateBody).toContain('locateRoutePoint')
    for (const forbidden of [
      'replaceRoutePoints',
      'updateRoutePoint',
      'addRoutePoint',
      'removeRoutePoint',
      'deleteRoute',
      'startRouteModify',
      'startRouteDraw',
      'setInteractionMode',
      'fitRoute',
    ]) {
      expect(locateBody).not.toContain(forbidden)
    }
  })

  it('抽屉宽度与 fitRoute 右侧让位保持配套(520px 抽屉)', () => {
    expect(source).toContain('size="520px"')
  })
})
