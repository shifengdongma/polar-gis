<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useNavigationStore } from '../stores/navigation'
import type { PlanningRoute } from '../types/navigation'
import type { RouteDraft } from '../types'
import NavigationTaskPanel from './NavigationTaskPanel.vue'
import PlanningResultPanel from './PlanningResultPanel.vue'
import RiskAnalysisPanel from './RiskAnalysisPanel.vue'
import RouteComparisonPanel from './RouteComparisonPanel.vue'
import VesselProfilePanel from './VesselProfilePanel.vue'

const props = defineProps<{ environmentTime?: string | null }>()
const emit = defineEmits<{
  (event: 'adopted', draft: RouteDraft): void
}>()

const navigation = useNavigationStore()
const environmentTime = computed(() => props.environmentTime ?? navigation.snapshotTime)

onMounted(() => {
  void navigation.loadVessels()
  void navigation.loadRuns()
})

function adopt(route: PlanningRoute) {
  const draft = navigation.adoptRoute(route)
  if (!draft) {
    ElMessage.error('采纳航线失败：项目尚未加载')
    return
  }
  ElMessage.success('已采纳为可编辑草稿（非自动驾驶执行）')
  emit('adopted', draft)
}
</script>

<template>
  <section class="intelligent-planning-panel">
    <el-tabs class="planning-tabs">
      <el-tab-pane label="规划任务" name="task">
        <NavigationTaskPanel />
      </el-tab-pane>
      <el-tab-pane label="船舶" name="vessel">
        <VesselProfilePanel
          :vessels="navigation.vessels"
          :selected-id="navigation.vesselId"
          :loading="navigation.vesselsLoading"
          :error="navigation.error"
          @select="(id) => (navigation.vesselId = id)"
        />
      </el-tab-pane>
      <el-tab-pane label="候选对比" name="comparison">
        <RouteComparisonPanel @adopt="adopt" />
      </el-tab-pane>
      <el-tab-pane label="风险" name="risk">
        <RiskAnalysisPanel />
      </el-tab-pane>
      <el-tab-pane label="结果" name="result">
        <PlanningResultPanel :environment-time="environmentTime" />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
