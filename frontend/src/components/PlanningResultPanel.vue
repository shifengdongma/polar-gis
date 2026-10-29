<script setup lang="ts">
import { computed } from 'vue'
import { useNavigationStore } from '../stores/navigation'
import {
  planningErrorMessage,
  planningSnapshotTime,
  planningStatusLabels,
} from '../utils/routePlanning'

const props = defineProps<{ environmentTime?: string | null }>()
const navigation = useNavigationStore()

const run = computed(() => navigation.currentRun)
const statusLabel = computed(() =>
  run.value ? planningStatusLabels[run.value.status] ?? run.value.status : '未创建',
)
const errorText = computed(() => planningErrorMessage(run.value))
const snapshotTime = computed(() => planningSnapshotTime(run.value))
const snapshotMismatch = computed(() => {
  if (!snapshotTime.value || !props.environmentTime) return false
  const normalize = (value: string) => new Date(value).toISOString().slice(0, 16)
  return normalize(snapshotTime.value) !== normalize(props.environmentTime)
})
const missingFields = computed(() => {
  const value = run.value?.resultSummary?.missingByField
  return value && typeof value === 'object' ? (value as Record<string, number>) : {}
})

function selectRun(planId: string) {
  void navigation.selectRun(planId)
}
</script>

<template>
  <section class="planning-result-panel">
    <div class="planning-result-heading">
      <div>
        <span class="eyebrow">PLANNING RUN</span>
        <h3>规划结果</h3>
      </div>
      <el-tag size="small" :type="run?.status === 'completed' ? 'success' : run?.status === 'failed' ? 'danger' : 'info'">
        {{ statusLabel }}
      </el-tag>
    </div>

    <el-alert
      v-if="navigation.isSynthetic"
      title="含合成环境数据，不可作为真实航行决策依据"
      type="warning"
      :closable="false"
      show-icon
    />

    <template v-if="run">
      <el-progress
        :percentage="run.progress"
        :status="run.status === 'failed' ? 'exception' : run.status === 'completed' ? 'success' : undefined"
        :stroke-width="5"
      />
      <div class="planning-result-meta">
        <span>任务：{{ run.planId.slice(0, 8) }}</span>
        <span>阶段：{{ run.stage }}</span>
        <span>风险模型：{{ run.riskModelVersion }}</span>
        <span>快照：{{ snapshotTime ?? '—' }}</span>
      </div>

      <el-alert
        v-if="snapshotMismatch"
        title="规划快照时间与当前地图环境时间不同；结果不会被自动覆盖，如需新时间请创建新任务"
        type="info"
        :closable="false"
        show-icon
      />
      <el-alert v-if="errorText" :title="errorText" type="error" :closable="false" show-icon />

      <div v-if="Object.keys(missingFields).length" class="planning-missing-fields">
        <span>{{ navigation.isSynthetic ? '原始 Provider 缺测（已用合成 gap-fill 补足）：' : '缺测字段：' }}</span>
        <el-tag
          v-for="(count, field) in missingFields"
          :key="field"
          size="small"
          type="warning"
        >{{ field }}: {{ count }}</el-tag>
      </div>

      <div class="planning-result-actions">
        <el-button size="small" :disabled="!navigation.isActiveRun" @click="navigation.cancelCurrent()">
          取消任务
        </el-button>
        <el-button size="small" :disabled="!run" @click="navigation.selectRun(run.planId)">刷新</el-button>
      </div>
    </template>
    <el-empty v-else description="尚未提交规划任务" :image-size="40" />

    <div v-if="navigation.runs.length" class="planning-history">
      <div class="planning-history-title">历史任务</div>
      <div
        v-for="item in navigation.runs"
        :key="item.planId"
        class="planning-history-item"
        :class="{ 'is-active': item.planId === run?.planId }"
        @click="selectRun(item.planId)"
      >
        <span>{{ item.planId.slice(0, 8) }}</span>
        <span>{{ planningStatusLabels[item.status] ?? item.status }}</span>
        <span>{{ new Date(item.createdAt).toISOString().slice(0, 16).replace('T', ' ') }}</span>
      </div>
    </div>
  </section>
</template>
