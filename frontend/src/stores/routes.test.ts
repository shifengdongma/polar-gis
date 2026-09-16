import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { RouteDraft, RoutePoint } from '../types'
import { parseStoredRoutes, routeStorageKey, serializeRoutes, useRoutesStore } from './routes'

function makePoints(coords: [number, number][]): RoutePoint[] {
  return coords.map(([lon, lat], index) => ({ id: `p-${index}`, seq: index + 1, lon, lat }))
}

describe('routes store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('创建 / 删除航路,默认名按最小未占用序号递增', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const first = store.createRoute()!
    const second = store.createRoute()!
    expect(first.name).toBe('航路 1')
    expect(second.name).toBe('航路 2')
    expect(store.routes).toHaveLength(2)
    expect(store.activeRouteId).toBe(second.id)
    store.deleteRoute(first.id)
    expect(store.routes).toHaveLength(1)
    expect(store.routes[0]!.id).toBe(second.id)
  })

  it('删除 activeRoute 后清空 activeRouteId', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const route = store.createRouteFromPoints(undefined, makePoints([[120, 72], [122, 73]]))!
    expect(store.activeRouteId).toBe(route.id)
    store.deleteRoute(route.id)
    expect(store.activeRouteId).toBeNull()
  })

  it('createRouteFromPoints 校验点数量与坐标,非法输入不写入', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    expect(store.createRouteFromPoints(undefined, makePoints([[120, 72]]))).toBeNull()
    expect(store.createRouteFromPoints(undefined, makePoints([[999, 72], [122, 73]]))).toBeNull()
    expect(store.routes).toHaveLength(0)
  })

  it('航路点 CRUD:修改 / 增加 / 删除', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const route = store.createRouteFromPoints('A', makePoints([[120, 72], [122, 73], [125, 74]]))!
    // 修改
    const target = route.points[1]!
    expect(store.updateRoutePoint(route.id, target.id, 127, 73.5).ok).toBe(true)
    expect(route.points[1]).toMatchObject({ lon: 127, lat: 73.5 })
    // 非法修改拒绝且不改写
    expect(store.updateRoutePoint(route.id, target.id, 181, 73.5).ok).toBe(false)
    expect(route.points[1]).toMatchObject({ lon: 127, lat: 73.5 })
    // 增加
    const added = store.addRoutePoint(route.id)
    expect(added.ok).toBe(true)
    expect(route.points).toHaveLength(4)
    expect(route.points[3]!.seq).toBe(4)
    // 删除
    expect(store.removeRoutePoint(route.id, route.points[3]!.id).ok).toBe(true)
    expect(route.points).toHaveLength(3)
    expect(route.points.map((p) => p.seq)).toEqual([1, 2, 3])
  })

  it('只剩 2 个点时禁止删除航路点', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const route = store.createRouteFromPoints(undefined, makePoints([[120, 72], [122, 73]]))!
    const result = store.removeRoutePoint(route.id, route.points[0]!.id)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toBe('航路至少需要两个航路点')
    expect(route.points).toHaveLength(2)
  })

  it('replaceRoutePoints 按索引复用旧 id,保持点位身份稳定', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const route = store.createRouteFromPoints(undefined, makePoints([[120, 72], [122, 73], [125, 74]]))!
    const oldIds = route.points.map((p) => p.id)
    store.replaceRoutePoints(route.id, makePoints([[130, 70], [132, 71]]))
    expect(route.points).toHaveLength(2)
    expect(route.points.map((p) => p.id)).toEqual(oldIds.slice(0, 2))
  })

  it('显隐切换与 visibleRouteIds / 全部显示 / 全部隐藏', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const a = store.createRouteFromPoints('A', makePoints([[120, 72], [122, 73]]))!
    const b = store.createRouteFromPoints('B', makePoints([[125, 74], [127, 75]]))!
    expect(store.visibleRouteIds).toEqual([a.id, b.id])
    store.toggleRouteVisibility(b.id)
    expect(b.visible).toBe(false)
    expect(store.visibleRouteIds).toEqual([a.id])
    store.hideAllRoutes()
    expect(store.visibleRouteIds).toEqual([])
    store.showAllRoutes()
    expect(store.visibleRouteIds).toEqual([a.id, b.id])
  })

  it('setActiveRoute 切换选中,非法 id 忽略', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const route = store.createRouteFromPoints(undefined, makePoints([[120, 72], [122, 73]]))!
    store.setActiveRoute(null)
    expect(store.activeRouteId).toBeNull()
    store.setActiveRoute(route.id)
    expect(store.activeRouteId).toBe(route.id)
    store.setActiveRoute('no-such-id')
    expect(store.activeRouteId).toBe(route.id)
  })

  it('每次数据变更 revision 递增(地图同步信号)', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const base = store.revision
    const route = store.createRouteFromPoints(undefined, makePoints([[120, 72], [122, 73]]))!
    expect(store.revision).toBeGreaterThan(base)
    const before = store.revision
    store.updateRoutePoint(route.id, route.points[0]!.id, 121, 72)
    expect(store.revision).toBeGreaterThan(before)
  })

  it('持久化后可恢复:名称 / 点位 / 显隐', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const route = store.createRouteFromPoints('北极航线', makePoints([[120, 72], [122, 73]]))!
    store.toggleRouteVisibility(route.id)

    const restored = useRoutesStore()
    restored.ensureLoaded('proj-1')
    expect(restored.routes).toHaveLength(1)
    expect(restored.routes[0]).toMatchObject({
      name: '北极航线',
      visible: false,
      projectId: 'proj-1',
    })
    expect(restored.routes[0]!.points).toHaveLength(2)
    expect(restored.routes[0]!.points[0]).toMatchObject({ lon: 120, lat: 72 })
  })

  it('不同 projectId 的草稿相互隔离', () => {
    const storeA = useRoutesStore()
    storeA.ensureLoaded('proj-A')
    storeA.createRouteFromPoints('A 航线', makePoints([[120, 72], [122, 73]]))
    const storeB = useRoutesStore()
    storeB.ensureLoaded('proj-B')
    storeB.createRouteFromPoints('B 航线', makePoints([[125, 74], [127, 75]]))
    // 重新加载各自项目,互不可见
    storeA.ensureLoaded('proj-A')
    expect(storeA.routes.map((r) => r.name)).toEqual(['A 航线'])
    storeB.ensureLoaded('proj-B')
    expect(storeB.routes.map((r) => r.name)).toEqual(['B 航线'])
    // 同一个 key 中只保存一个项目的数据
    expect(localStorage.getItem(routeStorageKey('proj-A'))).toContain('A 航线')
    expect(localStorage.getItem(routeStorageKey('proj-B'))).not.toContain('A 航线')
  })

  it('切换 projectId 时重置并加载新项目数据', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-A')
    store.createRouteFromPoints('A 航线', makePoints([[120, 72], [122, 73]]))
    store.ensureLoaded('proj-B')
    expect(store.routes).toHaveLength(0)
    expect(store.activeRouteId).toBeNull()
    expect(store.interactionMode).toBe('idle')
  })

  it('少于 2 点的草稿不写入 localStorage,但保留在内存中', () => {
    const store = useRoutesStore()
    store.ensureLoaded('proj-1')
    const route = store.createRoute()! // 0 点草稿
    expect(store.routes).toHaveLength(1)
    expect(route.points).toHaveLength(0)
    const raw = localStorage.getItem(routeStorageKey('proj-1'))
    expect(raw).toBe('{"version":1,"projectId":"proj-1","routes":[]}')
    // 补足 2 点后落盘
    store.replaceRoutePoints(route.id, makePoints([[120, 72], [122, 73]]))
    expect(localStorage.getItem(routeStorageKey('proj-1'))).toContain(route.id)
  })
})

describe('parseStoredRoutes 容错', () => {
  const projectId = 'proj-1'
  const valid = {
    version: 1,
    routes: [
      { id: 'r1', name: '航路 1', points: [{ id: 'p1', seq: 1, lon: 120, lat: 72 }, { id: 'p2', seq: 2, lon: 122, lat: 73 }], visible: true },
    ],
  }

  it('损坏 JSON → 空数组,不抛异常', () => {
    expect(parseStoredRoutes('{broken json', projectId)).toEqual([])
  })

  it('null / 空字符串 → 空数组', () => {
    expect(parseStoredRoutes(null, projectId)).toEqual([])
    expect(parseStoredRoutes('', projectId)).toEqual([])
  })

  it('解析 { version, routes } 包装结构', () => {
    const routes = parseStoredRoutes(JSON.stringify(valid), projectId)
    expect(routes).toHaveLength(1)
    expect(routes[0]).toMatchObject({ id: 'r1', name: '航路 1', projectId })
  })

  it('兼容裸数组外形(旧版本结构)', () => {
    const routes = parseStoredRoutes(JSON.stringify(valid.routes), projectId)
    expect(routes).toHaveLength(1)
    expect(routes[0]!.id).toBe('r1')
  })

  it('routes 非数组 / points 非数组 → 忽略', () => {
    expect(parseStoredRoutes(JSON.stringify({ version: 1, routes: 'x' }), projectId)).toEqual([])
    expect(parseStoredRoutes(JSON.stringify([{ id: 'r1', points: 'x' }]), projectId)).toEqual([])
  })

  it('非法经纬度点被丢弃,剩余不足 2 点整条丢弃', () => {
    const raw = JSON.stringify({
      routes: [
        { id: 'r1', points: [{ lon: 999, lat: 72 }, { lon: 122, lat: 73 }] }, // 1 合法点 → 丢弃
        { id: 'r2', points: [{ lon: 120, lat: 72 }, { lon: 999, lat: 0 }, { lon: 122, lat: 73 }] }, // 2 合法点 → 保留
      ],
    })
    const routes = parseStoredRoutes(raw, projectId)
    expect(routes).toHaveLength(1)
    expect(routes[0]!.id).toBe('r2')
    expect(routes[0]!.points).toHaveLength(2)
    expect(routes[0]!.points.map((p) => p.seq)).toEqual([1, 2])
  })

  it('字段缺失补默认值:name / visible / 时间 / id', () => {
    const raw = JSON.stringify([{ points: [{ lon: 120, lat: 72 }, { lon: 122, lat: 73 }] }])
    const routes = parseStoredRoutes(raw, projectId)
    expect(routes).toHaveLength(1)
    expect(routes[0]!.id).toBeTruthy()
    expect(routes[0]!.name).toBe('航路 1')
    expect(routes[0]!.visible).toBe(true)
    expect(routes[0]!.createdAt).toBeTruthy()
  })

  it('重复 id 去重(保留首个)', () => {
    const dup = { id: 'r1', points: [{ lon: 120, lat: 72 }, { lon: 122, lat: 73 }] }
    const routes = parseStoredRoutes(JSON.stringify([dup, dup]), projectId)
    expect(routes).toHaveLength(1)
  })

  it('serializeRoutes 输出可被 parseStoredRoutes 还原', () => {
    const draft: RouteDraft = {
      id: 'r9',
      projectId,
      name: '往返',
      points: makePoints([[120, 72], [122, 73]]),
      visible: false,
      createdAt: '2026-09-16T00:00:00Z',
      updatedAt: '2026-09-16T00:00:00Z',
    }
    const restored = parseStoredRoutes(serializeRoutes(projectId, [draft]), projectId)
    expect(restored).toHaveLength(1)
    expect(restored[0]).toMatchObject({ id: 'r9', name: '往返', visible: false })
  })
})
