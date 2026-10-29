<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { queryEnvironment } from '../api/navigation'
import { useNavigationStore } from '../stores/navigation'
import { useRoutesStore } from '../stores/routes'
import type { DataPolicy } from '../types/navigation'

const navigation = useNavigationStore()
const routesStore = useRoutesStore()

const planTitle = ref('')
const startLon = ref(120)
const startLat = ref(75)
const goalLon = ref(130)
const goalLat = ref(78)
const departure = ref(new Date().toISOString().slice(0, 19))
const dataPolicy = ref<DataPolicy>('real_only')
const populationSize = ref(36)
const generations = ref(20)
const seed = ref(42)
const submitting = ref(false)
const overrideValues = reactive<Record<string, string>>({
  depthM: '',
  iceConcentration: '',
  iceThicknessM: '',
  windSpeedMs: '',
  windDirectionFromDeg: '',
  currentSpeedMs: '',
  currentDirectionToDeg: '',
  waveHeightM: '',
  wavePeriodS: '',
  waveDirectionFromDeg: '',
})
const syntheticValuesLoaded = ref(false)

watch(dataPolicy, (policy) => {
  if (policy === 'allow_synthetic_research') void loadSyntheticDefaults()
})

const pickedStart = computed(() => navigation.pickedStart)
const pickedGoal = computed(() => navigation.pickedGoal)
const activeRoute = computed(() => routesStore.activeRoute)

watch(
  () => navigation.pickedStart,
  (point) => {
    if (!point) return
    startLon.value = Number(point.longitude.toFixed(6))
    startLat.value = Number(point.latitude.toFixed(6))
  },
)
watch(
  () => navigation.pickedGoal,
  (point) => {
    if (!point) return
    goalLon.value = Number(point.longitude.toFixed(6))
    goalLat.value = Number(point.latitude.toFixed(6))
  },
)

onMounted(() => {
  void navigation.loadVessels()
})

function pickStart() {
  navigation.setPickMode('start')
  ElMessage.info('请在地图上点击起点')
}

function pickGoal() {
  navigation.setPickMode('goal')
  ElMessage.info('请在地图上点击终点')
}

function useCurrentRouteEndpoints() {
  const route = activeRoute.value
  if (!route || route.points.length < 2) {
    ElMessage.warning('当前没有可用的手绘航路')
    return
  }
  const points = [...route.points].sort((a, b) => a.seq - b.seq)
  startLon.value = points[0].lon
  startLat.value = points[0].lat
  goalLon.value = points[points.length - 1].lon
  goalLat.value = points[points.length - 1].lat
}

function collectOverrides(): Record<string, number> | undefined {
  if (dataPolicy.value !== 'allow_synthetic_research') return undefined
  const result: Record<string, number> = {}
  for (const [key, raw] of Object.entries(overrideValues)) {
    if (raw.trim() === '') continue
    const value = Number(raw)
    if (Number.isFinite(value)) result[key] = value
  }
  return Object.keys(result).length ? result : undefined
}

async function loadSyntheticDefaults() {
  try {
    const sample = await queryEnvironment({
      longitude: Number(startLon.value),
      latitude: Number(startLat.value),
      time: departure.value.endsWith('Z') ? departure.value : `${departure.value}Z`,
      fields: ['bathymetry', 'ice', 'wind', 'current', 'wave'],
      dataPolicy: 'allow_synthetic_research',
    })
    const set = (key: string, value: unknown) => {
      if (typeof value === 'number' && Number.isFinite(value)) {
        overrideValues[key] = String(Number(value.toFixed(4)))
      }
    }
    set('depthM', sample.fields.bathymetry?.values.depthM)
    set('iceConcentration', sample.fields.ice?.values.concentration)
    set('iceThicknessM', sample.fields.ice?.values.thicknessM)
    set('windSpeedMs', sample.fields.wind?.values.speedMs)
    set('windDirectionFromDeg', sample.fields.wind?.values.directionFromDeg)
    set('currentSpeedMs', sample.fields.current?.values.speedMs)
    set('currentDirectionToDeg', sample.fields.current?.values.directionToDeg)
    set('waveHeightM', sample.fields.wave?.values.heightM)
    set('wavePeriodS', sample.fields.wave?.values.periodS)
    set('waveDirectionFromDeg', sample.fields.wave?.values.directionFromDeg)
    syntheticValuesLoaded.value = true
    ElMessage.success('已读取起点环境值；可直接修改，清空则恢复自动处理')
  } catch {
    syntheticValuesLoaded.value = false
    ElMessage.error('起点环境值读取失败，请检查时间/坐标或数据源')
  }
}

function clearOverrides() {
  for (const key of Object.keys(overrideValues)) overrideValues[key] = ''
  syntheticValuesLoaded.value = false
  ElMessage.info('已清空合成覆盖，规划将使用 Provider / 确定性 gap-fill')
}

async function submit() {
  if (!navigation.projectId) {
    ElMessage.error('项目尚未加载')
    return
  }
  const start = { longitude: Number(startLon.value), latitude: Number(startLat.value) }
  const goal = { longitude: Number(goalLon.value), latitude: Number(goalLat.value) }
  if (!Number.isFinite(start.longitude) || !Number.isFinite(start.latitude)) {
    ElMessage.error('起点经纬度不合法')
    return
  }
  if (!Number.isFinite(goal.longitude) || !Number.isFinite(goal.latitude)) {
    ElMessage.error('终点经纬度不合法')
    return
  }
  submitting.value = true
  try {
    await navigation.startPlan({
      projectId: navigation.projectId,
      title: planTitle.value.trim() || undefined,
      start,
      goal,
      departureTime: departure.value.endsWith('Z') ? departure.value : `${departure.value}Z`,
      vesselId: navigation.vesselId,
      dataPolicy: dataPolicy.value,
      algorithm: 'dnsga3',
      objectives: ['risk', 'energy', 'time'],
      populationSize: populationSize.value,
      generations: generations.value,
      seed: seed.value,
      syntheticOverrides: collectOverrides(),
    })
    navigation.setDataPolicy(dataPolicy.value)
    ElMessage.success('规划任务已提交')
  } catch {
    // navigation.error already carries the API message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="navigation-task-panel">
    <el-alert
      title="智能规划为辅助决策原型，不构成认证 ECDIS 或自动驾驶指令；候选航线必须人工审核。"
      type="warning"
      :closable="false"
      show-icon
    />

    <div class="navigation-form-section">
      <div class="navigation-form-title">任务名称</div>
      <el-input v-model="planTitle" size="small" maxlength="120" placeholder="可选；默认“智能规划”" />
    </div>

    <div class="navigation-form-section">
      <div class="navigation-form-title">起终点（WGS84）</div>
      <div class="navigation-coordinate-row">
        <el-input-number v-model="startLon" :precision="6" :controls="false" size="small" placeholder="起点经度" />
        <el-input-number v-model="startLat" :precision="6" :controls="false" size="small" placeholder="起点纬度" />
        <el-button size="small" type="primary" plain @click="pickStart">地图选起点</el-button>
      </div>
      <div class="navigation-coordinate-row">
        <el-input-number v-model="goalLon" :precision="6" :controls="false" size="small" placeholder="终点经度" />
        <el-input-number v-model="goalLat" :precision="6" :controls="false" size="small" placeholder="终点纬度" />
        <el-button size="small" type="primary" plain @click="pickGoal">地图选终点</el-button>
      </div>
      <div class="navigation-picked-hint">
        <span v-if="pickedStart">起点已选：{{ pickedStart.longitude.toFixed(4) }}, {{ pickedStart.latitude.toFixed(4) }}</span>
        <span v-if="pickedGoal">终点已选：{{ pickedGoal.longitude.toFixed(4) }}, {{ pickedGoal.latitude.toFixed(4) }}</span>
        <el-button size="small" text :disabled="!activeRoute" @click="useCurrentRouteEndpoints">取当前手绘航路端点</el-button>
      </div>
    </div>

    <div class="navigation-form-section">
      <div class="navigation-form-title">出发时间（UTC）与船舶</div>
      <el-date-picker
        v-model="departure"
        type="datetime"
        value-format="YYYY-MM-DDTHH:mm:ss"
        format="YYYY-MM-DD HH:mm"
        size="small"
        class="full-width"
      />
      <el-select v-model="navigation.vesselId" size="small" class="full-width" :loading="navigation.vesselsLoading">
        <el-option v-for="vessel in navigation.vessels" :key="vessel.id" :label="vessel.name" :value="vessel.id" />
      </el-select>
    </div>

    <div class="navigation-form-section">
      <div class="navigation-form-title">目标与数据策略</div>
      <div class="navigation-objectives">
        <el-checkbox :model-value="true" disabled>风险 Risk</el-checkbox>
        <el-checkbox :model-value="true" disabled>能耗 Energy</el-checkbox>
        <el-checkbox :model-value="true" disabled>航时 Time</el-checkbox>
      </div>
      <small class="navigation-form-note">NSGA-III 固定三目标；距离仅作统计，不参与优化。</small>
      <el-radio-group v-model="dataPolicy" size="small">
        <el-radio value="real_only">真实数据 only（默认）</el-radio>
        <el-radio value="allow_synthetic_research">合成研究数据</el-radio>
      </el-radio-group>
      <el-alert
        v-if="dataPolicy === 'allow_synthetic_research'"
        title="含合成环境数据，不可作为真实航行决策依据"
        type="warning"
        :closable="false"
        show-icon
      />
    </div>

    <div v-if="dataPolicy === 'allow_synthetic_research'" class="navigation-form-section">
      <div class="navigation-form-title">合成环境参数（仅研究验证）</div>
      <small class="navigation-form-note">
        算法需要：水深、冰密集度/冰厚、风速/风向、流速/流向、浪高/周期/浪向。空值表示不覆盖，
        由 Provider 或确定性 gap-fill 自动处理；填写后应用到全规划区，并标记为 synthetic。
      </small>
      <div class="navigation-override-actions">
        <el-button size="small" plain @click="loadSyntheticDefaults">从起点读取当前环境值</el-button>
        <el-button size="small" text @click="clearOverrides">清空覆盖</el-button>
        <span v-if="syntheticValuesLoaded" class="navigation-override-loaded">已载入实际合成值，可修改</span>
      </div>
      <div class="navigation-override-grid">
        <label>水深 m<el-input v-model="overrideValues.depthM" size="small" placeholder="自动" /></label>
        <label>冰密集度 0–1<el-input v-model="overrideValues.iceConcentration" size="small" placeholder="自动" /></label>
        <label>冰厚 m<el-input v-model="overrideValues.iceThicknessM" size="small" placeholder="自动" /></label>
        <label>风速 m/s<el-input v-model="overrideValues.windSpeedMs" size="small" placeholder="自动" /></label>
        <label>风向 FROM °<el-input v-model="overrideValues.windDirectionFromDeg" size="small" placeholder="自动" /></label>
        <label>流速 m/s<el-input v-model="overrideValues.currentSpeedMs" size="small" placeholder="自动" /></label>
        <label>流向 TO °<el-input v-model="overrideValues.currentDirectionToDeg" size="small" placeholder="自动" /></label>
        <label>浪高 m<el-input v-model="overrideValues.waveHeightM" size="small" placeholder="自动" /></label>
        <label>浪周期 s<el-input v-model="overrideValues.wavePeriodS" size="small" placeholder="自动" /></label>
        <label>浪向 FROM °<el-input v-model="overrideValues.waveDirectionFromDeg" size="small" placeholder="自动" /></label>
      </div>
    </div>

    <div class="navigation-form-section">
      <div class="navigation-form-title">算法参数</div>
      <div class="navigation-param-row">
        <label>种群<input v-model.number="populationSize" type="number" min="6" max="120" /></label>
        <label>代数<input v-model.number="generations" type="number" min="1" max="100" /></label>
        <label>seed<input v-model.number="seed" type="number" min="0" /></label>
      </div>
    </div>

    <el-alert v-if="navigation.error" :title="navigation.error" type="error" :closable="false" show-icon />
    <el-button
      type="primary"
      :loading="submitting || navigation.loading"
      class="navigation-submit"
      @click="submit"
    >
      开始智能规划
    </el-button>
  </section>
</template>
