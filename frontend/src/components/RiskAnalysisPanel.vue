<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useNavigationStore } from '../stores/navigation'
import type { DataPolicy, RiskField } from '../types/navigation'

const navigation = useNavigationStore()
const field = ref<RiskField>('combined')
const bboxWest = ref(120)
const bboxSouth = ref(74)
const bboxEast = ref(130)
const bboxNorth = ref(78)
const departure = ref(new Date().toISOString().slice(0, 19))
const dataPolicy = ref<DataPolicy>('real_only')
const starting = ref(false)

const riskGrid = computed(() => navigation.riskGrid)
const cell = computed(() => navigation.riskCell)
const fieldOptions: { value: RiskField; label: string }[] = [
  { value: 'combined', label: '综合风险' },
  { value: 'ice', label: '海冰风险' },
  { value: 'depth', label: '水深风险' },
  { value: 'fog', label: '雾风险' },
  { value: 'wind', label: '风风险' },
  { value: 'wave', label: '浪风险' },
]
const qualityLabels: Record<string, string> = {
  real: '真实',
  synthetic: '合成',
  missing: '缺失',
  unknown: '未知',
}

function riskText(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : '未知'
}

async function loadGrid() {
  await navigation.loadRiskGrid(field.value)
}

onMounted(() => {
  // Opening the risk tab after a completed plan should not leave the map
  // empty until the user clicks again.
  if (navigation.currentRun?.status === 'completed' && !navigation.riskGrid) {
    void loadGrid()
  }
})

async function evaluateArea() {
  if (!navigation.projectId) {
    ElMessage.error('项目尚未加载')
    return
  }
  starting.value = true
  try {
    await navigation.startRiskEvaluation({
      projectId: navigation.projectId,
      bbox: [bboxWest.value, bboxSouth.value, bboxEast.value, bboxNorth.value],
      departureTime: departure.value.endsWith('Z') ? departure.value : `${departure.value}Z`,
      vesselId: navigation.vesselId,
      dataPolicy: dataPolicy.value,
    })
    ElMessage.success('区域风险评估任务已提交')
  } catch {
    // navigation.error carries the message
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <section class="risk-analysis-panel">
    <div class="risk-panel-heading">
      <div>
        <span class="eyebrow">RISK</span>
        <h3>风险评估</h3>
      </div>
      <el-tag v-if="navigation.currentRun" size="small" type="info">{{ navigation.currentRun.riskModelVersion }}</el-tag>
    </div>

    <div class="risk-field-row">
      <el-select v-model="field" size="small">
        <el-option v-for="option in fieldOptions" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
      <el-button size="small" type="primary" :disabled="!navigation.currentRun" @click="loadGrid">加载风险格</el-button>
      <el-button
        size="small"
        :disabled="!navigation.riskGrid"
        :type="navigation.riskInspect ? 'warning' : 'default'"
        @click="navigation.setRiskInspect(!navigation.riskInspect)"
      >
        {{ navigation.riskInspect ? '结束地图点选' : '地图点选风险格' }}
      </el-button>
    </div>

    <el-alert
      v-if="navigation.currentRun?.status === 'failed' && navigation.currentRun?.errorCode === 'NO_FEASIBLE_ROUTE'"
      title="没有可行航线，但仍可查看风险栅格"
      type="info"
      :closable="false"
      show-icon
    />

    <div v-if="riskGrid" class="risk-grid-summary">
      返回 {{ riskGrid.returnedCells }} / {{ riskGrid.totalCells }} 个 25km 风险格
      <span v-if="riskGrid.snapshotTime"> · 快照 {{ riskGrid.snapshotTime }}</span>
    </div>
    <el-empty v-else description="点击“加载风险格”或在地图上点击风险单元" :image-size="36" />

    <div v-if="cell" class="risk-cell-detail">
      <div class="risk-cell-title">{{ cell.cellId }} · {{ cell.center.latitude.toFixed(3) }}, {{ cell.center.longitude.toFixed(3) }}</div>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="综合风险">{{ riskText(cell.risk.combined) }}</el-descriptions-item>
        <el-descriptions-item label="通航">{{ cell.traversable ? '可通行' : (cell.blockedReason ?? '不可通行') }}</el-descriptions-item>
        <el-descriptions-item label="海冰">{{ riskText(cell.risk.ice) }}</el-descriptions-item>
        <el-descriptions-item label="水深">{{ riskText(cell.risk.depth) }}</el-descriptions-item>
        <el-descriptions-item label="雾">{{ riskText(cell.risk.fog) }}</el-descriptions-item>
        <el-descriptions-item label="风">{{ riskText(cell.risk.wind) }}</el-descriptions-item>
        <el-descriptions-item label="浪">{{ riskText(cell.risk.wave) }}</el-descriptions-item>
        <el-descriptions-item label="模型">{{ cell.riskModelVersion }}</el-descriptions-item>
      </el-descriptions>
      <div class="risk-cell-subtitle">环境值</div>
      <div class="risk-cell-values">
        <span>水深 {{ cell.environment.depth_m ?? '—' }} m</span>
        <span>冰密集度 {{ cell.environment.ice_concentration ?? '—' }}</span>
        <span>冰厚 {{ cell.environment.ice_thickness_m ?? '—' }} m</span>
        <span>风速 {{ cell.environment.wind_speed_ms ?? '—' }} m/s</span>
        <span>流速 {{ cell.environment.current_speed_ms ?? '—' }} m/s</span>
        <span>浪高 {{ cell.environment.wave_height_m ?? '—' }} m</span>
      </div>
      <div class="risk-cell-subtitle">质量 / 来源</div>
      <div class="risk-cell-quality">
        <el-tag
          v-for="(value, key) in cell.quality"
          :key="key"
          size="small"
          :type="value === 'real' ? 'success' : value === 'synthetic' ? 'warning' : 'info'"
        >{{ key }}: {{ qualityLabels[value] ?? value }}</el-tag>
      </div>
      <div class="risk-cell-sources">
        <span v-for="(value, key) in cell.sources" :key="key">{{ key }}: {{ value }}</span>
      </div>
    </div>

    <div class="risk-area-form">
      <div class="risk-cell-subtitle">评估当前区域（无需先规划）</div>
      <div class="risk-bbox-row">
        <input v-model.number="bboxWest" type="number" step="0.5" placeholder="西经" />
        <input v-model.number="bboxSouth" type="number" step="0.5" placeholder="南纬" />
        <input v-model.number="bboxEast" type="number" step="0.5" placeholder="东经" />
        <input v-model.number="bboxNorth" type="number" step="0.5" placeholder="北纬" />
      </div>
      <el-date-picker
        v-model="departure"
        type="datetime"
        value-format="YYYY-MM-DDTHH:mm:ss"
        format="YYYY-MM-DD HH:mm"
        size="small"
        class="full-width"
      />
      <el-radio-group v-model="dataPolicy" size="small">
        <el-radio value="real_only">真实数据</el-radio>
        <el-radio value="allow_synthetic_research">合成研究</el-radio>
      </el-radio-group>
      <el-button size="small" type="primary" :loading="starting" @click="evaluateArea">提交区域风险评估</el-button>
    </div>
  </section>
</template>
