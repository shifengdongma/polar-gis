<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { api, apiErrorMessage } from '../../api/client'
import type { LayerRecord, Paginated } from '../../types'

interface BaseMapRecord {
  id: string
  name: string
  mapType: string
  urlTemplate: string
  crs: string
  attribution: string
  isOffline: boolean
  isEnabled: boolean
}

interface StyleRecord {
  id: string
  code: string
  name: string
  geoserverStyleName: string | null
  status: string
}

interface AuditRecord {
  id: string
  username: string | null
  action: string
  resourceType: string
  result: string
  requestId: string | null
  createdAt: string
}

const activeTab = ref('layers')
const layers = ref<LayerRecord[]>([])
const layerTotal = ref(0)
const layerPage = ref(1)
const layerPageSize = ref(15)
const baseMaps = ref<BaseMapRecord[]>([])
const styles = ref<StyleRecord[]>([])
const audits = ref<AuditRecord[]>([])
const auditTotal = ref(0)
const auditPage = ref(1)
const auditPageSize = ref(15)
const baseMapDialog = ref(false)
const styleDialog = ref(false)
const styleFile = ref<File | null>(null)
const queryDialog = ref(false)
const queryLayer = ref<LayerRecord | null>(null)
const queryRows = ref<Record<string, unknown>[]>([])
const queryLoading = ref(false)
const queryPage = ref(1)
const queryTotal = ref(0)
const queryField = ref('')
const queryValue = ref('')
const baseMapForm = reactive({ name: '', mapType: 'XYZ', urlTemplate: '', crs: 'EPSG:3857', attribution: '', isOffline: true, isEnabled: true })
const styleForm = reactive({ code: '', name: '' })

const queryColumns = computed(() => {
  const first = queryRows.value[0]
  return first ? Object.keys(first).filter((key) => key !== 'geometry') : queryLayer.value?.allowedFields || []
})

async function loadLayers(targetPage = layerPage.value) {
  const response = await api.get<Paginated<LayerRecord>>('/admin/layers', { params: { page: targetPage, pageSize: layerPageSize.value } })
  layers.value = response.data.items
  layerTotal.value = response.data.total
  layerPage.value = response.data.page
}

async function loadAudits(targetPage = auditPage.value) {
  const response = await api.get<Paginated<AuditRecord>>('/admin/audit-logs', { params: { page: targetPage, pageSize: auditPageSize.value } })
  audits.value = response.data.items
  auditTotal.value = response.data.total
  auditPage.value = response.data.page
}

async function loadAll() {
  const [baseMapResponse, styleResponse] = await Promise.all([
    api.get<BaseMapRecord[]>('/admin/base-maps'),
    api.get<StyleRecord[]>('/admin/styles'),
  ])
  baseMaps.value = baseMapResponse.data
  styles.value = styleResponse.data
  await Promise.all([loadLayers(), loadAudits()])
}

async function createBaseMap() {
  try {
    await api.post('/admin/base-maps', baseMapForm)
    ElMessage.success('底图配置已创建')
    baseMapDialog.value = false
    await loadAll()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
}

function selectStyleFile(uploadFile: UploadFile) {
  styleFile.value = uploadFile.raw || null
}

async function createStyle() {
  if (!styleFile.value) {
    ElMessage.warning('请选择SLD文件')
    return
  }
  try {
    const formData = new FormData()
    formData.append('file', styleFile.value)
    const upload = await api.post<{ id: string }>('/admin/uploads', formData)
    await api.post('/admin/styles', { ...styleForm, uploadId: upload.data.id })
    ElMessage.success('样式已校验并发布')
    styleDialog.value = false
    await loadAll()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '样式发布失败'))
  }
}

async function loadQueryRows() {
  if (!queryLayer.value) return
  queryLoading.value = true
  try {
    const filters = queryField.value && queryValue.value
      ? [{ field: queryField.value, operator: 'contains', value: queryValue.value }]
      : []
    const response = await api.post(`/layers/${queryLayer.value.id}/features/search`, {
      page: queryPage.value,
      pageSize: 15,
      filters,
    })
    queryRows.value = response.data.items
    queryTotal.value = response.data.total
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '图层查询失败'))
  } finally {
    queryLoading.value = false
  }
}

async function openQuery(layer: LayerRecord) {
  queryLayer.value = layer
  queryDialog.value = true
  queryPage.value = 1
  queryField.value = ''
  queryValue.value = ''
  queryRows.value = []
  await loadQueryRows()
}

async function exportLayer(format: 'csv' | 'geojson') {
  if (!queryLayer.value) return
  try {
    const filters = queryField.value && queryValue.value
      ? [{ field: queryField.value, operator: 'contains', value: queryValue.value }]
      : []
    const response = await api.post(
      `/layers/${queryLayer.value.id}/exports`,
      { format, filters, fields: queryLayer.value.allowedFields },
      { responseType: 'blob' },
    )
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = `${queryLayer.value.code}.${format === 'csv' ? 'csv' : 'geojson'}`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '图层导出失败'))
  }
}

async function exportLayerRecord(layer: LayerRecord) {
  queryLayer.value = layer
  queryField.value = ''
  queryValue.value = ''
  await exportLayer('csv')
}

onMounted(loadAll)
</script>

<template>
  <div class="page-stack">
    <section class="page-intro compact"><div><span class="eyebrow">MAP OPERATIONS</span><h2>图层与系统</h2><p>维护发布图层、SLD样式、离线底图和审计记录。</p></div></section>
    <el-card shadow="never" class="data-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="图层" name="layers">
          <el-table :data="layers" stripe>
            <el-table-column prop="name" label="图层名称" min-width="220" />
            <el-table-column prop="geometryType" label="类型" width="150" />
            <el-table-column prop="sourceCrs" label="坐标系" width="130" />
            <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="row.status === 'available' ? 'success' : row.status === 'publish_failed' ? 'danger' : 'warning'">{{ row.status }}</el-tag></template></el-table-column>
            <el-table-column label="能力" min-width="180"><template #default="{ row }"><el-button v-if="row.queryable" link type="primary" @click="openQuery(row)">查询</el-button><el-button v-if="row.exportable" link type="primary" @click="exportLayerRecord(row)">导出</el-button></template></el-table-column>
          </el-table>
          <div v-if="layerTotal" class="table-pagination"><el-pagination v-model:current-page="layerPage" v-model:page-size="layerPageSize" :page-sizes="[10, 15, 20, 50, 100]" :total="layerTotal" layout="total, sizes, prev, pager, next" @current-change="loadLayers" @size-change="loadLayers(1)" /></div>
        </el-tab-pane>
        <el-tab-pane label="SLD样式" name="styles">
          <div class="tab-toolbar"><el-button type="primary" @click="styleDialog = true">上传SLD</el-button></div>
          <el-table :data="styles" stripe><el-table-column prop="name" label="样式名称" /><el-table-column prop="code" label="代码" /><el-table-column prop="geoserverStyleName" label="GeoServer样式" /><el-table-column prop="status" label="状态" /></el-table>
        </el-tab-pane>
        <el-tab-pane label="底图" name="baseMaps">
          <div class="tab-toolbar"><el-button type="primary" @click="baseMapDialog = true">添加底图</el-button></div>
          <el-table :data="baseMaps" stripe><el-table-column prop="name" label="底图名称" /><el-table-column prop="mapType" label="类型" width="100" /><el-table-column prop="crs" label="坐标系" width="130" /><el-table-column label="来源" width="100"><template #default="{ row }">{{ row.isOffline ? '离线' : '在线' }}</template></el-table-column><el-table-column prop="urlTemplate" label="服务地址" show-overflow-tooltip /></el-table>
        </el-tab-pane>
        <el-tab-pane label="审计日志" name="audit">
          <el-table :data="audits" stripe><el-table-column prop="createdAt" label="时间" width="190"><template #default="{ row }">{{ new Date(row.createdAt).toLocaleString('zh-CN') }}</template></el-table-column><el-table-column prop="username" label="用户" width="140" /><el-table-column prop="action" label="动作" min-width="180" /><el-table-column prop="resourceType" label="资源" width="120" /><el-table-column prop="result" label="结果" width="100" /><el-table-column prop="requestId" label="请求ID" min-width="220" show-overflow-tooltip /></el-table>
          <div v-if="auditTotal" class="table-pagination"><el-pagination v-model:current-page="auditPage" v-model:page-size="auditPageSize" :page-sizes="[10, 15, 20, 50, 100]" :total="auditTotal" layout="total, sizes, prev, pager, next" @current-change="loadAudits" @size-change="loadAudits(1)" /></div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
    <el-dialog v-model="queryDialog" :title="`${queryLayer?.name || ''} · 数据查询与导出`" width="900px">
      <div class="tab-toolbar">
        <el-select v-model="queryField" clearable placeholder="筛选字段" style="width: 190px">
          <el-option v-for="field in queryLayer?.allowedFields || []" :key="field" :label="field" :value="field" />
        </el-select>
        <el-input v-model="queryValue" clearable placeholder="包含文本" style="width: 230px" @keyup.enter="queryPage = 1; loadQueryRows()" />
        <el-button type="primary" @click="queryPage = 1; loadQueryRows()">查询</el-button>
        <el-button v-if="queryLayer?.exportable" @click="exportLayer('csv')">导出 CSV</el-button>
        <el-button v-if="queryLayer?.exportable" @click="exportLayer('geojson')">导出 GeoJSON</el-button>
      </div>
      <el-table v-loading="queryLoading" :data="queryRows" height="480" stripe>
        <el-table-column v-for="column in queryColumns" :key="column" :prop="column" :label="column" min-width="150" show-overflow-tooltip />
      </el-table>
      <el-pagination v-model:current-page="queryPage" :page-size="15" :total="queryTotal" layout="prev, pager, next, total" @current-change="loadQueryRows" />
    </el-dialog>
    <el-dialog v-model="baseMapDialog" title="添加底图" width="560px">
      <el-form label-position="top"><div class="form-grid"><el-form-item label="名称"><el-input v-model="baseMapForm.name" /></el-form-item><el-form-item label="类型"><el-select v-model="baseMapForm.mapType" class="full-width"><el-option label="XYZ" value="XYZ" /><el-option label="WMTS" value="WMTS" /></el-select></el-form-item></div><el-form-item :label="baseMapForm.mapType === 'WMTS' ? 'GetCapabilities地址' : '瓦片模板地址'"><el-input v-model="baseMapForm.urlTemplate" :placeholder="baseMapForm.mapType === 'WMTS' ? 'https://host/wmts?SERVICE=WMTS&REQUEST=GetCapabilities' : 'https://host/tiles/{z}/{x}/{y}.png'" /></el-form-item><el-form-item label="坐标系"><el-input v-model="baseMapForm.crs" /></el-form-item><el-form-item label="版权说明"><el-input v-model="baseMapForm.attribution" /></el-form-item><el-checkbox v-model="baseMapForm.isOffline">生产离线底图</el-checkbox></el-form>
      <template #footer><el-button @click="baseMapDialog = false">取消</el-button><el-button type="primary" @click="createBaseMap">创建</el-button></template>
    </el-dialog>
    <el-dialog v-model="styleDialog" title="上传SLD样式" width="560px">
      <el-form label-position="top"><el-form-item label="样式代码"><el-input v-model="styleForm.code" /></el-form-item><el-form-item label="样式名称"><el-input v-model="styleForm.name" /></el-form-item><el-form-item label="SLD文件"><el-upload :auto-upload="false" :limit="1" accept=".sld" :on-change="selectStyleFile"><el-button>选择文件</el-button></el-upload></el-form-item></el-form>
      <template #footer><el-button @click="styleDialog = false">取消</el-button><el-button type="primary" @click="createStyle">校验并发布</el-button></template>
    </el-dialog>
  </div>
</template>
