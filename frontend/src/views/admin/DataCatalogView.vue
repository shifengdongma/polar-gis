<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import { Delete, Refresh, Search } from '@element-plus/icons-vue'
import { api, apiErrorMessage } from '../../api/client'
import type { Dataset, DatasetBulkDeleteResult, DatasetProjectReference, DatasetVersion, Paginated } from '../../types'

const datasets = ref<Dataset[]>([])
const total = ref(0)
const selectedDatasets = ref<Dataset[]>([])
const page = ref(1)
const pageSize = ref(15)
const datasetSearch = ref('')
const dialogVisible = ref(false)
const updateDialogVisible = ref(false)
const versionsVisible = ref(false)
const saving = ref(false)
const selectedFile = ref<File | null>(null)
const updateFile = ref<File | null>(null)
const activeDataset = ref<Dataset | null>(null)
const versions = ref<DatasetVersion[]>([])
const form = reactive({ code: '', name: '', dataType: 's57', description: '', sourceCrs: '' })

async function loadDatasets(targetPage = page.value) {
  const response = await api.get<Paginated<Dataset>>('/admin/datasets', {
    params: { page: targetPage, pageSize: pageSize.value, search: datasetSearch.value.trim() || undefined },
  })
  datasets.value = response.data.items
  total.value = response.data.total
  page.value = response.data.page
}

async function searchDatasets() {
  await loadDatasets(1)
}

async function resetDatasetSearch() {
  datasetSearch.value = ''
  await loadDatasets(1)
}

function selectFile(uploadFile: UploadFile) {
  selectedFile.value = uploadFile.raw || null
}

function selectUpdateFile(uploadFile: UploadFile) {
  updateFile.value = uploadFile.raw || null
}

function openUpdate(dataset: Dataset) {
  activeDataset.value = dataset
  updateFile.value = null
  updateDialogVisible.value = true
}

async function uploadUpdate() {
  if (!activeDataset.value || !updateFile.value) {
    ElMessage.warning('请选择连续更新文件')
    return
  }
  saving.value = true
  try {
    const body = new FormData()
    body.append('file', updateFile.value)
    const upload = await api.post<{ id: string }>('/admin/uploads', body, { timeout: 0 })
    await api.post(`/admin/datasets/${activeDataset.value.id}/s57-updates`, { uploadId: upload.data.id })
    ElMessage.success('连续更新已进入处理队列')
    updateDialogVisible.value = false
    await loadDatasets(1)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'S-57更新创建失败'))
  } finally {
    saving.value = false
  }
}

async function viewVersions(dataset: Dataset) {
  activeDataset.value = dataset
  try {
    versions.value = (await api.get<DatasetVersion[]>(`/admin/datasets/${dataset.id}/versions`)).data
    versionsVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '版本历史加载失败'))
  }
}

async function rollback(dataset: Dataset) {
  try {
    await ElMessageBox.confirm('将切换到上一有效版本，并同步替换项目中的对应图层。是否继续？', '确认回退', { type: 'warning' })
    await api.post(`/admin/datasets/${dataset.id}/rollback`)
    ElMessage.success('已回退到上一有效版本')
    await loadDatasets(1)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '版本回退失败'))
  }
}

async function deleteDataset(dataset: Dataset) {
  try {
    const references = (await api.get<DatasetProjectReference[]>(`/admin/datasets/${dataset.id}/references`)).data
    if (references.length) {
      await ElMessageBox.alert(
        `该数据集正在被以下项目引用，移除项目中的图层后才能删除：${references.map((project) => project.name).join('、')}`,
        '无法删除数据集',
        { type: 'warning', confirmButtonText: '知道了' },
      )
      return
    }
    await ElMessageBox.confirm(
      `将“${dataset.name}”移入已删除数据。地图与项目不会再显示它，原始文件和派生资源仍需在“数据清理”中永久删除。`,
      '删除数据集',
      { type: 'warning', confirmButtonText: '移入已删除数据', cancelButtonText: '取消' },
    )
    await api.delete(`/admin/datasets/${dataset.id}`)
    ElMessage.success('数据集已删除，可在“数据清理”中永久清理资源')
    await loadDatasets(page.value)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '数据集删除失败'))
  }
}

function handleDatasetSelection(rows: Dataset[]) {
  selectedDatasets.value = rows
}

async function bulkDeleteDatasets() {
  if (!selectedDatasets.value.length) return
  try {
    await ElMessageBox.confirm(
      `将选中的 ${selectedDatasets.value.length} 个数据集移入已删除数据。未被项目引用的数据集会立即移入“数据清理”，被引用的数据集会保留并列出原因。`,
      '批量删除数据集',
      { type: 'warning', confirmButtonText: '移入已删除数据', cancelButtonText: '取消' },
    )
    const result = (await api.post<DatasetBulkDeleteResult>('/admin/datasets/bulk-delete', {
      datasetIds: selectedDatasets.value.map((dataset) => dataset.id),
    })).data
    selectedDatasets.value = []
    await loadDatasets(page.value)
    if (result.deletedIds.length) {
      ElMessage.success(`已删除 ${result.deletedIds.length} 个数据集，可在“数据清理”中永久清理资源`)
    }
    if (result.blocked.length) {
      await ElMessageBox.alert(
        result.blocked.map((item) => `${item.datasetName}：${item.projects.map((project) => project.name).join('、')}`).join('；'),
        `${result.blocked.length} 个数据集仍被项目引用`,
        { type: 'warning', confirmButtonText: '知道了' },
      )
    }
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '批量删除数据集失败'))
  }
}

async function uploadAndCreate() {
  if (!selectedFile.value) {
    ElMessage.warning('请选择数据文件')
    return
  }
  saving.value = true
  try {
    const body = new FormData()
    body.append('file', selectedFile.value)
    const upload = await api.post<{ id: string }>('/admin/uploads', body, { timeout: 0 })
    await api.post('/admin/datasets', {
      ...form,
      sourceCrs: form.sourceCrs || null,
      uploadId: upload.data.id,
    })
    ElMessage.success('数据已上传，导入任务正在排队')
    dialogVisible.value = false
    selectedFile.value = null
    Object.assign(form, { code: '', name: '', dataType: 's57', description: '', sourceCrs: '' })
    await loadDatasets(1)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '数据上传失败'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadDatasets()
})
</script>

<template>
  <div class="page-stack">
    <section class="page-intro compact">
      <div><span class="eyebrow">DATA CATALOG</span><h2>数据目录</h2><p>统一管理可被多个项目复用的数据集。</p></div>
      <div class="header-actions"><el-button type="primary" @click="dialogVisible = true">上传数据</el-button></div>
    </section>
    <el-card shadow="never" class="data-card">
      <div class="catalog-table-head">
        <div><strong>数据集</strong><span>共 {{ total }} 个可复用数据集</span></div>
        <div class="catalog-toolbar">
          <el-input v-model="datasetSearch" class="dataset-search" clearable placeholder="搜索名称或代码" @keyup.enter="searchDatasets">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button type="primary" :icon="Search" @click="searchDatasets">查询</el-button>
          <el-tooltip content="重置查询并刷新数据" placement="top"><el-button :icon="Refresh" circle aria-label="重置查询并刷新数据" @click="resetDatasetSearch" /></el-tooltip>
          <el-button type="danger" plain :icon="Delete" :disabled="!selectedDatasets.length" @click="bulkDeleteDatasets">删除选中（{{ selectedDatasets.length }}）</el-button>
        </div>
      </div>
      <el-table :data="datasets" stripe @selection-change="handleDatasetSelection">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="name" label="数据集" min-width="220" />
        <el-table-column prop="code" label="代码" min-width="140" />
        <el-table-column label="类型" width="120"><template #default="{ row }"><el-tag effect="plain">{{ row.dataType.toUpperCase() }}</el-tag></template></el-table-column>
        <el-table-column prop="versionCount" label="版本数" width="90" />
        <el-table-column label="当前版本" width="130"><template #default="{ row }"><span :class="['status-pill', row.currentVersionId ? 'success' : 'warning']">{{ row.currentVersionId ? '有效' : '处理中' }}</span></template></el-table-column>
        <el-table-column label="更新时间" width="180"><template #default="{ row }">{{ new Date(row.updatedAt).toLocaleString('zh-CN') }}</template></el-table-column>
        <el-table-column label="操作" width="320" align="right"><template #default="{ row }"><el-button link @click="viewVersions(row)">版本历史</el-button><el-button v-if="row.dataType === 's57' && row.currentVersionId" link type="primary" @click="openUpdate(row)">连续更新</el-button><el-button v-if="row.dataType === 's57' && row.versionCount > 1" link type="warning" @click="rollback(row)">回退</el-button><el-button link type="danger" @click="deleteDataset(row)">删除</el-button></template></el-table-column>
      </el-table>
      <div v-if="total" class="table-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[10, 15, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="loadDatasets" @size-change="loadDatasets(1)" /></div>
    </el-card>
    <el-dialog v-model="dialogVisible" title="上传并创建数据集" width="620px">
      <el-alert title="原始文件将被保留，导入由独立Worker异步执行。" type="info" :closable="false" class="dialog-alert" />
      <el-form label-position="top">
        <el-form-item label="数据文件">
          <el-upload drag :auto-upload="false" :limit="1" :on-change="selectFile" :on-remove="() => (selectedFile = null)">
            <div class="upload-copy"><strong>拖拽文件到此处，或点击选择</strong><span>支持S-57、GeoTIFF、Shapefile ZIP、GeoJSON，最大5GB</span></div>
          </el-upload>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="数据集代码"><el-input v-model="form.code" /></el-form-item>
          <el-form-item label="数据类型"><el-select v-model="form.dataType" class="full-width"><el-option label="S-57海图" value="s57" /><el-option label="矢量数据" value="vector" /><el-option label="栅格数据" value="raster" /></el-select></el-form-item>
        </div>
        <el-form-item label="数据集名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="原始坐标系"><el-input v-model="form.sourceCrs" placeholder="可选，例如 EPSG:4326" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="uploadAndCreate">上传并导入</el-button></template>
    </el-dialog>
    <el-dialog v-model="updateDialogVisible" :title="`S-57连续更新 · ${activeDataset?.name || ''}`" width="560px">
      <el-alert title="只接受与当前海图单元匹配且更新号连续的 .001、.002 等文件；校验失败不会覆盖当前有效版本。" type="warning" :closable="false" class="dialog-alert" />
      <el-upload drag :auto-upload="false" :limit="1" :on-change="selectUpdateFile" :on-remove="() => (updateFile = null)"><div class="upload-copy"><strong>选择连续更新文件</strong><span>文件名和三位更新号将由服务端校验</span></div></el-upload>
      <template #footer><el-button @click="updateDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="uploadUpdate">上传并校验</el-button></template>
    </el-dialog>
    <el-drawer v-model="versionsVisible" :title="`${activeDataset?.name || ''} · 版本历史`" size="620px">
      <el-table :data="versions" stripe><el-table-column prop="versionNo" label="版本" width="80" /><el-table-column prop="sourceFormat" label="源格式/更新号" width="130" /><el-table-column prop="status" label="状态" width="110" /><el-table-column label="S-57单元" min-width="150"><template #default="{ row }">{{ row.metadataJson.cellName || '—' }}</template></el-table-column><el-table-column label="激活时间" width="180"><template #default="{ row }">{{ row.activatedAt ? new Date(row.activatedAt).toLocaleString('zh-CN') : '—' }}</template></el-table-column></el-table>
    </el-drawer>
  </div>
</template>
