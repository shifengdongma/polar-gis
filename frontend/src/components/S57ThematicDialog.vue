<script setup lang="ts">
/**
 * S-57 水深/危险物专题提取对话框。
 *
 * This dialog is adjacent to the existing waterway panel but does not alter
 * the waterway snapshot flow. Results are real filesystem exports; this UI
 * never renders a full SOUNDG layer, only the backend's small preview sample.
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { S57ThematicsApi } from '../composables/useS57Thematics'
import type {
  S57ThematicClass,
  S57ThematicExportManifest,
} from '../types/s57Thematics'

const props = defineProps<{
  modelValue: boolean
  thematics: S57ThematicsApi
}>()
const thematics = computed(() => props.thematics)
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'preview', collection: Record<string, unknown>, exportId: string): void
  (event: 'clear-preview'): void
}>()

const activeTab = ref<'extract' | 'exports'>('extract')
const catalog = computed(() => props.thematics.catalog.value)
const selectedClasses = computed(() => props.thematics.selectedClasses.value)
const selectedCells = computed(() => props.thematics.selectedCells.value)
const selectedDatasets = computed(() => props.thematics.selectedDatasets.value)
const viewportOnly = computed(() => props.thematics.viewportOnly.value)
const extractableClasses = computed(() =>
  props.thematics.classes.value.filter((item) => item.extractable),
)
const selectingAll = computed(
  () =>
    extractableClasses.value.length > 0 &&
    extractableClasses.value.every((item) => selectedClasses.value.has(item.code)),
)
const cellOptions = computed(() => catalog.value?.cells ?? [])
const datasetOptions = computed(() => catalog.value?.datasets ?? [])
const classes = computed(() => props.thematics.classes.value)
const exportsList = computed(() => props.thematics.exports.value)
const soundgDepthWarning = computed(
  () => catalog.value?.soundgDepth.depthPreserved === false,
)

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

function checked(code: string): boolean {
  return selectedClasses.value.has(code)
}

function onToggleClass(item: S57ThematicClass, value: string | number | boolean) {
  props.thematics.toggleClass(item.code, value === true)
}

function selectAllClasses() {
  for (const item of extractableClasses.value) {
    props.thematics.toggleClass(item.code, true)
  }
}

function clearClasses() {
  for (const item of classes.value) {
    props.thematics.toggleClass(item.code, false)
  }
}

function onViewportChange(value: string | number | boolean) {
  props.thematics.setViewportOnly(value === true)
}

function onCellChange(values: string[]) {
  const next = new Set(values)
  for (const cell of [...selectedCells.value]) {
    if (!next.has(cell)) props.thematics.toggleCell(cell, false)
  }
  for (const cell of next) {
    if (!selectedCells.value.has(cell)) props.thematics.toggleCell(cell, true)
  }
}

function onDatasetChange(values: string[]) {
  const next = new Set(values)
  for (const datasetId of [...selectedDatasets.value]) {
    if (!next.has(datasetId)) props.thematics.toggleDataset(datasetId, false)
  }
  for (const datasetId of next) {
    if (!selectedDatasets.value.has(datasetId)) props.thematics.toggleDataset(datasetId, true)
  }
}

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { hour12: false })
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

async function createExport() {
  const manifest = await props.thematics.createExport()
  if (!manifest) {
    if (props.thematics.createError.value) {
      ElMessage.error(props.thematics.createError.value)
    }
    return
  }
  const suffix = manifest.complete
    ? `已保存 ${manifest.featureCount} 个要素`
    : `已保存 ${manifest.featureCount} 个要素（成果标记为截断/不完整）`
  ElMessage.success(suffix)
  activeTab.value = 'exports'
  void props.thematics.loadExports()
}

async function download(manifest: S57ThematicExportManifest) {
  await props.thematics.downloadExport(manifest)
  if (props.thematics.downloadError.value) {
    ElMessage.error(props.thematics.downloadError.value)
  }
}

async function preview(manifest: S57ThematicExportManifest) {
  const collection = await props.thematics.loadPreview(manifest)
  if (!collection) {
    if (props.thematics.previewError.value) {
      ElMessage.error(props.thematics.previewError.value)
    }
    return
  }
  emit('preview', collection, manifest.exportId)
  ElMessage.success('已在地图显示该成果的样例预览（非完整成果）')
}

function onOpen() {
  if (!props.thematics.catalog.value) void props.thematics.loadCatalog()
  void props.thematics.loadExports()
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="S-57 专题数据提取（水深 / 危险物）"
    width="780px"
    class="s57-thematic-dialog"
    append-to-body
    @open="onOpen"
  >
    <div class="thematic-disclaimer">
      成果是航线规划的<b>原始候选数据</b>，不是经过安全论证的通航网络；DRVAL1/DRVAL2/VALDCO/VALSOU 不等于保证安全水深。
    </div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="提取" name="extract">
        <div v-if="thematics.catalogLoading.value" class="thematic-empty">正在读取项目已导入的 S-57 对象类…</div>
        <div v-else-if="thematics.catalogError.value" class="thematic-error">
          <span>{{ thematics.catalogError.value }}</span>
          <el-button size="small" text @click="thematics.loadCatalog()">重试</el-button>
        </div>
        <div v-else-if="!thematics.hasCatalogData.value" class="thematic-empty">
          当前项目没有可提取的 S-57 空间图层
        </div>
        <template v-else>
          <div v-if="soundgDepthWarning" class="thematic-warning">
            部分 SOUNDG 几何为 2D，深度可能未保留；导出会在 manifest 中标记，不会用 DEPARE 范围替代测深值。
          </div>

          <div class="thematic-section-title">来源与范围</div>
          <div class="thematic-source-row">
            <el-radio-group :model-value="viewportOnly ? 'viewport' : 'project'" @change="(value: string | number | boolean) => onViewportChange(value === 'viewport')">
              <el-radio-button label="project">项目全部有效数据</el-radio-button>
              <el-radio-button label="viewport">当前视口</el-radio-button>
            </el-radio-group>
            <span class="thematic-source-note">{{ viewportOnly ? '仅提取当前地图范围' : '提取当前项目已关联的当前版本全部数据' }}</span>
          </div>
          <div class="thematic-select-row">
            <el-select
              :model-value="[...selectedCells]"
              multiple
              collapse-tags
              clearable
              filterable
              size="small"
              placeholder="全部 Cell（可选具体海图单元）"
              @change="onCellChange"
            >
              <el-option
                v-for="cell in cellOptions"
                :key="cell.sourceCell"
                :label="`${cell.sourceCell} · ${cell.featureCount} 要素`"
                :value="cell.sourceCell"
              />
            </el-select>
            <el-select
              :model-value="[...selectedDatasets]"
              multiple
              collapse-tags
              clearable
              filterable
              size="small"
              placeholder="全部数据集（可选具体数据集）"
              @change="onDatasetChange"
            >
              <el-option
                v-for="dataset in datasetOptions"
                :key="dataset.datasetId"
                :label="`${dataset.datasetName} · v${dataset.versionNo}`"
                :value="dataset.datasetId"
              />
            </el-select>
          </div>

          <div class="thematic-section-title">
            对象类
            <el-button size="small" text @click="selectingAll ? clearClasses() : selectAllClasses()">
              {{ selectingAll ? '取消全选' : '全选' }}
            </el-button>
          </div>
          <div v-for="category in catalog?.categories ?? []" :key="category.code" class="thematic-category">
            <div class="thematic-category-head">{{ category.nameZh }}</div>
            <div class="thematic-class-grid">
              <el-checkbox
                v-for="item in category.classes"
                :key="item.code"
                :model-value="checked(item.code)"
                :disabled="!item.extractable"
                class="thematic-class-item"
                @change="(value: string | number | boolean) => onToggleClass(item, value)"
              >
                <span>{{ item.nameZh }}</span>
                <code>{{ item.code }}</code>
                <b>{{ item.count }}</b>
                <em v-if="!item.layerCount">未导入</em>
                <em v-else-if="!item.extractable">不可提取</em>
              </el-checkbox>
            </div>
            <div
              v-for="item in category.classes.filter((entry) => entry.layerCount > 0)"
              :key="`${item.code}-desc`"
              class="thematic-class-desc"
            >
              {{ item.description }}
            </div>
          </div>

          <div class="thematic-summary">
            <span>源图层 <b>{{ thematics.selectedLayerCount.value }}</b></span>
            <span>可提取层 <b>{{ thematics.selectedExtractableLayerCount.value }}</b></span>
            <span>要素条数 <b>{{ thematics.selectedFeatureCount.value }}</b></span>
            <span v-if="!thematics.selectedCountComplete.value">部分数量未知</span>
            <span class="thematic-summary-note">SOUNDG 的“条数”是要素数，一条可含多个测深点。</span>
          </div>

          <div class="thematic-form-row">
            <label>成果名称</label>
            <el-input v-model="thematics.exportName.value" size="small" maxlength="120" placeholder="可选，默认按时间命名" />
          </div>
          <div class="thematic-form-row">
            <label>单类上限</label>
            <el-input-number v-model="thematics.maxFeaturesPerClass.value" :min="1" :max="1000000" :step="10000" size="small" />
            <span class="thematic-source-note">留空使用服务端上限；达到上限会标记截断。</span>
          </div>
          <div v-if="thematics.createError.value" class="thematic-error">{{ thematics.createError.value }}</div>
          <div class="thematic-actions">
            <el-button type="primary" :loading="thematics.creating.value" @click="createExport">提取并保存</el-button>
            <el-button text @click="emit('clear-preview')">清除地图样例</el-button>
          </div>

          <div class="thematic-semantics">
            <div v-for="item in catalog?.semantics ?? []" :key="item">{{ item }}</div>
            <div v-for="item in catalog?.warnings ?? []" :key="item">{{ item }}</div>
          </div>
        </template>
      </el-tab-pane>

      <el-tab-pane label="已保存成果" name="exports">
        <div v-if="thematics.exportsLoading.value" class="thematic-empty">正在读取已保存成果…</div>
        <div v-else-if="thematics.exportsError.value" class="thematic-error">
          <span>{{ thematics.exportsError.value }}</span>
          <el-button size="small" text @click="thematics.loadExports()">重试</el-button>
        </div>
        <div v-else-if="exportsList.length === 0" class="thematic-empty">尚未保存 S-57 专题成果</div>
        <div v-else class="thematic-export-list">
          <article v-for="manifest in exportsList" :key="manifest.exportId" class="thematic-export-item">
            <div class="thematic-export-head">
              <strong>{{ manifest.name }}</strong>
              <div class="thematic-tags">
                <el-tag v-if="manifest.stale" size="small" type="warning">基于旧版数据</el-tag>
                <el-tag v-if="manifest.complete" size="small" type="success">完整</el-tag>
                <el-tag v-else size="small" type="danger">截断/不完整</el-tag>
              </div>
            </div>
            <div class="thematic-export-meta">
              <span>{{ formatTime(manifest.createdAt) }}</span>
              <span>{{ manifest.featureCount }} 个要素</span>
              <span>{{ manifest.files.length }} 个文件 · {{ formatBytes(manifest.files.reduce((sum, item) => sum + item.bytes, 0)) }}</span>
            </div>
            <div class="thematic-export-meta">
              <span>对象类：{{ manifest.objectClasses.map((item) => item.code).join('、') || '—' }}</span>
              <span>Cell：{{ manifest.sourceCells.join('、') || '—' }}</span>
            </div>
            <div v-if="manifest.truncationReasons.length" class="thematic-export-warning">
              截断原因：{{ manifest.truncationReasons.join('、') }}
            </div>
            <div class="thematic-export-actions">
              <el-button size="small" text :loading="thematics.downloading.value" @click="download(manifest)">
                {{ manifest.files.length > 1 ? '下载 ZIP' : '下载 GeoJSON' }}
              </el-button>
              <el-button size="small" text :loading="thematics.previewLoading.value" :disabled="!manifest.preview" @click="preview(manifest)">
                在图上预览样例
              </el-button>
            </div>
            <details class="thematic-manifest-details">
              <summary>查看 manifest / 警告</summary>
              <div>schema：{{ manifest.schemaVersion }} · CRS：{{ manifest.crs }}</div>
              <div v-for="warning in manifest.warnings" :key="warning">{{ warning }}</div>
              <div v-for="item in manifest.objectClasses" :key="item.code">
                {{ item.nameZh }}（{{ item.code }}）：{{ item.featureCount }} 条{{ item.truncated ? '，已截断' : '' }}
              </div>
            </details>
          </article>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-dialog>
</template>
