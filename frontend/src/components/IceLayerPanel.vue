<script setup lang="ts">
/**
 * 冰情信息面板(左侧图层面板内的环境叠加区块)。
 *
 * - 只读驱动 useIceOverlay 的动作,不直接触碰 OpenLayers;
 * - 厚度缺失(本数据集常态)必须显示「当前日期无厚度变量」并禁用开关,
 *   绝不生成假数据、绝不把缺失当 0;
 * - 图例色值来自 mapIce 的 iceLegendGradient(与后端 PALETTE_STOPS 同源),
 *   组件内不写第二套颜色;
 * - class 统一 ice- 前缀。
 */
import { computed } from 'vue'
import type { IceOverlayApi } from '../composables/useIceOverlay'
import { formatIceDate, iceLegendGradient } from '../utils/mapIce'

const props = defineProps<{ ice: IceOverlayApi }>()

const concentrationVisible = computed(() => props.ice.concentrationVisible.value)
const thicknessVisible = computed(() => props.ice.thicknessVisible.value)
const concentrationOpacity = computed(() => props.ice.concentrationOpacity.value)
const thicknessOpacity = computed(() => props.ice.thicknessOpacity.value)
const concentrationAvailable = computed(() => props.ice.concentrationAvailable.value)
const thicknessAvailable = computed(() => props.ice.thicknessAvailable.value)
const selectedDate = computed(() => props.ice.selectedDate.value)
const error = computed(() => props.ice.error.value)
const empty = computed(
  () => !props.ice.info.value && !error.value || (props.ice.info.value?.dates.length ?? 0) === 0,
)
const debugAlignment = computed(() => props.ice.debugAlignment.value)

const concentrationGradient = iceLegendGradient('concentration')
const thicknessGradient = iceLegendGradient('thickness')
const concentrationTicks = ['0', '10', '20', '30', '40', '50', '60', '70', '80', '90', '100']
const thicknessTicks = ['0', '0.5', '1.5', '3', '5+']

function onToggleConcentration(value: string | number | boolean) {
  props.ice.toggleConcentration(value === true)
}

function onToggleThickness(value: string | number | boolean) {
  props.ice.toggleThickness(value === true)
}

function onConcentrationOpacity(value: number | number[]) {
  props.ice.setConcentrationOpacity(Array.isArray(value) ? (value[0] ?? 0) : value)
}

function onThicknessOpacity(value: number | number[]) {
  props.ice.setThicknessOpacity(Array.isArray(value) ? (value[0] ?? 0) : value)
}

function onDebugAlignment(value: string | number | boolean) {
  props.ice.setDebugAlignment(value === true)
}
</script>

<template>
  <section class="ice-panel">
    <div class="ice-panel-heading">
      <span class="ice-panel-title">冰情信息</span>
      <span class="ice-panel-badge">环境叠加</span>
    </div>

    <div v-if="error" class="ice-panel-empty">{{ error }}</div>
    <div v-else-if="empty" class="ice-panel-empty">无可用冰情数据</div>

    <template v-else>
      <div class="ice-field">
        <div class="ice-field-row">
          <el-switch
            :model-value="concentrationVisible"
            :disabled="!concentrationAvailable"
            size="small"
            @change="onToggleConcentration"
          />
          <span class="ice-field-name">海冰浓度</span>
          <span v-if="!concentrationAvailable" class="ice-field-state">当前日期无浓度数据</span>
        </div>
        <div class="ice-opacity-row">
          <span>透明度</span>
          <el-slider
            :model-value="concentrationOpacity"
            :min="0"
            :max="1"
            :step="0.05"
            :show-tooltip="false"
            :disabled="!concentrationVisible"
            size="small"
            @input="onConcentrationOpacity"
          />
          <span class="ice-opacity-value">{{ Math.round(concentrationOpacity * 100) }}%</span>
        </div>
      </div>

      <div class="ice-field">
        <div class="ice-field-row">
          <el-switch
            :model-value="thicknessVisible"
            :disabled="!thicknessAvailable"
            size="small"
            @change="onToggleThickness"
          />
          <span class="ice-field-name">海冰厚度</span>
          <span v-if="!thicknessAvailable" class="ice-field-state">当前日期无厚度变量</span>
        </div>
        <div class="ice-opacity-row">
          <span>透明度</span>
          <el-slider
            :model-value="thicknessOpacity"
            :min="0"
            :max="1"
            :step="0.05"
            :show-tooltip="false"
            :disabled="!thicknessVisible"
            size="small"
            @input="onThicknessOpacity"
          />
          <span class="ice-opacity-value">{{ Math.round(thicknessOpacity * 100) }}%</span>
        </div>
      </div>

      <div class="ice-panel-date">当前日期:{{ selectedDate ? formatIceDate(selectedDate) : '—' }}</div>

      <div class="ice-legend">
        <div class="ice-legend-title">海冰浓度（%）</div>
        <div class="ice-legend-bar" :style="{ background: concentrationGradient }"></div>
        <div class="ice-legend-ticks">
          <span v-for="tick in concentrationTicks" :key="tick">{{ tick }}</span>
        </div>
      </div>

      <div class="ice-legend" :class="{ 'is-unavailable': !thicknessAvailable }">
        <div class="ice-legend-title">海冰厚度（m）<template v-if="!thicknessAvailable"> · 当前数据不可用</template></div>
        <div class="ice-legend-bar" :style="{ background: thicknessGradient }"></div>
        <div class="ice-legend-ticks">
          <span v-for="tick in thicknessTicks" :key="tick">{{ tick }}</span>
        </div>
      </div>

      <div class="ice-panel-actions">
        <el-button size="small" text @click="ice.fitIceExtent()">定位冰区</el-button>
      </div>

      <div class="ice-panel-debug">
        <span>坐标对齐验证</span>
        <el-switch :model-value="debugAlignment" size="small" @change="onDebugAlignment" />
      </div>

      <p class="ice-panel-note">
        本平台属非认证航海显示系统;冰情数据用于环境信息展示与功能验证,数据有效性以实际导入数据来源为准,不可替代正式航海冰情资料。
      </p>
    </template>
  </section>
</template>
