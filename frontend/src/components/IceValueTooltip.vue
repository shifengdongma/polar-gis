<script setup lang="ts">
/**
 * 冰情值浮窗(只读)—— 展示后端原始网格值。
 *
 * 数值来自 /ice/value 的原始网格查询,**绝不从 PNG 颜色反推**;
 * 0 是有效值,原样显示(不做真值判断)。定位与既有 .map-hover-coord
 * 同模式:像素锚定 + 边缘翻转;pointer-events:none 不吞地图事件,
 * 位于 .map-overlay-root(打印/截图自动排除)。
 */
import { computed } from 'vue'
import type { IceHoverState } from '../composables/useIceOverlay'
import { ICE_FIELD_LABELS, formatIceDate } from '../utils/mapIce'
import type { IceFieldId } from '../types'

const props = defineProps<{ hover: IceHoverState }>()

const tooltipClass = computed(() => ({
  'ice-value-tooltip': true,
  'is-flip-x': props.hover.flipX,
  'is-flip-y': props.hover.flipY,
}))
const tooltipStyle = computed(() => ({ left: `${props.hover.x}px`, top: `${props.hover.y}px` }))

const fieldLabel = computed(() => ICE_FIELD_LABELS[props.hover.field as IceFieldId] ?? '冰情')

/** 0 是有效值;整数不带小数,非整数保留 1 位 */
const valueText = computed(() => {
  const value = props.hover.value
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return props.hover.units === '%' ? `${text}%` : `${text} ${props.hover.units}`
})

function formatLonLat(value: number): string {
  return Number.isFinite(value) ? value.toFixed(4) : '—'
}
</script>

<template>
  <div :class="tooltipClass" :style="tooltipStyle">
    <div class="ice-tooltip-title">{{ fieldLabel }}：{{ valueText }}</div>
    <div class="ice-tooltip-row">{{ formatIceDate(hover.date) }}</div>
    <div class="ice-tooltip-row">经度 {{ formatLonLat(hover.longitude) }}°</div>
    <div class="ice-tooltip-row">纬度 {{ formatLonLat(hover.latitude) }}°</div>
  </div>
</template>
