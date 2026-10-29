<script setup lang="ts">
/**
 * 航路规划模拟面板 — 多航路管理 UI。
 *
 * 只调用 Routes Store(业务真值)与 useRouteDrawing API(地图交互),
 * 不直接操作 OpenLayers 对象。面板为非模态抽屉(:modal=false),
 * 打开时可以同时在地图上绘制 / 拖拽。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { RouteDrawingApi } from '../composables/useRouteDrawing'
import { useNavigationStore } from '../stores/navigation'
import { useRoutesStore } from '../stores/routes'
import type { RouteDraft, RoutePoint, RoutePointRow } from '../types'
import IntelligentPlanningPanel from './IntelligentPlanningPanel.vue'
import {
  calculateRouteLength,
  formatBearing,
  formatDistance,
  parseRouteCoordinateText,
  routePointRole,
  routePointRoleLabel,
  routeSegments,
} from '../utils/mapRoute'
import { formatHours, formatMwh, routeMetricsStale } from '../utils/routePlanning'

const props = defineProps<{
  visible: boolean
  drawing: RouteDrawingApi
  environmentTime?: string | null
}>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void }>()

const store = useRoutesStore()
const navigation = useNavigationStore()
const planningMode = ref<'manual' | 'smart'>('manual')
const batchText = ref('')
const nameInput = ref('')
/** 非法坐标输入回退时强制 el-input-number 重挂载,恢复显示 Store 合法值 */
const rowVersion = ref(0)

const activeRoute = computed(() => store.activeRoute)
const interactionMode = computed(() => store.interactionMode)
const activePlanningSnapshot = computed(() => activeRoute.value?.planningSnapshot ?? null)
const activePlanningStale = computed(() =>
  activeRoute.value ? routeMetricsStale(activeRoute.value) : false,
)
const reevaluating = ref(false)

watch(
  () => props.visible,
  (visible) => {
    if (!visible) {
      navigation.setPickMode('idle')
      navigation.setRiskInspect(false)
    }
  },
)

function setPlanningMode(mode: 'manual' | 'smart') {
  planningMode.value = mode
  if (mode === 'manual') {
    navigation.setPickMode('idle')
    navigation.setRiskInspect(false)
  } else {
    void navigation.loadRuns()
  }
}

function handleAdopted(draft: RouteDraft) {
  planningMode.value = 'manual'
  store.setActiveRoute(draft.id)
  void nextTick(() => props.drawing.fitRoute(draft.id))
}

async function reevaluateActiveRoute() {
  if (!activeRoute.value) return
  reevaluating.value = true
  try {
    const result = await navigation.refreshAdoptedMetrics(activeRoute.value)
    if (result.traversable) ElMessage.success('已按当前规划快照重新评估')
    else ElMessage.warning(result.reason ?? '当前航线不可通行')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '航线重评失败')
  } finally {
    reevaluating.value = false
  }
}

/**
 * 点表数据:在原航路点上挂载方向角色与「入站航段」信息。
 * 途经点先后顺序即航路方向 —— 首点为起点、末点为终点(按 seq 判定,见 mapRoute)。
 * 航段信息与地图浮窗共用 mapRoute.routeSegments 同一份计算结果,不会出现两套数字。
 * 起点没有入站航段,按约定显示占位符。
 */
const pointRows = computed<RoutePointRow[]>(() => {
  const points = activeRoute.value?.points ?? []
  const sorted = [...points].sort((a, b) => a.seq - b.seq)
  const segments = routeSegments(points)
  return sorted.map((point, index) => {
    const role = routePointRole(points, index)
    const inbound = index > 0 ? segments[index - 1] : undefined
    return {
      ...point,
      role,
      roleLabel: routePointRoleLabel(role),
      // 起点没有入站航段 → 占位符;累计距离在起点是真实有效的 0,如实显示
      inboundLegText: inbound ? `${formatDistance(inbound.distanceMeters)} · 初始真方位 ${formatBearing(inbound.initialBearingDeg)}` : '—',
      cumulativeDistanceText: inbound ? formatDistance(inbound.cumulativeMeters) : formatDistance(0),
    }
  })
})

const activeRouteLengthText = computed(() => {
  if (!activeRoute.value) return ''
  return formatDistance(calculateRouteLength(activeRoute.value.points))
})

watch(
  () => store.activeRouteId,
  (id) => {
    nameInput.value = store.routes.find((route) => route.id === id)?.name ?? ''
  },
  { immediate: true },
)

async function promptRouteName(title: string, confirmText: string): Promise<string | null> {
  try {
    const { value } = await ElMessageBox.prompt('请输入航路名称', title, {
      inputValue: store.nextRouteName(),
      confirmButtonText: confirmText,
      cancelButtonText: '取消',
      inputValidator: (input: string) => (!input.trim() ? '航路名称不能为空' : true),
    })
    return value
  } catch {
    return null // 用户取消
  }
}

async function handleCreateRoute() {
  const name = await promptRouteName('新建航路', '创建')
  if (name !== null) {
    store.createRoute(name)
    ElMessage.success(`已创建航路「${store.activeRoute?.name ?? name}」,可通过地图绘制或输入坐标添加航路点`)
  }
}

async function handleDeleteRoute(routeId: string, name: string) {
  try {
    await ElMessageBox.confirm(`删除航路「${name}」？此操作不可恢复。`, '删除航路', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  if (store.interactionMode !== 'idle') store.setInteractionMode('idle')
  store.deleteRoute(routeId)
  ElMessage.success('航路已删除')
}

function commitName() {
  if (!activeRoute.value) return
  const result = store.updateRouteName(activeRoute.value.id, nameInput.value)
  if (!result.ok) {
    ElMessage.error(result.error)
    nameInput.value = activeRoute.value.name // 回退显示
  }
}

function handlePointChange(point: RoutePoint, field: 'lon' | 'lat', value: number | undefined) {
  if (!activeRoute.value) return
  const lon = field === 'lon' ? value : point.lon
  const lat = field === 'lat' ? value : point.lat
  if (lon === undefined || lat === undefined) {
    ElMessage.error('坐标必须是有效数字')
    rowVersion.value += 1 // 重挂载表格输入,回退为合法值
    return
  }
  const result = store.updateRoutePoint(activeRoute.value.id, point.id, lon, lat)
  if (!result.ok) {
    ElMessage.error(result.error)
    rowVersion.value += 1 // 重挂载表格输入,回退为合法值
  }
}

function handlePointLonChange(point: RoutePoint, value: number | undefined) {
  handlePointChange(point, 'lon', value)
}

function handlePointLatChange(point: RoutePoint, value: number | undefined) {
  handlePointChange(point, 'lat', value)
}

function handleAddPoint() {
  if (!activeRoute.value) return
  const result = store.addRoutePoint(activeRoute.value.id)
  if (!result.ok) ElMessage.error(result.error)
}

/**
 * 点表行点击 → 在地图上定位并短暂高亮该航路点。
 * 只做定位:不改航路数据、不进入绘制/编辑、不触发测量或要素识别。
 * 点中输入框 / 按钮时不定位 —— 否则编辑坐标或删除航路点时地图会乱飞。
 */
function handleLocatePoint(row: RoutePointRow, _column?: unknown, event?: Event) {
  const target = event?.target as HTMLElement | null | undefined
  if (target?.closest('input, button, .el-input, .el-button')) return
  locatePoint(row)
}

/** 「#」列按钮(el-table 的 row-click 不带下标,这里按下标取行) */
function handleLocateRow(index: number) {
  const row = pointRows.value[index]
  if (row) locatePoint(row)
}

function locatePoint(row: RoutePointRow) {
  if (!activeRoute.value) return
  // 绘制/拖拽编辑中不抢视图,避免与 Modify 拖拽互相打断
  if (interactionMode.value !== 'idle') return
  props.drawing.locateRoutePoint(activeRoute.value.id, row.id)
}

function handleRemovePoint(point: RoutePoint) {
  if (!activeRoute.value) return
  if (activeRoute.value.points.length <= 2) {
    ElMessage.warning('航路至少需要两个航路点')
    return
  }
  const result = store.removeRoutePoint(activeRoute.value.id, point.id)
  if (!result.ok) ElMessage.error(result.error)
}

async function handleStartDraw() {
  if (interactionMode.value === 'draw') return
  const active = store.activeRoute
  if (active && active.points.length >= 2) {
    try {
      await ElMessageBox.confirm('当前航路已有航路点，地图绘制将覆盖这些点位，是否继续？', '地图绘制', {
        type: 'warning',
        confirmButtonText: '继续',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    props.drawing.startRouteDraw()
    return
  }
  if (!active) {
    const name = await promptRouteName('新建航路', '创建并绘制')
    if (name === null) return
    store.createRoute(name)
  }
  props.drawing.startRouteDraw()
}

function toggleModify() {
  if (interactionMode.value === 'edit') {
    props.drawing.stopRouteModify()
  } else {
    props.drawing.startRouteModify()
  }
}

function handleApplyBatch() {
  const { points, errors } = parseRouteCoordinateText(batchText.value)
  if (errors.length > 0) {
    const shown = errors.slice(0, 3).join('；')
    ElMessage.error(shown + (errors.length > 3 ? ` 等共 ${errors.length} 处错误` : ''))
    return
  }
  if (points.length < 2) {
    ElMessage.error('批量坐标至少需要两个有效航路点')
    return
  }
  let target = store.activeRoute
  if (!target) {
    target = store.createRoute(undefined, points)
    if (!target) return
  } else {
    store.replaceRoutePoints(target.id, points)
  }
  batchText.value = ''
  ElMessage.success(`已应用 ${points.length} 个航路点`)
}
</script>

<template>
  <!-- modal-penetrable 必须与 :modal="false" 同时设置:否则抽屉的全屏 overlay
       会拦截整个视口的指针事件,导致地图平移/缩放/绘制/拖拽全部失效 -->
  <el-drawer
    :model-value="visible"
    @update:model-value="emit('update:visible', $event)"
    :modal="false"
    modal-penetrable
    :lock-scroll="false"
    direction="rtl"
    size="520px"
    class="route-planner-drawer"
  >
    <template #header>
      <div class="route-planner-header">
        <span class="route-planner-title">航路规划模拟</span>
        <span class="route-planner-badge">演示功能</span>
      </div>
    </template>

    <div class="route-mode-tabs">
      <button :class="{ active: planningMode === 'manual' }" type="button" @click="setPlanningMode('manual')">手动绘制</button>
      <button :class="{ active: planningMode === 'smart' }" type="button" @click="setPlanningMode('smart')">智能规划</button>
    </div>

    <div v-show="planningMode === 'manual'">
    <el-alert
      title="当前航路仅用于功能模拟，不作为实际导航依据。"
      type="warning"
      :closable="false"
      show-icon
      class="route-planner-alert"
    />

    <div class="route-toolbar">
      <el-button type="primary" size="small" @click="handleCreateRoute">+ 新建航路</el-button>
      <el-button size="small" :disabled="!store.routes.length" @click="store.showAllRoutes()">全部显示</el-button>
      <el-button size="small" :disabled="!store.routes.length" @click="store.hideAllRoutes()">全部隐藏</el-button>
    </div>

    <div v-if="store.routes.length" class="route-list">
      <div
        v-for="route in store.routes"
        :key="route.id"
        class="route-item"
        :class="{ 'is-active': route.id === store.activeRouteId }"
        @click="store.setActiveRoute(route.id)"
      >
        <el-checkbox
          :model-value="route.visible"
          :label="route.name"
          @change="store.toggleRouteVisibility(route.id)"
          @click.stop
        />
        <span class="route-item-meta">
          {{ route.points.length }} 个航路点
          <span v-if="route.points.length < 2" class="route-warning">(至少 2 个)</span>
        </span>
        <span class="route-item-actions" @click.stop>
          <el-button size="small" text type="primary" @click="drawing.fitRoute(route.id)">定位</el-button>
          <el-button size="small" text type="danger" @click="handleDeleteRoute(route.id, route.name)">删除</el-button>
        </span>
      </div>
    </div>
    <el-empty v-else description="暂无航路，点击「新建航路」开始" :image-size="60" />

    <template v-if="activeRoute">
      <div class="route-detail">
        <div class="route-detail-header">
          <span class="route-detail-title">当前航路</span>
          <el-input v-model="nameInput" size="small" class="route-name-input" @change="commitName" />
        </div>

        <el-table :key="rowVersion" :data="pointRows" size="small" class="route-point-table" max-height="280" @row-click="handleLocatePoint">
          <el-table-column label="#" width="58" align="center">
            <template #default="{ $index }">
              <el-button size="small" text type="primary" title="在地图上定位该航路点" @click.stop="handleLocateRow($index)">
                {{ $index + 1 }}
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="说明" width="52" align="center">
            <template #header>
              <span title="航路方向:按途经点先后顺序,首点为起点、末点为终点">说明</span>
            </template>
            <template #default="{ row }">
              <span class="route-role-tag" :class="`is-${row.role}`">{{ row.roleLabel }}</span>
            </template>
          </el-table-column>
          <el-table-column label="入站航段" min-width="150">
            <template #header>
              <span title="该点与前一个航路点之间的球面最短路径(大圆)距离,以及该段的初始真方位角(非磁方位,也不代表整段恒定航向);起点没有入站航段">入站航段</span>
            </template>
            <template #default="{ row }">
              <span class="route-leg-text">{{ row.inboundLegText }}</span>
            </template>
          </el-table-column>
          <el-table-column label="累计" min-width="104">
            <template #header>
              <span title="从起点沿航路点顺序累加至该点的距离">累计</span>
            </template>
            <template #default="{ row }">
              <span class="route-leg-text">{{ row.cumulativeDistanceText }}</span>
            </template>
          </el-table-column>
          <el-table-column label="经度(-180~180)">
            <template #default="{ row }">
              <el-input-number
                :model-value="row.lon"
                :precision="6"
                :controls="false"
                size="small"
                @change="handlePointLonChange(row, $event)"
              />
            </template>
          </el-table-column>
          <el-table-column label="纬度(-90~90)">
            <template #default="{ row }">
              <el-input-number
                :model-value="row.lat"
                :precision="6"
                :controls="false"
                size="small"
                @change="handlePointLatChange(row, $event)"
              />
            </template>
          </el-table-column>
          <el-table-column width="40" align="center">
            <template #default="{ row }">
              <el-button
                size="small"
                text
                type="danger"
                :disabled="activeRoute.points.length <= 2"
                title="删除航路点"
                @click="handleRemovePoint(row)"
              >×</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" :disabled="interactionMode === 'draw'" @click="handleAddPoint">+ 添加航路点</el-button>

        <div class="route-actions">
          <template v-if="interactionMode === 'draw'">
            <el-button size="small" @click="drawing.removeLastRoutePoint()">撤销点</el-button>
            <el-button size="small" type="warning" @click="drawing.cancelRouteDraw()">取消绘制</el-button>
          </template>
          <template v-else>
            <el-button size="small" type="primary" :disabled="interactionMode === 'edit'" @click="handleStartDraw">
              地图绘制
            </el-button>
            <el-button size="small" :type="interactionMode === 'edit' ? 'warning' : 'default'" @click="toggleModify">
              {{ interactionMode === 'edit' ? '结束编辑' : '拖拽编辑' }}
            </el-button>
            <el-button size="small" :disabled="activeRoute.points.length < 2" @click="drawing.fitRoute(activeRoute.id)">
              定位航路
            </el-button>
          </template>
        </div>
        <div v-if="activeRoute.points.length >= 2" class="route-length">航路长度：{{ activeRouteLengthText }}</div>
        <div v-else class="route-length route-warning">航路至少需要两个航路点</div>

        <div v-if="activePlanningSnapshot" class="route-planning-metrics">
          <el-alert
            v-if="activePlanningStale"
            title="当前航线已修改，风险和能耗结果需要重新计算"
            type="warning"
            :closable="false"
            show-icon
          />
          <template v-else>
            <div class="route-planning-metrics-title">规划快照（只读）</div>
            <div class="route-planning-metrics-grid">
              <span>风险 {{ activePlanningSnapshot.risk.toFixed(3) }}</span>
              <span>能耗 {{ formatMwh(activePlanningSnapshot.energyMWh) }}</span>
              <span>航时 {{ formatHours(activePlanningSnapshot.timeHours) }}</span>
              <span>距离 {{ activePlanningSnapshot.distanceKm.toFixed(0) }} km</span>
            </div>
            <div class="route-planning-snapshot-time">快照：{{ activePlanningSnapshot.snapshotTime }}</div>
          </template>
          <el-button size="small" type="primary" plain :loading="reevaluating" @click="reevaluateActiveRoute">
            按当前航线重新评估
          </el-button>
        </div>

        <div class="route-direction-legend">
          <span class="route-direction-item">
            <i class="route-direction-dot route-start-dot" />起点（第 1 个航路点）
          </span>
          <span class="route-direction-item">
            <i class="route-direction-dot route-end-dot" />终点（最后 1 个航路点）
          </span>
          <span class="route-direction-note">航路方向：按途经点先后顺序，由起点驶向终点</span>
        </div>
        <p class="route-units-note">
          坐标：WGS84 经纬度（经度, 纬度）· 距离：km / NM（1 NM = 1852 m）· 方位：初始真方位角（非磁方位）
          · 距离为按航路点顺序的球面最短路径（大圆）分段之和，为近似地表距离。
          <strong>模拟航路，仅供展示与交互验证，不作为实际导航依据。</strong>
        </p>
      </div>
    </template>
    <el-empty v-else description="请先选择或新建一条航路" :image-size="60" />

    <div class="route-batch">
      <div class="route-batch-title">批量坐标输入（每行一个点：经度,纬度）</div>
      <el-input
        v-model="batchText"
        type="textarea"
        :rows="5"
        placeholder="120.123456,72.123456&#10;121.332211,72.553321&#10;123.553211,73.021133"
      />
      <el-button size="small" type="primary" class="route-batch-apply" @click="handleApplyBatch">应用坐标</el-button>
    </div>
    </div>

    <IntelligentPlanningPanel
      v-if="planningMode === 'smart'"
      :environment-time="environmentTime"
      @adopted="handleAdopted"
    />
  </el-drawer>
</template>
