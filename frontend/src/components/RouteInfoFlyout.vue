<!--
  航线信息浮窗(地图内)。

  只读展示:本组件**不修改任何航路数据** —— 没有改名、加点、删点、拖拽入口,
  只调用传入的 drawing API 做「定位航路 / 定位航点 / 高亮航段」。
  与 RoutePlannerPanel 同契约:不直接接触 OpenLayers 对象。

  距离与方位全部来自 mapRoute 的 routeSegments / calculateRouteLength ——
  与面板同源同口径,不会出现两处数字不一致。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { RouteDrawingApi } from '../composables/useRouteDrawing'
import type { RouteDraft, RoutePointRoleRow } from '../types'
import {
  calculateRouteLength,
  formatBearing,
  formatDistance,
  routePointRole,
  routePointRoleLabel,
  routeSegments,
} from '../utils/mapRoute'

const props = defineProps<{
  route: RouteDraft
  /** 锚点像素(已夹取在地图视口内)与翻转标记 */
  pixel: { x: number; y: number; flipX: boolean; flipY: boolean }
  /** 当前选中航段(1-based);无 → null */
  segmentIndex: number | null
  drawing: RouteDrawingApi
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

/** 点表行:航路点 + 由 seq 推导的方向角色(派生数据,不入 Store) */
const pointRows = computed<RoutePointRoleRow[]>(() => {
  const points = props.route.points
  return [...points]
    .sort((a, b) => a.seq - b.seq)
    .map((point, index) => {
      const role = routePointRole(points, index)
      return { ...point, role, roleLabel: routePointRoleLabel(role) }
    })
})
const segments = computed(() => routeSegments(props.route.points))
const totalLengthText = computed(() => formatDistance(calculateRouteLength(props.route.points)))
const startPoint = computed(() => pointRows.value[0] ?? null)
const endPoint = computed(() => pointRows.value[pointRows.value.length - 1] ?? null)
const activeSegment = computed(() =>
  props.segmentIndex === null ? null : (segments.value.find((segment) => segment.index === props.segmentIndex) ?? null),
)
const selectedPointId = ref<string | null>(null)
const selectedPointIndex = computed(() => pointRows.value.findIndex((point) => point.id === selectedPointId.value))

const flyoutClass = computed(() => ({
  'route-info-flyout': true,
  'is-flip-x': props.pixel.flipX,
  'is-flip-y': props.pixel.flipY,
}))
const flyoutStyle = computed(() => ({ left: `${props.pixel.x}px`, top: `${props.pixel.y}px` }))

/** 点击航路点:定位 + 短暂高亮(不改数据、不进入绘制/编辑、不触发测量/识别) */
function handleLocatePoint(pointId: string) {
  selectedPointId.value = pointId
  props.drawing.locateRoutePoint(props.route.id, pointId)
}

function handleLocateRoute() {
  props.drawing.fitRoute(props.route.id)
}

onBeforeUnmount(() => {
  props.drawing.highlightSegment(null, null)
})
</script>

<template>
  <div :class="flyoutClass" :style="flyoutStyle">
    <div class="route-flyout-header">
      <span class="route-flyout-title" :title="route.name">{{ route.name }}</span>
      <button class="route-flyout-close" type="button" title="关闭" @click="emit('close')">×</button>
    </div>

    <div class="route-flyout-summary">
      <div class="route-flyout-row"><span class="route-flyout-label">总长度</span><span>{{ totalLengthText }}</span></div>
      <div class="route-flyout-row"><span class="route-flyout-label">航路点数</span><span>{{ pointRows.length }}</span></div>
      <div v-if="startPoint" class="route-flyout-row">
        <span class="route-flyout-label">起点</span><span>{{ startPoint.lon.toFixed(4) }}°, {{ startPoint.lat.toFixed(4) }}°</span>
      </div>
      <div v-if="endPoint" class="route-flyout-row">
        <span class="route-flyout-label">终点</span><span>{{ endPoint.lon.toFixed(4) }}°, {{ endPoint.lat.toFixed(4) }}°</span>
      </div>
    </div>

    <div v-if="activeSegment" class="route-flyout-segment">
      <div class="route-flyout-segment-title">航段 {{ activeSegment.index }}(第 {{ activeSegment.from.seq }} 点 → 第 {{ activeSegment.to.seq }} 点)</div>
      <div class="route-flyout-row"><span class="route-flyout-label">该段距离</span><span>{{ formatDistance(activeSegment.distanceMeters) }}</span></div>
      <div class="route-flyout-row"><span class="route-flyout-label">累计距离</span><span>{{ formatDistance(activeSegment.cumulativeMeters) }}</span></div>
      <div class="route-flyout-row">
        <span class="route-flyout-label">初始真方位</span><span>{{ formatBearing(activeSegment.initialBearingDeg) }}</span>
      </div>
    </div>

    <!-- 航路点列表:经度 / 纬度分列,列头写明顺序与单位范围,不以裸坐标示人 -->
    <div class="route-flyout-points">
      <div class="route-flyout-point is-head">
        <span class="route-flyout-seq">#</span>
        <span class="route-flyout-role">说明</span>
        <span>经度(°)</span>
        <span>纬度(°)</span>
      </div>
      <div
        v-for="(point, index) in pointRows"
        :key="point.id"
        class="route-flyout-point"
        :class="{ 'is-selected': index === selectedPointIndex }"
        title="点击定位该航路点"
        @click="handleLocatePoint(point.id)"
      >
        <span class="route-flyout-seq">{{ point.seq }}</span>
        <span class="route-flyout-role" :class="`is-${point.role}`">{{ point.roleLabel }}</span>
        <span>{{ point.lon.toFixed(4) }}</span>
        <span>{{ point.lat.toFixed(4) }}</span>
      </div>
    </div>

    <div class="route-flyout-actions">
      <button type="button" @click="handleLocateRoute">定位整条航路</button>
      <button type="button" :disabled="selectedPointIndex < 0" @click="selectedPointId && handleLocatePoint(selectedPointId)">定位所选航点</button>
    </div>

    <p class="route-flyout-note">
      距离为按航路点顺序计算的球面最短路径(大圆)分段之和;地图上投影后的视觉线段在极区、高纬及跨日期变更线处
      不一定与该大地线重合。方位为初始真方位角(非磁方位,也不代表整段恒定航向)。
    </p>
  </div>
</template>
