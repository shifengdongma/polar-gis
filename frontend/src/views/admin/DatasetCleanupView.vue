<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, apiErrorMessage } from '../../api/client'
import type { DatasetBulkPurgePreview, DatasetBulkPurgeResult, DatasetCleanupPreview } from '../../types'

const datasets = ref<DatasetCleanupPreview[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const purging = ref(false)
const selected = ref<DatasetCleanupPreview | null>(null)
const selectedDatasets = ref<DatasetCleanupPreview[]>([])
const bulkPreview = ref<DatasetBulkPurgePreview | null>(null)
const confirmation = ref('')
const isBulkPurge = computed(() => Boolean(bulkPreview.value))
const purgeItems = computed(() => bulkPreview.value?.datasets || (selected.value ? [selected.value] : []))
const confirmationText = computed(() => bulkPreview.value?.confirmationText || selected.value?.confirmationText || '')
const resourceCounts = computed(() => purgeItems.value.reduce((counts, dataset) => ({
  files: counts.files + dataset.sourceFiles.length,
  tables: counts.tables + dataset.derivedTables.length,
  services: counts.services + dataset.geoserverResources.length,
}), { files: 0, tables: 0, services: 0 }))

async function loadDeletedDatasets() {
  loading.value = true
  try {
    datasets.value = (await api.get<DatasetCleanupPreview[]>('/admin/datasets/deleted')).data
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '已删除数据加载失败'))
  } finally {
    loading.value = false
  }
}

async function openPurge(dataset: DatasetCleanupPreview) {
  try {
    selected.value = (await api.get<DatasetCleanupPreview>(`/admin/datasets/${dataset.datasetId}/cleanup-preview`)).data
    bulkPreview.value = null
    confirmation.value = ''
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '清理预览加载失败'))
  }
}

function handleSelection(rows: DatasetCleanupPreview[]) {
  selectedDatasets.value = rows
}

async function openBulkPurge() {
  if (!selectedDatasets.value.length) return
  try {
    bulkPreview.value = (await api.post<DatasetBulkPurgePreview>('/admin/datasets/bulk-purge-preview', {
      datasetIds: selectedDatasets.value.map((dataset) => dataset.datasetId),
    })).data
    selected.value = null
    confirmation.value = ''
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '批量清理预览加载失败'))
  }
}

async function purge() {
  if (!purgeItems.value.length || confirmation.value !== confirmationText.value) {
    ElMessage.warning('请输入页面显示的确认文本')
    return
  }
  purging.value = true
  try {
    if (bulkPreview.value) {
      const result = await api.post<DatasetBulkPurgeResult>('/admin/datasets/bulk-purge', {
        datasetIds: bulkPreview.value.datasets.map((dataset) => dataset.datasetId),
        confirmation: confirmation.value,
      })
      ElMessage.success(`已永久清理 ${result.data.purgedIds.length} 个数据集及其资源`)
    } else if (selected.value) {
      await api.post(`/admin/datasets/${selected.value.datasetId}/purge`, { confirmation: confirmation.value })
      ElMessage.success('数据集及其资源已永久清理')
    }
    dialogVisible.value = false
    selectedDatasets.value = []
    await loadDeletedDatasets()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '永久清理失败'))
  } finally {
    purging.value = false
  }
}

onMounted(loadDeletedDatasets)
</script>

<template>
  <div class="page-stack">
    <section class="page-intro compact">
      <div><span class="eyebrow">DATA RETENTION</span><h2>数据清理</h2><p>永久删除已删除数据集的原始文件、派生表和 GeoServer 资源。</p></div>
      <el-button :loading="loading" @click="loadDeletedDatasets">刷新</el-button>
    </section>
    <el-alert title="永久清理不可恢复，仅处理已从项目中移除且已软删除的数据集。" type="warning" :closable="false" />
    <el-card shadow="never" class="data-card">
      <div class="catalog-table-head"><div><strong>待清理数据</strong><span>共 {{ datasets.length }} 个数据集</span></div><el-button type="danger" plain :disabled="!selectedDatasets.length" @click="openBulkPurge">永久清理选中（{{ selectedDatasets.length }}）</el-button></div>
      <el-table v-loading="loading" :data="datasets" stripe empty-text="暂无可永久清理的数据" @selection-change="handleSelection">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="datasetName" label="数据集" min-width="220" />
        <el-table-column prop="datasetCode" label="代码" width="160" />
        <el-table-column label="资源" width="190"><template #default="{ row }">文件 {{ row.sourceFiles.length }} · 表 {{ row.derivedTables.length }} · 服务 {{ row.geoserverResources.length }}</template></el-table-column>
        <el-table-column label="删除时间" width="180"><template #default="{ row }">{{ new Date(row.deletedAt).toLocaleString('zh-CN') }}</template></el-table-column>
        <el-table-column label="操作" width="110" align="right"><template #default="{ row }"><el-button link type="danger" @click="openPurge(row)">永久清理</el-button></template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" :title="isBulkPurge ? `批量永久清理 · ${purgeItems.length} 个数据集` : `永久清理 · ${selected?.datasetName || ''}`" width="760px" destroy-on-close>
      <el-alert title="此操作将删除下列资源，无法恢复。确认前请核对资源清单。" type="error" :closable="false" class="dialog-alert" />
      <div v-if="purgeItems.length" class="cleanup-preview">
        <div class="cleanup-stat"><span>数据集</span><strong>{{ purgeItems.length }}</strong></div>
        <div class="cleanup-stat"><span>原始文件</span><strong>{{ resourceCounts.files }}</strong></div>
        <div class="cleanup-stat"><span>派生表</span><strong>{{ resourceCounts.tables }}</strong></div>
        <div class="cleanup-stat"><span>服务资源</span><strong>{{ resourceCounts.services }}</strong></div>
        <section v-for="dataset in purgeItems" :key="dataset.datasetId" class="cleanup-dataset">
          <strong>{{ dataset.datasetName }} <small>{{ dataset.datasetCode }}</small></strong>
          <div class="cleanup-list"><strong>原始文件</strong><span v-for="item in dataset.sourceFiles" :key="item">{{ item }}</span><span v-if="!dataset.sourceFiles.length">无</span></div>
          <div class="cleanup-list"><strong>PostGIS 派生表</strong><span v-for="item in dataset.derivedTables" :key="item">{{ item }}</span><span v-if="!dataset.derivedTables.length">无</span></div>
          <div class="cleanup-list"><strong>GeoServer 资源</strong><span v-for="item in dataset.geoserverResources" :key="item">{{ item }}</span><span v-if="!dataset.geoserverResources.length">无</span></div>
        </section>
        <el-form-item label="确认文本"><el-input v-model="confirmation" :placeholder="confirmationText" /></el-form-item>
      </div>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="danger" :loading="purging" @click="purge">永久清理</el-button></template>
    </el-dialog>
  </div>
</template>
