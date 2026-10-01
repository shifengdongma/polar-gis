<script setup lang="ts">
/**
 * 冰情时间轴 —— "实际存在文件"的纯粹索引视图。
 *
 * - 只使用 info.dates 数组索引:步进/滑块都直接给日期,绝不按 date±1 推算;
 * - 左右让位由父视图注入(leftOffset/rightOffset,随面板折叠变化),
 *   不写死像素;UI 浮层不进入地图截图/打印。
 */
import { formatIceDate } from '../utils/mapIce'

const props = defineProps<{
  /** info.dates:实际存在的 NetCDF 文件日期(升序) */
  dates: string[]
  /** 当前日期在 dates 中的下标;异常时为 -1(钳制展示为 0) */
  currentIndex: number
  /** 左侧让位(px):随图层面板折叠状态变化 */
  leftOffset: number
  /** 右侧让位(px):随航路面板展开状态变化 */
  rightOffset: number
}>()

const emit = defineEmits<{
  (e: 'step', delta: number): void
  (e: 'select', date: string): void
}>()

function onRangeInput(event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  const date = props.dates[value]
  if (date) emit('select', date)
}
</script>

<template>
  <div
    class="ice-timeline"
    :style="{ left: leftOffset + 'px', right: rightOffset + 'px' }"
  >
    <div class="ice-timeline-date">{{ formatIceDate(dates[Math.max(0, currentIndex)] ?? '') }}</div>
    <div class="ice-timeline-controls">
      <button
        type="button"
        aria-label="上一个日期"
        :disabled="currentIndex <= 0"
        @click="emit('step', -1)"
      >‹</button>
      <input
        type="range"
        min="0"
        :max="Math.max(0, dates.length - 1)"
        step="1"
        :value="Math.max(0, currentIndex)"
        aria-label="冰情日期"
        @input="onRangeInput"
      />
      <button
        type="button"
        aria-label="下一个日期"
        :disabled="currentIndex >= dates.length - 1"
        @click="emit('step', 1)"
      >›</button>
    </div>
    <div class="ice-timeline-meta">{{ Math.max(0, currentIndex) + 1 }} / {{ dates.length }} 个可用日期</div>
  </div>
</template>
