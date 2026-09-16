<script setup lang="ts">
/**
 * 航路规划模拟面板 — 多航路管理 UI。
 *
 * 只调用 Routes Store(业务真值)与 useRouteDrawing API(地图交互),
 * 不直接操作 OpenLayers 对象。面板为非模态抽屉(:modal=false),
 * 打开时可以同时在地图上绘制 / 拖拽。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { RouteDrawingApi } from '../composables/useRouteDrawing'
import { useRoutesStore } from '../stores/routes'
import type { RoutePoint } from '../types'
import { calculateRouteLength, parseRouteCoordinateText } from '../utils/mapRoute'

const props = defineProps<{ visible: boolean; drawing: RouteDrawingApi }>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void }>()

const store = useRoutesStore()
const batchText = ref('')
const nameInput = ref('')
/** 非法坐标输入回退时强制 el-input-number 重挂载,恢复显示 Store 合法值 */
const rowVersion = ref(0)

const activeRoute = computed(() => store.activeRoute)
const interactionMode = computed(() => store.interactionMode)

const activeRouteLengthText = computed(() => {
  if (!activeRoute.value) return ''
  const meters = calculateRouteLength(activeRoute.value.points)
  return meters > 1000 ? `${(meters / 1000).toFixed(2)} km` : `${meters.toFixed(1)} m`
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
    size="440px"
    class="route-planner-drawer"
  >
    <template #header>
      <div class="route-planner-header">
        <span class="route-planner-title">航路规划模拟</span>
        <span class="route-planner-badge">演示功能</span>
      </div>
    </template>

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

        <el-table :key="rowVersion" :data="activeRoute.points" size="small" class="route-point-table" max-height="280">
          <el-table-column label="#" width="40" align="center">
            <template #default="{ $index }">{{ $index + 1 }}</template>
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
  </el-drawer>
</template>
