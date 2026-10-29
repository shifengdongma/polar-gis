<script setup lang="ts">
import { computed } from 'vue'
import type { EnvironmentOverlaysApi } from '../composables/useEnvironmentOverlays'
import type { EnvironmentField } from '../types/navigation'
import EnvironmentTimeControl from './EnvironmentTimeControl.vue'

const props = defineProps<{ env: EnvironmentOverlaysApi }>()

const fields: { id: EnvironmentField; label: string; hint: string }[] = [
  { id: 'bathymetry', label: '水深（GEBCO）', hint: '分级色带 · 透明陆地' },
  { id: 'wind', label: '风场（CARRA2）', hint: '箭头指向去向 · 风速着色' },
  { id: 'current', label: '海流（TOPAZ5）', hint: '箭头指向流向 · 流速着色' },
  { id: 'wave', label: '海浪（WAM）', hint: '箭头指向去向 · 浪高着色' },
]

const qualityLabels: Record<string, string> = {
  real: '真实',
  synthetic: '合成',
  missing: '缺失',
  unknown: '未知',
}

const hasSynthetic = computed(() =>
  fields.some((field) => props.env.layers[field.id].quality === 'synthetic'),
)

function qualityLabel(field: EnvironmentField) {
  const quality = props.env.layers[field].quality
  return quality ? qualityLabels[quality] ?? quality : '未知'
}

function matchedLabel(field: EnvironmentField) {
  const matched = props.env.layers[field].matchedTime
  return matched ? new Date(matched).toISOString().replace('.000Z', 'Z') : '动态/未知'
}

function onPolicyChange(value: string | number | boolean) {
  props.env.setDisplayPolicy(value ? 'allow_synthetic_research' : 'real_only')
}

function onVisibleChange(field: EnvironmentField, value: string | number | boolean) {
  props.env.setVisible(field, Boolean(value))
}

function onOpacityChange(field: EnvironmentField, value: number | number[]) {
  props.env.setOpacity(field, Array.isArray(value) ? value[0] : value)
}
</script>

<template>
  <section class="environment-layer-panel">
    <div class="environment-panel-heading">
      <div>
        <span class="eyebrow">ENVIRONMENT</span>
        <h3>环境图层</h3>
      </div>
      <el-tag v-if="hasSynthetic" size="small" type="warning">含合成数据</el-tag>
    </div>

    <EnvironmentTimeControl
      :model-value="env.requestedTime.value"
      @update:model-value="env.setTime"
      @refresh="env.refreshAll"
    />

    <div class="environment-policy-row">
      <span>研究数据</span>
      <el-switch
        :model-value="env.displayPolicy.value === 'allow_synthetic_research'"
        size="small"
        @change="onPolicyChange"
      />
      <small>合成数据仅用于研究验证，不可作为真实航行依据</small>
    </div>

    <el-alert
      v-if="env.sourcesError.value"
      :title="env.sourcesError.value"
      type="warning"
      :closable="false"
      show-icon
      class="environment-source-error"
    />

    <div v-for="field in fields" :key="field.id" class="environment-layer-row">
      <div class="environment-layer-main">
        <el-switch
          :model-value="env.layers[field.id].visible"
          size="small"
          @change="(value: boolean | string | number) => onVisibleChange(field.id, value)"
        />
        <div class="environment-layer-title">
          <strong>{{ field.label }}</strong>
          <small>{{ field.hint }}</small>
        </div>
        <span :class="['quality-badge', `quality-${env.layers[field.id].quality ?? 'missing'}`]">
          {{ qualityLabel(field.id) }}
        </span>
      </div>
      <div v-if="env.layers[field.id].visible" class="environment-layer-detail">
        <el-slider
          :model-value="env.layers[field.id].opacity"
          :min="0.1"
          :max="1"
          :step="0.05"
          size="small"
          @update:model-value="(value: number | number[]) => onOpacityChange(field.id, value)"
        />
        <div class="environment-layer-meta">
          <span>{{ env.layers[field.id].source ?? '来源未知' }}</span>
          <span>{{ matchedLabel(field.id) }}</span>
          <span v-if="env.layers[field.id].loading">加载中…</span>
          <span v-if="env.layers[field.id].error" class="environment-layer-error">{{ env.layers[field.id].error }}</span>
        </div>
      </div>
    </div>

    <div class="environment-layer-note">
      海冰由底部冰情时间轴独立控制；风险栅格需先完成规划或区域风险评估。
    </div>
  </section>
</template>
