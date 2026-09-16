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

// jsdom 环境下 import.meta.url 为 http 协议,无法用于 fs;vitest cwd 即项目根目录
const source = readFileSync(join(process.cwd(), 'src/components/RoutePlannerPanel.vue'), 'utf-8')

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
