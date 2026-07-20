<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, apiErrorMessage } from '../../api/client'
import type { ImportJob, Paginated } from '../../types'

const jobs = ref<ImportJob[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(15)
let timer: number | undefined
const statusLabels: Record<string, string> = {
  queued: '排队',
  running: '处理中',
  succeeded: '成功',
  failed: '失败',
  cancelled: '取消',
}

function executionTime(job: ImportJob) {
  if (job.finishedAt) return { label: '完成', value: job.finishedAt }
  if (job.startedAt) return { label: '开始', value: job.startedAt }
  return { label: '排队', value: job.queuedAt }
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

async function loadJobs(targetPage = page.value) {
  const response = await api.get<Paginated<ImportJob>>('/admin/import-jobs', { params: { page: targetPage, pageSize: pageSize.value } })
  jobs.value = response.data.items
  total.value = response.data.total
  page.value = response.data.page
}

async function retry(job: ImportJob) {
  try {
    await api.post(`/admin/import-jobs/${job.id}/retry`)
    ElMessage.success('任务已重新排队')
    await loadJobs()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
}

onMounted(() => {
  loadJobs()
  timer = window.setInterval(loadJobs, 3000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page-stack">
    <section class="page-intro compact"><div><span class="eyebrow">IMPORT PIPELINE</span><h2>导入任务</h2><p>查看GDAL处理、PostGIS入库和GeoServer发布进度。</p></div></section>
    <el-card shadow="never" class="data-card">
      <el-table :data="jobs" stripe>
        <el-table-column prop="jobType" label="任务类型" width="140" />
        <el-table-column prop="stage" label="当前阶段" width="130" />
        <el-table-column label="进度" min-width="220"><template #default="{ row }"><el-progress :percentage="row.progress" :status="row.status === 'failed' ? 'exception' : row.status === 'succeeded' ? 'success' : undefined" /></template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><span :class="['status-pill', row.status]">{{ statusLabels[row.status] || row.status }}</span></template></el-table-column>
        <el-table-column label="执行时间" width="190"><template #default="{ row }"><span class="job-time"><em>{{ executionTime(row).label }}</em>{{ formatDateTime(executionTime(row).value) }}</span></template></el-table-column>
        <el-table-column label="错误" min-width="220"><template #default="{ row }"><span class="error-text">{{ row.errorMessage || '—' }}</span></template></el-table-column>
        <el-table-column label="操作" width="100" align="right"><template #default="{ row }"><el-button v-if="row.status === 'failed'" link type="primary" @click="retry(row)">重试</el-button></template></el-table-column>
      </el-table>
      <div v-if="total" class="table-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[10, 15, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="loadJobs" @size-change="loadJobs(1)" /></div>
    </el-card>
  </div>
</template>
