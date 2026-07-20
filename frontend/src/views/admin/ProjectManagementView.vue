<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, apiErrorMessage } from '../../api/client'
import type {
  Paginated,
  Project,
  ProjectDatasetLayer,
} from '../../types'

type EditableDataset = ProjectDatasetLayer

const projects = ref<Project[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(15)
const dialogVisible = ref(false)
const layersDialogVisible = ref(false)
const saving = ref(false)
const layerSaving = ref(false)
const layerLoading = ref(false)
const layerConfigPage = ref(1)
const layerConfigPageSize = ref(15)
const layerConfigTotal = ref(0)
const activeProject = ref<Project | null>(null)
const editableDatasets = ref<EditableDataset[]>([])
const form = reactive({ code: '', name: '', description: '', defaultCrs: 'EPSG:3857' })
type DatasetDraft = Pick<EditableDataset, 'datasetId' | 'selected' | 'groupName' | 'sortOrder' | 'visibleByDefault' | 'opacity'>
const datasetDrafts = new Map<string, DatasetDraft>()

async function loadProjects(targetPage = page.value) {
  const response = await api.get<Paginated<Project>>('/admin/projects', { params: { page: targetPage, pageSize: pageSize.value } })
  projects.value = response.data.items
  total.value = response.data.total
  page.value = response.data.page
}

async function createProject() {
  saving.value = true
  try {
    await api.post('/admin/projects', form)
    ElMessage.success('项目创建成功')
    dialogVisible.value = false
    Object.assign(form, { code: '', name: '', description: '', defaultCrs: 'EPSG:3857' })
    await loadProjects(1)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '项目创建失败'))
  } finally {
    saving.value = false
  }
}

async function changeStatus(project: Project, action: 'publish' | 'unpublish' | 'archive') {
  try {
    await api.post(`/admin/projects/${project.id}/${action}`)
    ElMessage.success('项目状态已更新')
    await loadProjects()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '项目状态更新失败'))
  }
}

async function deleteProject(project: Project) {
  try {
    await ElMessageBox.confirm(
      `将删除项目“${project.name}”。项目图层配置会被移除，数据集本身不会删除。`,
      '删除项目',
      { type: 'warning', confirmButtonText: '删除项目', cancelButtonText: '取消' },
    )
    await api.delete(`/admin/projects/${project.id}`)
    ElMessage.success('项目已删除')
    await loadProjects(page.value)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '项目删除失败'))
  }
}

async function configureLayers(project: Project) {
  activeProject.value = project
  layersDialogVisible.value = true
  layerLoading.value = true
  try {
    datasetDrafts.clear()
    layerConfigPage.value = 1
    await loadLayerPage(1, false)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '项目图层配置加载失败'))
  } finally {
    layerLoading.value = false
  }
}

function cacheLayerPage() {
  editableDatasets.value.forEach((dataset) => datasetDrafts.set(dataset.datasetId, {
    datasetId: dataset.datasetId,
    selected: dataset.selected,
    groupName: dataset.groupName,
    sortOrder: dataset.sortOrder,
    visibleByDefault: dataset.visibleByDefault,
    opacity: dataset.opacity,
  }))
}

async function loadLayerPage(targetPage = layerConfigPage.value, cacheCurrent = true) {
  if (cacheCurrent) cacheLayerPage()
  layerLoading.value = true
  try {
    const response = await api.get<Paginated<ProjectDatasetLayer>>(
      `/admin/projects/${activeProject.value?.id}/dataset-layers`,
      { params: { page: targetPage, pageSize: layerConfigPageSize.value } },
    )
    layerConfigPage.value = response.data.page
    layerConfigTotal.value = response.data.total
    editableDatasets.value = response.data.items.map((dataset, index) => {
      const current = datasetDrafts.get(dataset.datasetId)
      return {
        ...dataset,
        selected: current?.selected ?? dataset.selected,
        groupName: current?.groupName ?? dataset.groupName,
        sortOrder: current?.sortOrder ?? (dataset.selected ? dataset.sortOrder : (layerConfigPage.value - 1) * layerConfigPageSize.value + index),
        visibleByDefault: current?.visibleByDefault ?? dataset.visibleByDefault,
        opacity: current?.opacity ?? dataset.opacity,
      }
    })
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '图层目录加载失败'))
  } finally {
    layerLoading.value = false
  }
}

async function saveLayers() {
  if (!activeProject.value) return
  layerSaving.value = true
  try {
    cacheLayerPage()
    const datasets = Array.from(datasetDrafts.values())
      .filter((dataset) => dataset.selected)
      .sort((left, right) => left.sortOrder - right.sortOrder)
      .map((dataset, index) => ({
        datasetId: dataset.datasetId,
        groupName: dataset.groupName || '默认分组',
        sortOrder: index,
        visibleByDefault: dataset.visibleByDefault,
        opacity: dataset.opacity,
      }))
    await api.put(`/admin/projects/${activeProject.value.id}/dataset-layers`, { datasets })
    ElMessage.success('项目数据集配置已保存')
    layersDialogVisible.value = false
    await loadProjects()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '项目图层配置保存失败'))
  } finally {
    layerSaving.value = false
  }
}

onMounted(loadProjects)
</script>

<template>
  <div class="page-stack">
    <section class="page-intro compact">
      <div><span class="eyebrow">PROJECT GOVERNANCE</span><h2>项目管理</h2><p>配置项目范围、投影和发布状态。</p></div>
      <el-button type="primary" @click="dialogVisible = true">创建项目</el-button>
    </section>
    <el-card shadow="never" class="data-card">
      <el-table :data="projects" stripe>
        <el-table-column prop="name" label="项目名称" min-width="220" />
        <el-table-column prop="code" label="代码" min-width="140" />
        <el-table-column prop="defaultCrs" label="默认投影" width="130" />
        <el-table-column prop="layerCount" label="数据集" width="90" />
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.status === 'published' ? 'success' : row.status === 'archived' ? 'info' : 'warning'">{{ { draft: '草稿', published: '已发布', archived: '已归档' }[row.status as Project['status']] }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="360" align="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="configureLayers(row)">配置数据集</el-button>
            <el-button v-if="row.status !== 'published'" link type="primary" @click="changeStatus(row, 'publish')">发布</el-button>
            <el-button v-else link @click="changeStatus(row, 'unpublish')">撤回</el-button>
            <el-button v-if="row.status !== 'archived'" link type="warning" @click="changeStatus(row, 'archive')">归档</el-button>
            <el-button link type="danger" @click="deleteProject(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="total" class="table-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[10, 15, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="loadProjects" @size-change="loadProjects(1)" /></div>
    </el-card>
    <el-dialog v-model="dialogVisible" title="创建项目" width="560px">
      <el-form label-position="top">
        <el-form-item label="项目代码"><el-input v-model="form.code" placeholder="例如 arctic-monitoring" /></el-form-item>
        <el-form-item label="项目名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="默认投影"><el-radio-group v-model="form.defaultCrs"><el-radio-button value="EPSG:3857">常规地图</el-radio-button><el-radio-button value="EPSG:3413">北极投影</el-radio-button></el-radio-group></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="createProject">创建</el-button></template>
    </el-dialog>
    <el-dialog v-model="layersDialogVisible" :title="`配置海图数据集 · ${activeProject?.name || ''}`" width="1040px" top="5vh">
      <el-alert title="每行对应一个数据集或 S-57 海图单元。保存时会自动包含其当前版本的内部对象图层，并保留既有 GeoServer 默认样式。" type="info" :closable="false" class="dialog-alert" />
      <el-table v-loading="layerLoading" :data="editableDatasets" height="62vh" stripe>
        <el-table-column label="启用" width="70"><template #default="{ row }"><el-checkbox v-model="row.selected" /></template></el-table-column>
        <el-table-column label="数据集" min-width="240"><template #default="{ row }"><strong>{{ row.datasetName }}</strong><div><small>{{ row.datasetCode }} · {{ row.dataType }} · 当前版本 {{ row.versionNo }}</small></div></template></el-table-column>
        <el-table-column prop="availableLayerCount" label="内部图层" width="100" />
        <el-table-column label="分组" width="150"><template #default="{ row }"><el-input v-model="row.groupName" :disabled="!row.selected" /></template></el-table-column>
        <el-table-column label="默认显示" width="100"><template #default="{ row }"><el-switch v-model="row.visibleByDefault" :disabled="!row.selected" /></template></el-table-column>
        <el-table-column label="透明度" width="180"><template #default="{ row }"><el-slider v-model="row.opacity" :disabled="!row.selected" :min="0" :max="1" :step="0.05" /></template></el-table-column>
        <el-table-column label="顺序" width="100"><template #default="{ row }"><el-input-number v-model="row.sortOrder" :disabled="!row.selected" :min="0" controls-position="right" /></template></el-table-column>
      </el-table>
      <div v-if="layerConfigTotal" class="table-pagination"><el-pagination v-model:current-page="layerConfigPage" v-model:page-size="layerConfigPageSize" :page-sizes="[10, 15, 20, 50, 100]" :total="layerConfigTotal" layout="total, sizes, prev, pager, next" @current-change="loadLayerPage" @size-change="loadLayerPage(1)" /></div>
      <template #footer><el-button @click="layersDialogVisible = false">取消</el-button><el-button type="primary" :loading="layerSaving" @click="saveLayers">保存配置</el-button></template>
    </el-dialog>
  </div>
</template>
