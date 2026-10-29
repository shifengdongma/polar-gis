<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { useNavigationStore } from '../stores/navigation'
import type { PlanningRoute } from '../types/navigation'
import { formatHours, formatMwh } from '../utils/routePlanning'

const emit = defineEmits<{
  (event: 'adopt', route: PlanningRoute): void
}>()

const navigation = useNavigationStore()
const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

const routes = computed(() => navigation.routes)
const selectedId = computed(() => navigation.selectedRouteId)

function statusQuality(route: PlanningRoute): string {
  if (route.sourceQuality === 'real') return '真实'
  if (route.sourceQuality === 'synthetic') return '合成'
  if (route.sourceQuality === 'unknown') return '未知'
  return route.sourceQuality
}

function renderChart() {
  if (!chartEl.value) return
  chart ??= echarts.init(chartEl.value)
  const points = routes.value.map((route) => ({
    value: [route.energyMWh, route.riskScore],
    routeId: route.routeId,
    label: route.label,
    timeHours: route.timeHours,
    selected: route.routeId === selectedId.value,
    recommended: route.recommended,
  }))
  chart.setOption(
    {
      animationDuration: 220,
      grid: { left: 44, right: 12, top: 18, bottom: 34 },
      xAxis: {
        type: 'value',
        name: '能耗 MWh',
        nameTextStyle: { color: '#7897a3', fontSize: 9 },
        axisLabel: { color: '#7897a3', fontSize: 9 },
        splitLine: { lineStyle: { color: 'rgba(178,211,220,.1)' } },
      },
      yAxis: {
        type: 'value',
        name: '风险',
        min: 0,
        nameTextStyle: { color: '#7897a3', fontSize: 9 },
        axisLabel: { color: '#7897a3', fontSize: 9 },
        splitLine: { lineStyle: { color: 'rgba(178,211,220,.1)' } },
      },
      tooltip: {
        trigger: 'item',
        formatter: (params: any) => {
          const item = params.data
          return `${item.label}<br/>能耗 ${Number(item.value[0]).toFixed(2)} MWh<br/>风险 ${Number(item.value[1]).toFixed(3)}<br/>航时 ${Number(item.timeHours).toFixed(2)} h`
        },
      },
      series: [
        {
          type: 'scatter',
          symbolSize: (_value: number[], params: any) =>
            params.data?.selected ? 15 : params.data?.recommended ? 12 : 9,
          data: points,
          itemStyle: {
            color: (params: any) =>
              params.data?.selected
                ? '#ffd166'
                : params.data?.recommended
                  ? '#35c3d6'
                  : '#8fb8c9',
            borderColor: '#07111d',
            borderWidth: 1,
          },
          emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2 } },
        },
      ],
    },
    true,
  )
}

function handleChartClick(params: any) {
  const routeId = params?.data?.routeId
  if (typeof routeId === 'string') navigation.selectRoute(routeId)
}

function selectRoute(route: PlanningRoute) {
  navigation.selectRoute(route.routeId)
}

watch(routes, () => nextTick(renderChart), { deep: true })
watch(selectedId, () => nextTick(renderChart))

onMounted(() => {
  nextTick(() => {
    renderChart()
    chart?.on('click', handleChartClick)
    if (chartEl.value) {
      observer = new ResizeObserver(() => chart?.resize())
      observer.observe(chartEl.value)
    }
  })
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="route-comparison-panel">
    <div class="route-comparison-heading">
      <div>
        <span class="eyebrow">PARETO</span>
        <h3>候选航线对比</h3>
      </div>
      <el-tag size="small" type="info">{{ routes.length }} 条候选</el-tag>
    </div>

    <el-alert
      v-if="navigation.isSynthetic"
      title="含合成环境数据：仅用于研究验证，不可作为真实航行依据"
      type="warning"
      :closable="false"
      show-icon
    />

    <el-table
      v-if="routes.length"
      :data="routes"
      size="small"
      max-height="250"
      highlight-current-row
      @row-click="selectRoute"
    >
      <el-table-column label="航线" min-width="90">
        <template #default="{ row }">
          <span :class="{ 'route-comparison-recommended': row.recommended }">{{ row.label }}</span>
        </template>
      </el-table-column>
      <el-table-column label="风险" width="66" align="right">
        <template #default="{ row }">{{ row.riskScore.toFixed(3) }}</template>
      </el-table-column>
      <el-table-column label="能耗" width="92" align="right">
        <template #default="{ row }">{{ formatMwh(row.energyMWh) }}</template>
      </el-table-column>
      <el-table-column label="航时" width="74" align="right">
        <template #default="{ row }">{{ formatHours(row.timeHours) }}</template>
      </el-table-column>
      <el-table-column label="距离" width="78" align="right">
        <template #default="{ row }">{{ row.distanceKm.toFixed(0) }} km</template>
      </el-table-column>
      <el-table-column label="质量" width="56">
        <template #default="{ row }">{{ statusQuality(row) }}</template>
      </el-table-column>
      <el-table-column label="" width="72">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click.stop="emit('adopt', row)">采纳</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="尚无候选航线" :image-size="40" />

    <div ref="chartEl" class="route-comparison-chart" />
    <p class="route-comparison-note">
      Pareto 图只绘制算法实际返回的候选解；Distance 仅作统计，不参与 NSGA-III 目标。
    </p>
  </section>
</template>
