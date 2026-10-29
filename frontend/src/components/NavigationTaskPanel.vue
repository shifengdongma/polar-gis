<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useNavigationStore } from '../stores/navigation'
import { useRoutesStore } from '../stores/routes'
import type { DataPolicy } from '../types/navigation'

const navigation = useNavigationStore()
const routesStore = useRoutesStore()

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
