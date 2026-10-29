<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
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
const snapshotFields = computed(() => {
  const fields = run.value?.environmentSnapshot?.fields
  if (!fields || typeof fields !== 'object') return []
  return Object.values(fields as Record<string, Record<string, unknown>>).map((field) => ({
    field: String(field.field ?? ''),
    quality: String(field.quality ?? 'unknown'),
    source: field.source == null ? '' : String(field.source),
  }))
})
const syntheticOverrides = computed(() => {
  const value = run.value?.environmentSnapshot?.syntheticOverrides
  return value && typeof value === 'object' ? (value as Record<string, number>) : {}
})
const stageLabels: Record<string, string> = {
  queued: '排队',
  planning: '规划',
  environment: '环境采样',
  optimizing: '多目标优化',
  persisting: '结果保存',
  completed: '完成',
  failed: '失败',
  cancelled: '取消',
}

function selectRun(planId: string) {
  void navigation.selectRun(planId)
}

async function renamePlan(planId: string, current: string) {
  try {
    const result = await ElMessageBox.prompt('输入新的任务名称', '重命名规划任务', {
      inputValue: current,
      inputValidator: (value) => (value?.trim() ? true : '名称不能为空'),
    })
    await navigation.renameRun(planId, result.value)
    ElMessage.success('已重命名')
  } catch {
    // cancelled or API error already reported
  }
}

async function deletePlan(planId: string) {
  try {
    await ElMessageBox.confirm('删除后不可恢复（含候选航线与风险栅格文件）', '删除规划任务', {
      type: 'warning',
    })
    await navigation.deleteRun(planId)
    ElMessage.success('已删除')
  } catch {
    // cancelled or API error already reported
  }
}
</script>

<template>
  <section class="planning-result-panel">
    <div class="planning-result-heading">
      <div>
        <span class="eyebrow">PLANNING RUN</span>
        <h3>{{ run?.title || '规划结果' }}</h3>
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
        <span>阶段：{{ stageLabels[run.stage] ?? run.stage }}</span>
        <span>风险模型：{{ run.riskModelVersion }}</span>
        <span>快照：{{ snapshotTime ?? '—' }}</span>
      </div>

      <div v-if="snapshotFields.length" class="planning-snapshot-fields">
        <span class="planning-snapshot-title">算法环境字段：</span>
        <span v-for="field in snapshotFields" :key="String(field.field)" class="planning-snapshot-field">
          {{ field.field }}:
          {{ field.quality ?? '未知' }}
          <template v-if="field.source">（{{ field.source }}）</template>
        </span>
      </div>
      <div v-if="Object.keys(syntheticOverrides).length" class="planning-overrides">
        <span class="planning-snapshot-title">合成覆盖：</span>
        <span v-for="(value, key) in syntheticOverrides" :key="key">{{ key }}={{ value }}</span>
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
        <div class="planning-history-meta">
          <strong>{{ item.title || '智能规划' }}</strong>
          <span>{{ planningStatusLabels[item.status] ?? item.status }}</span>
          <span>{{ new Date(item.createdAt).toISOString().slice(0, 16).replace('T', ' ') }}</span>
        </div>
        <div class="planning-history-actions" @click.stop>
          <el-button size="small" text @click="renamePlan(item.planId, item.title)">重命名</el-button>
          <el-button
            size="small"
            text
            type="danger"
            :disabled="item.status === 'queued' || item.status === 'running'"
            @click="deletePlan(item.planId)"
          >删除</el-button>
        </div>
      </div>
    </div>
  </section>
</template>
