<script setup lang="ts">
import { computed } from 'vue'
import type { EnvironmentTooltipState } from '../composables/useEnvironmentOverlays'
import { environmentValueText } from '../utils/mapEnvironment'

const props = defineProps<{ tooltip: EnvironmentTooltipState }>()

const labels: Record<string, string> = {
  bathymetry: '水深',
  ice: '海冰',
  wind: '风场',
  current: '海流',
  wave: '海浪',
}
const qualityLabels: Record<string, string> = {
  real: '真实数据',
  synthetic: '合成数据',
  missing: '缺失',
  unknown: '未知',
}
const label = computed(() => labels[props.tooltip.field] ?? props.tooltip.field)
const observation = computed(() => props.tooltip.observation)
const valueText = computed(() =>
  observation.value ? environmentValueText({
    id: 'hover',
    longitude: props.tooltip.longitude,
    latitude: props.tooltip.latitude,
    field: observation.value.field,
    available: observation.value.available,
    values: observation.value.values,
    units: observation.value.units,
    quality: observation.value.quality,
    source: observation.value.source,
    matchedTime: observation.value.time.matchedTime,
    reason: observation.value.reason,
  }) : '—',
)
const matchedText = computed(() => {
  const matched = observation.value?.time.matchedTime
  return matched ? new Date(matched).toISOString().replace('.000Z', 'Z') : '静态/未知'
})
</script>

<template>
  <div
    class="environment-value-tooltip glass-panel"
    :class="{ 'is-flip-x': tooltip.flipX, 'is-flip-y': tooltip.flipY }"
    :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }"
  >
    <div class="environment-tooltip-title">
      <strong>{{ label }}</strong>
      <span :class="['quality-badge', `quality-${observation?.quality ?? 'missing'}`]">
        {{ qualityLabels[observation?.quality ?? 'missing'] }}
      </span>
    </div>
    <div class="environment-tooltip-value">{{ valueText }}</div>
    <div class="environment-tooltip-meta">
      <span>来源：{{ observation?.source ?? '—' }}</span>
      <span>匹配时间：{{ matchedText }}</span>
      <span v-if="observation?.reason">原因：{{ observation.reason }}</span>
    </div>
    <div class="environment-tooltip-coord">
      {{ tooltip.latitude.toFixed(4) }}°, {{ tooltip.longitude.toFixed(4) }}°
    </div>
  </div>
</template>
