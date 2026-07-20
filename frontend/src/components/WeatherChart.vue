<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

interface WeatherPoint {
  forecastAt: string
  temperatureC: number
  windSpeedMs: number
  windDirectionDeg: number
  waveHeightM: number
}

const props = defineProps<{ items: WeatherPoint[] }>()
const chartTarget = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function renderChart() {
  if (!chartTarget.value) return
  chart ??= echarts.init(chartTarget.value)
  chart.setOption({
    color: ['#35c3d6', '#168aad', '#e89b27'],
    tooltip: { trigger: 'axis' },
    legend: { data: ['温度 °C', '风速 m/s', '浪高 m'] },
    grid: { left: 42, right: 24, top: 42, bottom: 46 },
    xAxis: {
      type: 'category',
      data: props.items.map((item) => new Date(item.forecastAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit' })),
      axisLabel: { rotate: 35 },
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#e8eef2' } } },
    series: [
      { name: '温度 °C', type: 'line', smooth: true, data: props.items.map((item) => item.temperatureC) },
      { name: '风速 m/s', type: 'line', smooth: true, data: props.items.map((item) => item.windSpeedMs) },
      { name: '浪高 m', type: 'line', smooth: true, data: props.items.map((item) => item.waveHeightM) },
    ],
  })
}

onMounted(renderChart)
watch(() => props.items, renderChart, { deep: true })
onBeforeUnmount(() => chart?.dispose())
</script>

<template>
  <div ref="chartTarget" class="weather-chart"></div>
</template>

