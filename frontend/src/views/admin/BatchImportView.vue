<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { api, apiErrorMessage } from '../../api/client'
import type { Paginated, S57ImportBatch, S57ImportBatchDetail } from '../../types'

const dialogVisible = ref(false)
const detailVisible = ref(false)
const saving = ref(false)
const batchMode = ref<'zip' | 'directory'>('zip')
const batchName = ref('')
const batchFiles = ref<File[]>([])
const uploadProgress = ref(0)
const batches = ref<S57ImportBatch[]>([])
const page = ref(1)
const pageSize = ref(15)
const total = ref(0)
const detail = ref<S57ImportBatchDetail | null>(null)
const directoryInput = ref<HTMLInputElement>()
let timer: number | undefined

const statusLabels: Record<string, string> = {
  queued: '排队', running: '处理中', succeeded: '成功', partial_failed: '部分失败', failed: '失败', paused: '已暂停', cancelled: '已取消',
}
const itemStageLabels: Record<string, string> = {
  import_base: '导入基础单元', append_updates: '追加更新', up_to_date: '已是最新', completed: '已完成', failed: '失败', cancelled: '已取消',
}

async function loadBatches(targetPage = page.value) {
  const response = await api.get<Paginated<S57ImportBatch>>('/admin/s57-import-batches', {
    params: { page: targetPage, pageSize: pageSize.value },
  })
  batches.value = response.data.items
  page.value = response.data.page
  total.value = response.data.total
  if (detail.value && ['queued', 'running', 'paused'].includes(detail.value.status)) {
    detail.value = (await api.get<S57ImportBatchDetail>(`/admin/s57-import-batches/${detail.value.id}`)).data
  }
}

async function pauseBatch(batch: S57ImportBatch) {
  try {
    await api.post(`/admin/s57-import-batches/${batch.id}/pause`)
    ElMessage.success('已发送暂停指令')
    await loadBatches()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '暂停失败'))
  }
}

async function resumeBatch(batch: S57ImportBatch) {
  try {
    await api.post(`/admin/s57-import-batches/${batch.id}/resume`)
    ElMessage.success('已恢复处理')
    await loadBatches()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '恢复失败'))
  }
}

async function cancelBatch(batch: S57ImportBatch) {
  try {
    await api.post(`/admin/s57-import-batches/${batch.id}/cancel`)
    ElMessage.success('已取消批次')
    await loadBatches()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '取消失败'))
  }
}

function openDialog() {
  batchName.value = ''
  batchFiles.value = []
  uploadProgress.value = 0
  batchMode.value = 'zip'
  dialogVisible.value = true
}

function selectZip(uploadFile: UploadFile) {
  const file = uploadFile.raw
  batchFiles.value = file ? [file] : []
  if (file && !batchName.value) batchName.value = file.name.replace(/\.zip$/i, '')
}

function selectDirectory(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files || [])
  batchFiles.value = selected.filter((file) => /^.+\.\d{3}$/i.test(file.name))
  const ignored = selected.length - batchFiles.value.length
  if (ignored) ElMessage.info(`已忽略 ${ignored} 个非 S-57 文件`)
  const relativePath = batchFiles.value[0]?.webkitRelativePath
  if (relativePath && !batchName.value) batchName.value = relativePath.split('/')[0]
}

async function createBatch() {
  if (!batchName.value.trim()) {
    ElMessage.warning('请输入批次名称')
    return
  }
  if (!batchFiles.value.length) {
    ElMessage.warning(batchMode.value === 'zip' ? '请选择 ZIP 文件' : '请选择 S-57 目录')
    return
  }
  saving.value = true
  uploadProgress.value = 0
  try {
    const body = new FormData()
    body.append('name', batchName.value.trim())
    batchFiles.value.forEach((file) => body.append('files', file, file.name))
    await api.post('/admin/s57-import-batches', body, {
      timeout: 0,
      onUploadProgress: (event) => {
        uploadProgress.value = event.total ? Math.round(event.loaded * 100 / event.total) : 0
      },
    })
    ElMessage.success('批量导入已进入处理队列')
    dialogVisible.value = false
    await loadBatches(1)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '批量导入创建失败'))
  } finally {
    saving.value = false
  }
}

async function viewBatch(batch: S57ImportBatch) {
  try {
    detail.value = (await api.get<S57ImportBatchDetail>(`/admin/s57-import-batches/${batch.id}`)).data
    detailVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '批次详情加载失败'))
  }
}

onMounted(() => {
  loadBatches()
  timer = window.setInterval(loadBatches, 3000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page-stack">
    <section class="page-intro compact">
      <div><span class="eyebrow">S-57 BATCH IMPORT</span><h2>批量导入</h2><p>按海图单元识别基础单元与连续更新，并跟踪每个单元的处理结果。</p></div>
      <div class="header-actions"><el-button type="primary" @click="openDialog">新建批量导入</el-button></div>
    </section>
    <el-card shadow="never" class="data-card">
      <div class="catalog-table-head"><div><strong>导入批次</strong><span>共 {{ total }} 个批次</span></div></div>
      <el-table :data="batches" stripe empty-text="暂无批量导入记录">
        <el-table-column prop="name" label="批次" min-width="190" />
        <el-table-column label="进度" min-width="220"><template #default="{ row }"><el-progress :percentage="row.progress" :status="row.status === 'failed' ? 'exception' : row.status === 'succeeded' ? 'success' : undefined" /></template></el-table-column>
        <el-table-column label="单元" width="180"><template #default="{ row }">{{ row.processedCells }}/{{ row.totalCells || '待识别' }} · 成功 {{ row.succeededCells }} · 失败 {{ row.failedCells }}</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><span :class="['status-pill', row.status]">{{ statusLabels[row.status] || row.status }}</span></template></el-table-column>
        <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ new Date(row.createdAt).toLocaleString('zh-CN') }}</template></el-table-column>
        <el-table-column label="操作" width="220" align="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'running'" link type="warning" @click="pauseBatch(row)">暂停</el-button>
            <el-button v-if="row.status === 'paused'" link type="success" @click="resumeBatch(row)">继续</el-button>
            <el-button v-if="['queued', 'running', 'paused'].includes(row.status)" link type="danger" @click="cancelBatch(row)">取消</el-button>
            <el-button link type="primary" @click="viewBatch(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="total" class="table-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[10, 15, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="loadBatches" @size-change="loadBatches(1)" /></div>
    </el-card>
    <el-dialog v-model="dialogVisible" title="批量导入 S-57" width="620px">
      <el-alert title="系统按海图单元分组，并严格按 .000、.001、.002…顺序处理。" type="info" :closable="false" class="dialog-alert" />
      <el-form label-position="top">
        <el-form-item label="批次名称"><el-input v-model="batchName" maxlength="180" placeholder="例如：北极海图 2026-07" /></el-form-item>
        <el-form-item label="来源"><el-segmented v-model="batchMode" :options="[{ label: 'ZIP 压缩包', value: 'zip' }, { label: '本地目录', value: 'directory' }]" @change="batchFiles = []" /></el-form-item>
        <el-form-item v-if="batchMode === 'zip'" label="ZIP 文件"><el-upload drag :auto-upload="false" :limit="1" accept=".zip" :on-change="selectZip" :on-remove="() => (batchFiles = [])"><div class="upload-copy"><strong>拖拽 ZIP 到此处，或点击选择</strong><span>压缩包内可包含多个海图单元及连续更新文件</span></div></el-upload></el-form-item>
        <el-form-item v-else label="S-57 目录"><input ref="directoryInput" type="file" multiple webkitdirectory class="visually-hidden" @change="selectDirectory" /><div class="directory-picker"><el-button @click="directoryInput?.click()">选择目录</el-button><span>{{ batchFiles.length ? `已识别 ${batchFiles.length} 个 S-57 文件` : '尚未选择目录' }}</span></div></el-form-item>
        <el-progress v-if="saving" :percentage="uploadProgress" />
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="createBatch">上传并排队</el-button></template>
    </el-dialog>
    <el-drawer v-model="detailVisible" :title="`${detail?.name || ''} · 批次详情`" size="760px">
      <div v-if="detail" class="batch-summary"><el-progress :percentage="detail.progress" :status="detail.status === 'failed' ? 'exception' : detail.status === 'succeeded' ? 'success' : undefined" /><span>成功 {{ detail.succeededCells }}，失败 {{ detail.failedCells }}，共 {{ detail.totalCells }} 个单元</span></div>
      <el-table :data="detail?.items || []" stripe>
        <el-table-column prop="cellName" label="海图单元" min-width="130" />
        <el-table-column label="更新链" width="120"><template #default="{ row }">.000 - .{{ String(row.updateCount).padStart(3, '0') }}</template></el-table-column>
        <el-table-column label="当前更新" width="100"><template #default="{ row }">.{{ String(row.currentUpdate).padStart(3, '0') }}</template></el-table-column>
        <el-table-column label="结果" width="120"><template #default="{ row }">{{ itemStageLabels[row.stage] || row.stage }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><span :class="['status-pill', row.status]">{{ statusLabels[row.status] || row.status }}</span></template></el-table-column>
        <el-table-column label="失败原因" min-width="220"><template #default="{ row }"><span v-if="row.errorMessage" class="error-text">{{ row.errorMessage }}</span><span v-else>—</span></template></el-table-column>
      </el-table>
    </el-drawer>
  </div>
</template>
