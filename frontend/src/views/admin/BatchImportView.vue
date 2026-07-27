<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, computed } from 'vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { api, apiErrorMessage } from '../../api/client'
import type {
  Paginated, S57ImportBatch, S57ImportBatchDetail,
  BasemapProfile, BasemapPreflightResponse, BasemapRunDetail,
} from '../../types'

// ── standard batch state ──────────────────────────────────────────

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

// ── basemap state ──────────────────────────────────────────────────

const basemapProfiles = ref<BasemapProfile[]>([])
const basemapSelectedProfile = ref('global_overview_v1')
const basemapPreflightResult = ref<BasemapPreflightResponse | null>(null)
const basemapPreflightVisible = ref(false)
const basemapPreflighting = ref(false)
const basemapImporting = ref(false)
const basemapShowAdvanced = ref(false)
const basemapAdvanced = ref({
  includeBand2: false,
  setAsDefault: false,
  buildWmts3413: true,
  warmLowZoom: false,
})
const basemapSourceMode = ref<'server_directory' | 'upload'>('server_directory')
const basemapRunDetail = ref<BasemapRunDetail | null>(null)
const basemapRunVisible = ref(false)

const basemapStatusText = computed(() => {
  const r = basemapPreflightResult.value
  if (!r) return '未导入'
  if (basemapImporting.value) return '导入中'
  if (r.skipCellCount === r.expectedCellCount) return '已是最新'
  if (r.updateCellCount > 0 || r.createCellCount > 0) return '有可用更新'
  return '未导入'
})

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
  loadBasemapProfiles()
  timer = window.setInterval(loadBatches, 3000)
})
onBeforeUnmount(() => window.clearInterval(timer))

// ── basemap functions ──────────────────────────────────────────────

async function loadBasemapProfiles() {
  try {
    basemapProfiles.value = (await api.get<BasemapProfile[]>('/admin/s57-basemaps/profiles')).data
  } catch { /* silently fail */ }
}

async function runBasemapPreflight() {
  basemapPreflighting.value = true
  try {
    const body: Record<string, unknown> = {
      profileCode: basemapSelectedProfile.value,
      sourceType: basemapSourceMode.value,
    }
    basemapPreflightResult.value = (await api.post<BasemapPreflightResponse>(
      '/admin/s57-basemaps/preflight', body,
    )).data
    basemapPreflightVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '预检失败'))
  } finally {
    basemapPreflighting.value = false
  }
}

async function startBasemapImport() {
  if (!basemapPreflightResult.value?.canStart) return
  basemapImporting.value = true
  try {
    const body = {
      profileCode: basemapSelectedProfile.value,
      manifestHash: basemapPreflightResult.value.manifestHash,
      sourceType: basemapSourceMode.value,
      setAsDefault: basemapAdvanced.value.setAsDefault,
      buildWmts3857: true,
      buildWmts3413: basemapAdvanced.value.buildWmts3413,
      warmLowZoomCache: basemapAdvanced.value.warmLowZoom,
    }
    await api.post('/admin/s57-basemaps/import', body)
    ElMessage.success('底图导入已启动')
    basemapPreflightVisible.value = false
    await loadBatches()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '导入启动失败'))
  } finally {
    basemapImporting.value = false
  }
}

const actionLabels: Record<string, string> = {
  create: '新建', append_updates: '追加更新', skip_current: '已是最新', blocked: '阻塞',
}

async function viewBasemapRun(batchId: string) {
  try {
    basemapRunDetail.value = (await api.get<BasemapRunDetail>(
      `/admin/s57-basemaps/runs/${batchId}`,
    )).data
    basemapRunVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '加载运行详情失败'))
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`
  return `${(bytes / 1073741824).toFixed(2)} GB`
}
</script>

<template>
  <div class="page-stack">
    <section class="page-intro compact">
      <div><span class="eyebrow">S-57 BATCH IMPORT</span><h2>批量导入</h2><p>按海图单元识别基础单元与连续更新，或一键导入全球海图概览底图。</p></div>
      <div class="header-actions"><el-button type="primary" @click="openDialog">新建批量导入</el-button></div>
    </section>

    <!-- ═══ Basemap Section ═══ -->
    <el-card shadow="never" class="data-card basemap-card">
      <div class="basemap-header">
        <div class="basemap-info">
          <span class="basemap-title">🌐 全球海图概览底图</span>
          <span class="basemap-sub">
            当前数据包：{{ basemapPreflightResult?.expectedCellCount || basemapProfiles[0]?.cellCount || 18 }} 个概览Cell
            / {{ basemapPreflightResult?.expectedFileCount || basemapProfiles[0]?.fileCount || 29 }} 个文件
            <template v-if="basemapPreflightResult?.totalSizeBytes">
              · {{ formatBytes(basemapPreflightResult.totalSizeBytes) }}
            </template>
          </span>
          <span class="basemap-sub">
            覆盖范围：{{ basemapPreflightResult?.coverageMessage || '待预检' }}
          </span>
          <span :class="['status-pill', basemapImporting ? 'running' : basemapPreflightResult?.canStart ? 'succeeded' : '']">
            {{ basemapStatusText }}
          </span>
        </div>
        <div class="basemap-actions">
          <el-button :loading="basemapPreflighting" @click="runBasemapPreflight">
            {{ basemapPreflightResult ? '重新预检数据包' : '预检数据包' }}
          </el-button>
          <el-button
            type="primary"
            :disabled="!basemapPreflightResult?.canStart || basemapPreflightResult?.blockedCellCount > 0"
            :loading="basemapImporting"
            @click="startBasemapImport"
          >
            {{ basemapPreflightResult?.skipCellCount === basemapPreflightResult?.expectedCellCount && basemapPreflightResult?.createCellCount === 0 ? '重建底图发布' : '一键导入/更新' }}
          </el-button>
          <el-button
            v-if="basemapRunDetail"
            link
            type="primary"
            @click="basemapRunVisible = true"
          >查看最近任务</el-button>
          <el-button link type="info" @click="basemapShowAdvanced = !basemapShowAdvanced">
            高级选项 {{ basemapShowAdvanced ? '▴' : '▾' }}
          </el-button>
        </div>
      </div>

      <div v-if="basemapShowAdvanced" class="basemap-advanced">
        <el-checkbox v-model="basemapAdvanced.includeBand2">
          导入用途等级2区域增强数据
        </el-checkbox>
        <span class="hint-text">将额外处理71个Cell、776个文件。区域增强数据不会合并到默认概览WMTS底图。</span>
        <br />
        <el-checkbox v-model="basemapAdvanced.setAsDefault">导入后设为默认底图</el-checkbox>
        <br />
        <el-checkbox v-model="basemapAdvanced.buildWmts3413">创建EPSG:3413 WMTS</el-checkbox>
        <br />
        <el-checkbox v-model="basemapAdvanced.warmLowZoom">预热低缩放级别缓存</el-checkbox>
      </div>
    </el-card>

    <!-- ═══ Standard batch table ═══ -->
    <el-card shadow="never" class="data-card">
      <div class="catalog-table-head"><div><strong>导入批次</strong><span>共 {{ total }} 个批次</span></div></div>
      <el-table :data="batches" stripe empty-text="暂无批量导入记录">
        <el-table-column prop="name" label="批次" min-width="190"><template #default="{ row }"><span>{{ row.name }}</span><el-tag v-if="row.purpose === 'basemap'" size="small" type="warning" effect="plain" style="margin-left:6px">底图</el-tag></template></el-table-column>
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

    <!-- ═══ Basemap Preflight Dialog ═══ -->
    <el-dialog v-model="basemapPreflightVisible" title="预检结果 — 全球海图概览底图" width="720px">
      <template v-if="basemapPreflightResult">
        <div class="preflight-grid">
          <div class="pf-item"><strong>Profile</strong><span>{{ basemapPreflightResult.profileName }}</span></div>
          <div class="pf-item"><strong>数据源</strong><span>{{ basemapSourceMode === 'server_directory' ? '服务器目录' : '上传' }}</span></div>
          <div class="pf-item"><strong>预期Cell数</strong><span>{{ basemapPreflightResult.expectedCellCount }}</span></div>
          <div class="pf-item"><strong>发现Cell数</strong><span>{{ basemapPreflightResult.discoveredCellCount }}</span></div>
          <div class="pf-item"><strong>选中文件数</strong><span>{{ basemapPreflightResult.selectedFileCount }}</span></div>
          <div class="pf-item"><strong>忽略文件数</strong><span>{{ basemapPreflightResult.ignoredFileCount }}</span></div>
          <div class="pf-item"><strong>新建Cell</strong><span class="pf-create">{{ basemapPreflightResult.createCellCount }}</span></div>
          <div class="pf-item"><strong>更新Cell</strong><span class="pf-update">{{ basemapPreflightResult.updateCellCount }}</span></div>
          <div class="pf-item"><strong>已是最新</strong><span class="pf-skip">{{ basemapPreflightResult.skipCellCount }}</span></div>
          <div class="pf-item"><strong>阻塞</strong><span :class="basemapPreflightResult.blockedCellCount > 0 ? 'pf-blocked' : ''">{{ basemapPreflightResult.blockedCellCount }}</span></div>
          <div class="pf-item"><strong>文件总大小</strong><span>{{ formatBytes(basemapPreflightResult.totalSizeBytes) }}</span></div>
          <div class="pf-item"><strong>覆盖验证</strong><span>{{ basemapPreflightResult.coverageVerified ? '已验证' : '未验证全球无缝覆盖' }}</span></div>
        </div>
        <el-alert
          v-if="basemapPreflightResult.blockedCellCount > 0"
          title="存在阻塞的Cell，无法启动导入"
          type="error"
          :closable="false"
          style="margin-top:12px"
        />
        <el-alert
          v-if="basemapPreflightResult.ignoredFiles.length > 0"
          :title="`已忽略 ${basemapPreflightResult.ignoredFileCount} 个文件（用途等级2/3或非S-57文件，前100项）`"
          type="warning"
          :closable="false"
          style="margin-top:12px"
        />
        <el-table
          v-if="basemapPreflightResult.cells.length > 0"
          :data="basemapPreflightResult.cells"
          stripe
          size="small"
          style="margin-top:12px"
          max-height="300"
        >
          <el-table-column prop="cellName" label="Cell" width="130" />
          <el-table-column label="更新号" width="80"><template #default="{ row }">.000-.{{ String(row.expectedMaxUpdate).padStart(3, '0') }}</template></el-table-column>
          <el-table-column label="发现" width="70"><template #default="{ row }">{{ row.discoveredUpdates?.length || 0 }}</template></el-table-column>
          <el-table-column label="操作" width="110"><template #default="{ row }"><span :class="['pf-action', row.action]">{{ actionLabels[row.action] || row.action }}</span></template></el-table-column>
          <el-table-column label="用途等级" width="80"><template #default="{ row }">{{ row.usageBand ?? '-' }}</template></el-table-column>
          <el-table-column label="DB更新" width="80"><template #default="{ row }">{{ row.databaseCurrentUpdate !== null ? `.${String(row.databaseCurrentUpdate).padStart(3, '0')}` : '无' }}</template></el-table-column>
          <el-table-column label="错误" min-width="180"><template #default="{ row }"><span v-if="row.errors?.length" class="error-text">{{ row.errors.join('; ') }}</span><span v-else>—</span></template></el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="basemapPreflightVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="!basemapPreflightResult?.canStart"
          :loading="basemapImporting"
          @click="startBasemapImport"
        >
          {{ basemapPreflightResult?.skipCellCount === basemapPreflightResult?.expectedCellCount && basemapPreflightResult?.createCellCount === 0 ? '重建底图发布' : '一键导入/更新' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ═══ Basemap Run Detail Drawer ═══ -->
    <el-drawer v-model="basemapRunVisible" title="底图导入运行详情" size="760px">
      <template v-if="basemapRunDetail">
        <div class="basemap-run-summary">
          <el-progress
            :percentage="basemapRunDetail.progress"
            :status="basemapRunDetail.status === 'failed' ? 'exception' : basemapRunDetail.status === 'succeeded' ? 'success' : undefined"
          />
          <span>成功 {{ basemapRunDetail.succeededCells }}，失败 {{ basemapRunDetail.failedCells }}，共 {{ basemapRunDetail.totalCells }} 个单元</span>
        </div>
        <div v-if="basemapRunDetail.postProcessStatus" class="run-meta">
          <el-tag :type="basemapRunDetail.postProcessStatus === 'completed' ? 'success' : basemapRunDetail.postProcessStatus === 'failed' ? 'danger' : 'warning'">
            后处理: {{ basemapRunDetail.postProcessStatus }}
          </el-tag>
          <el-tag v-if="basemapRunDetail.layerGroupStatus" :type="basemapRunDetail.layerGroupStatus === 'published' ? 'success' : 'danger'" style="margin-left:8px">
            Layer Group: {{ basemapRunDetail.layerGroupStatus }}
          </el-tag>
          <el-tag v-if="basemapRunDetail.wmts3857Status" :type="basemapRunDetail.wmts3857Status === 'registered' ? 'success' : 'danger'" style="margin-left:8px">
            WMTS 3857: {{ basemapRunDetail.wmts3857Status }}
          </el-tag>
          <el-tag v-if="basemapRunDetail.wmts3413Status" :type="basemapRunDetail.wmts3413Status === 'registered' ? 'success' : 'danger'" style="margin-left:8px">
            WMTS 3413: {{ basemapRunDetail.wmts3413Status }}
          </el-tag>
        </div>
        <div v-if="basemapRunDetail.warnings?.length" style="margin-top:12px">
          <el-alert
            v-for="(w, i) in basemapRunDetail.warnings"
            :key="i"
            :title="w"
            type="warning"
            :closable="false"
            style="margin-bottom:4px"
          />
        </div>
        <el-table :data="basemapRunDetail.items || []" stripe style="margin-top:12px">
          <el-table-column prop="cellName" label="海图单元" min-width="130" />
          <el-table-column label="更新链" width="120"><template #default="{ row }">.000 - .{{ String(row.updateCount).padStart(3, '0') }}</template></el-table-column>
          <el-table-column label="当前更新" width="100"><template #default="{ row }">.{{ String(row.currentUpdate).padStart(3, '0') }}</template></el-table-column>
          <el-table-column label="结果" width="120"><template #default="{ row }">{{ itemStageLabels[row.stage] || row.stage }}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }"><span :class="['status-pill', row.status]">{{ statusLabels[row.status] || row.status }}</span></template></el-table-column>
          <el-table-column label="失败原因" min-width="220"><template #default="{ row }"><span v-if="row.errorMessage" class="error-text">{{ row.errorMessage }}</span><span v-else>—</span></template></el-table-column>
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>
