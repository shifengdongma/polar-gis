/**
 * useIceOverlay 关键契约回归防护(源码断言)。
 *
 * 组合式函数强依赖真实 OpenLayers 地图实例,本项目没有组件级挂载测试的先例
 * (见 RoutePlannerPanel.test.ts 说明),这里沿用源码断言守护冰情叠层的
 * 不可回退约束:
 * 1. attach 幂等、dispose 彻底(removeLayer + dispose + 摘监听 + abort);
 * 2. 日期/投影切换只替换 XYZ Source,绝不重建 Layer(防图层累积);
 * 3. 与 S-57 渲染体系彻底解耦(不进入 runtimeLayers/Bundle/TileRequestQueue);
 * 4. hover:debounce + AbortController + 请求代次号,旧响应绝不覆盖新位置;
 * 5. 不自行注册 map 事件(由视图唯一 pointermove 分发,避免双监听)。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// jsdom 环境下 import.meta.url 为 http 协议,无法用于 fs;vitest cwd 即项目根目录
const source = readFileSync(join(process.cwd(), 'src/composables/useIceOverlay.ts'), 'utf-8')
/** 注释里会声明「不进入 X」的约束,隔离断言只针对实际代码 */
const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')

function functionBody(name: string): string {
  return source.match(new RegExp(`function ${name}\\([\\s\\S]*?\\n  \\}`))?.[0] ?? ''
}

describe('useIceOverlay 图层生命周期', () => {
  it('attach 幂等:已附着的实例再次调用直接返回', () => {
    const body = functionBody('attach')
    expect(body).not.toBe('')
    expect(body).toContain('if (!map || attached) return')
    expect(body).toContain('attached = true')
  })

  it('只有两个冰情 TileLayer + 一个调试 VectorLayer,无其他图层创建', () => {
    expect((source.match(/new TileLayer\(/g) ?? []).length).toBe(2)
    expect((source.match(/new VectorLayer\(/g) ?? []).length).toBe(1)
  })

  it('dispose 彻底:removeLayer + dispose + 中止在飞请求 + 复位 attached', () => {
    const body = functionBody('dispose')
    expect(body).toContain('map.removeLayer(')
    expect(body).toContain('.dispose()')
    expect(body).toContain('attached = false')
    expect(functionBody('clearHover')).toContain('abort()')
  })

  it('日期/可用性/投影切换只替换 Source,绝不重建 Layer(防累积)', () => {
    const body = functionBody('refreshLayers')
    expect(body).not.toBe('')
    expect(body).toContain('setSource(')
    expect(body).not.toContain('new TileLayer(') // 只换源不建层
  })

  it('投影切换保留 selectedDate / visible / opacity 状态', () => {
    const body = functionBody('reloadForProjection')
    expect(body).not.toBe('')
    for (const forbidden of ['selectedDate.value =', 'concentrationVisible.value =', 'thicknessVisible.value =', 'concentrationOpacity.value =', 'thicknessOpacity.value =']) {
      expect(body).not.toContain(forbidden)
    }
    expect(body).toContain('refreshLayers()')
  })

  it('XYZ 源禁止淡入并允许跨域合成(截图体系依赖 canvas 合成)', () => {
    expect(source).toContain("crossOrigin: 'anonymous'")
    expect(source).toContain('transition: 0')
  })
})

describe('useIceOverlay 与 S-57 / 现有体系隔离', () => {
  it('绝不触碰 S-57 图层状态集合与渲染调度体系(仅复用通用请求管线)', () => {
    for (const forbidden of [
      'runtimeLayers',
      'selectedLayerIds',
      'attachedLayerIds',
      'activeLayerIds',
      'mapRenderScheduler',
      'disposeAllBundles',
      'attachWmsLayer',
      'reconcileRenderPlan',
    ]) {
      expect(code).not.toContain(forbidden)
    }
  })

  it('冰情瓦片复用统一请求管线:限流队列 + 共享 LRU 缓存(参照 S-57 做法)', () => {
    // 决策更新(会话 #26.1):自管 <img> 请求实测导致堆积累攒,改为接入
    // 与 S-57 相同的通用队列/缓存(限并发 + 复用 + 丢弃即中止)。
    expect(source).toContain('tileRequestQueue.fetch(')
    expect(source).toContain('tileCache.get(')
    expect(source).toContain('tileCache.set(')
  })

  it('自定义 tileLoadFunction:丢弃即中止在飞请求,可恢复错误重试', () => {
    expect(source).toContain('tileLoadFunction')
    // ol10 的"瓦片被释放"状态是 TileState.EMPTY(release()/dispose() 时置位)
    expect(source).toContain('TileState.EMPTY')
    expect(source).toContain('TILE_RETRY_MAX_ATTEMPTS')
    expect(source).toContain('tile.setState(TileState.ERROR')
  })

  it('代次中止:日期/投影/开关切换即中止上一代全部在飞瓦片请求', () => {
    expect(source).toContain('abortStaleTileLoads')
    expect(source).toContain('tileGeneration')
    expect(source).toContain('generation !== tileGeneration')
    // refreshLayers(所有源替换路径)必须先中止旧代次
    const body = functionBody('refreshLayers')
    expect(body).toContain('abortStaleTileLoads()')
  })

  it('不自行注册 map 事件(唯一 pointermove 在视图中分发)', () => {
    expect(source).not.toContain("map.on('pointermove'")
    expect(source).not.toContain("map.on('singleclick'")
  })

  it('调试对齐图层默认关闭', () => {
    expect(source).toContain('visible: false')
    expect(source).toContain('ICE_ALIGNMENT_Z_INDEX')
  })
})

describe('useIceOverlay hover 契约', () => {
  it('100ms debounce + AbortController + 请求代次号,旧响应不覆盖新位置', () => {
    expect(source).toContain('ICE_HOVER_DEBOUNCE_MS = 100')
    expect(source).toContain('AbortController')
    expect(source).toContain('hoverRequestId')
    expect(source).toContain('requestId !== hoverRequestId')
  })

  it('拖图 / 图层关闭 / 无日期 / 其他地图交互进行中 → 一律停止查询', () => {
    const body = functionBody('handlePointerMove')
    expect(body).toContain('event.dragging')
    expect(body).toContain('concentrationVisible.value')
    expect(body).toContain('selectedDate.value')
    expect(body).toContain('canQueryValue()')
    expect(body).toContain('clearHover()')
  })

  it('数据范围之外不发请求(客户端预筛)', () => {
    expect(source).toContain('pointerInIceExtent')
    expect(functionBody('handlePointerMove')).toContain('pointerInIceExtent')
  })

  it('原始值有效性用 isIceValueValid(0 是有效值)', () => {
    expect(source).toContain('isIceValueValid(')
  })
})
