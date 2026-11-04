<script setup lang="ts">
/**
 * S-57 航道专题面板（左侧图层目录内的独立专题区块）。
 *
 * 只驱动 useS57Waterways，不直接操作 OpenLayers；要素名称缺失时显示
 * “未命名航道要素”，绝不生成假名称。辅助要素与航道主类别分开展示。
 */
import { computed } from 'vue'
import { Close, Location, Search } from '@element-plus/icons-vue'
import type { S57WaterwaysApi } from '../composables/useS57Waterways'
import type {
  S57WaterwayClass,
  S57WaterwaySearchItem,
  S57WaterwayProperty,
} from '../types/s57Waterways'
import { waterwayDisplayName, waterwaySourceLabel } from '../utils/mapS57Waterway'

const props = defineProps<{ waterways: S57WaterwaysApi }>()
const emit = defineEmits<{ (event: 'close'): void }>()

const catalog = computed(() => props.waterways.catalog.value)
const classes = computed(() => catalog.value?.classes ?? [])
const primaryGroups = computed(() => {
  const groups = new Map<string, { name: string; items: S57WaterwayClass[] }>()
  for (const item of classes.value.filter((entry) => !entry.auxiliary)) {
    const group = groups.get(item.group) ?? { name: item.groupNameZh, items: [] }
    group.items.push(item)
    groups.set(item.group, group)
  }
  return [...groups.values()]
})
const auxiliaryClasses = computed(() => classes.value.filter((entry) => entry.auxiliary))
const results = computed(() => props.waterways.results.value)
const total = computed(() => props.waterways.total.value)
const pageSize = computed(() => props.waterways.pageSize.value)
const detail = computed(() => props.waterways.detail.value)
const detailVisible = computed(
  () => Boolean(detail.value) || props.waterways.detailLoading.value,
)
const selectedClasses = computed(() => props.waterways.selectedClasses.value)
const includeAuxiliary = computed(() => props.waterways.includeAuxiliary.value)
const viewportOnly = computed(() => props.waterways.viewportOnly.value)
const selectionMode = computed(() => props.waterways.selectionMode.value)
const catalogLoading = computed(() => props.waterways.catalogLoading.value)
const catalogError = computed(() => props.waterways.catalogError.value)
const searching = computed(() => props.waterways.searching.value)
const searchError = computed(() => props.waterways.searchError.value)
const detailLoading = computed(() => props.waterways.detailLoading.value)
const detailError = computed(() => props.waterways.detailError.value)
const warnings = computed(() => props.waterways.warnings.value)
const hasWaterwayData = computed(() => props.waterways.hasWaterwayData.value)

function checked(code: string): boolean {
  return selectedClasses.value.has(code)
}

function onToggleClass(code: string, value: string | number | boolean) {
  props.waterways.toggleClass(code, value === true)
}

function onAuxiliaryChange(value: string | number | boolean) {
  props.waterways.setIncludeAuxiliary(value === true)
}

function onSearch() {
  void props.waterways.runSearch(1)
}

function onPageChange(page: number) {
  props.waterways.setPage(page)
}

function shown(item: S57WaterwaySearchItem): boolean {
  return props.waterways.isItemShown(item.id)
}

function toggleShown(item: S57WaterwaySearchItem) {
  props.waterways.showItem(item, !shown(item))
}

function locate(item: S57WaterwaySearchItem) {
  props.waterways.locate(item)
}

function displayRaw(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未提供'
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

function propertyValue(property: S57WaterwayProperty): string {
  return property.provided ? displayRaw(property.raw) : '未提供'
}

function closePanel() {
  emit('close')
}
</script>

<template>
  <section class="waterway-panel">
    <div class="waterway-panel-heading">
      <div>
        <span class="waterway-panel-title">S-57 航道专题</span>
        <span class="waterway-panel-badge">真实海图要素</span>
      </div>
      <button class="waterway-panel-close" type="button" aria-label="关闭航道专题" @click="closePanel">
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <div v-if="catalogLoading" class="waterway-panel-empty">正在读取项目航道图层…</div>
    <div v-else-if="catalogError" class="waterway-panel-error">
      <span>{{ catalogError }}</span>
      <el-button size="small" text @click="waterways.loadCatalog()">重试</el-button>
    </div>
    <div v-else-if="!hasWaterwayData" class="waterway-panel-empty">
      当前数据未检索到航道专题要素
    </div>

    <template v-else>
      <div class="waterway-search-box">
        <el-input
          v-model="waterways.keyword.value"
          :prefix-icon="Search"
          clearable
          size="small"
          placeholder="搜索航道名称或属性（OBJNAM/NOBJNM/INFORM）"
          @keyup.enter="onSearch"
        />
        <div class="waterway-search-row">
          <el-checkbox :model-value="viewportOnly" size="small" @change="(value: string | number | boolean) => (waterways.viewportOnly.value = value === true)">
            当前视口
          </el-checkbox>
          <el-checkbox :model-value="selectionMode" size="small" @change="(value: string | number | boolean) => waterways.setSelectionMode(value === true)">
            地图点选
          </el-checkbox>
          <el-button size="small" type="primary" :disabled="!waterways.canSearch.value" :loading="searching" @click="onSearch">搜索</el-button>
          <el-button size="small" text @click="waterways.clearFilters()">清空</el-button>
        </div>
      </div>

      <div class="waterway-class-groups">
        <div v-for="group in primaryGroups" :key="group.name" class="waterway-class-group">
          <div class="waterway-class-group-title">{{ group.name }}</div>
          <el-checkbox
            v-for="item in group.items"
            :key="item.code"
            :model-value="checked(item.code)"
            :disabled="item.layerCount === 0"
            size="small"
            class="waterway-class-checkbox"
            @change="(value: string | number | boolean) => onToggleClass(item.code, value)"
          >
            <span>{{ item.nameZh }}</span>
            <span class="waterway-class-code">{{ item.code }}</span>
            <span class="waterway-class-count">{{ item.count }}</span>
          </el-checkbox>
        </div>
      </div>

      <div v-if="auxiliaryClasses.length > 0" class="waterway-auxiliary">
        <div class="waterway-auxiliary-head">
          <span>相关辅助要素（不视为航道）</span>
          <el-switch :model-value="includeAuxiliary" size="small" @change="onAuxiliaryChange" />
        </div>
        <div v-if="includeAuxiliary" class="waterway-class-group">
          <el-checkbox
            v-for="item in auxiliaryClasses"
            :key="item.code"
            :model-value="checked(item.code)"
            :disabled="item.layerCount === 0"
            size="small"
            class="waterway-class-checkbox"
            @change="(value: string | number | boolean) => onToggleClass(item.code, value)"
          >
            <span>{{ item.nameZh }}</span>
            <span class="waterway-class-code">{{ item.code }}</span>
            <span class="waterway-class-count">{{ item.count }}</span>
          </el-checkbox>
        </div>
      </div>

      <div v-if="searchError" class="waterway-panel-error">
        <span>{{ searchError }}</span>
      </div>
      <div v-if="warnings.length > 0" class="waterway-warnings">
        <div v-for="warning in warnings" :key="warning">{{ warning }}</div>
      </div>

      <div class="waterway-results-head">
        <span>搜索结果 {{ total }} 条</span>
        <el-button size="small" text :disabled="waterways.displayedCount.value === 0" @click="waterways.clearDisplay()">
          清除显示（{{ waterways.displayedCount.value }}）
        </el-button>
      </div>

      <div v-if="searching && results.length === 0" class="waterway-panel-empty">正在查询真实 S-57 要素…</div>
      <div v-else-if="results.length === 0" class="waterway-panel-empty">
        {{ catalog && catalog.total === 0 ? '当前数据未检索到航道专题要素' : '没有匹配结果' }}
      </div>
      <div v-else class="waterway-result-list">
        <article v-for="item in results" :key="item.id" class="waterway-result-item">
          <div class="waterway-result-main">
            <strong>{{ waterwayDisplayName(item) }}</strong>
            <div class="waterway-result-meta">
              <span>{{ item.objectNameZh }} · {{ item.objectClass }}</span>
              <span>{{ waterwaySourceLabel(item) }}</span>
              <span v-if="item.auxiliary" class="waterway-aux-tag">辅助要素</span>
            </div>
            <div v-if="item.inform" class="waterway-result-inform">{{ item.inform }}</div>
          </div>
          <div class="waterway-result-actions">
            <el-button size="small" text :icon="Location" :disabled="!item.geometry" @click="locate(item)">定位</el-button>
            <el-button size="small" text @click="waterways.openDetail(item.id)">详情</el-button>
            <el-button size="small" text :disabled="!item.geometry" @click="toggleShown(item)">
              {{ shown(item) ? '隐藏' : '显示' }}
            </el-button>
          </div>
        </article>
      </div>

      <el-pagination
        v-if="total > pageSize"
        class="waterway-pagination"
        small
        layout="prev, pager, next"
        :current-page="waterways.page.value"
        :page-size="pageSize"
        :total="total"
        @current-change="onPageChange"
      />
    </template>

    <el-drawer
      :model-value="detailVisible"
      title="航道要素详情"
      size="420px"
      class="waterway-detail-drawer"
      @close="waterways.closeDetail()"
    >
      <div v-if="detailLoading" class="waterway-panel-empty">正在加载要素属性…</div>
      <div v-else-if="detailError" class="waterway-panel-error">{{ detailError }}</div>
      <template v-else-if="detail">
        <el-descriptions :column="1" border size="small" class="waterway-detail-desc">
          <el-descriptions-item label="名称">{{ waterwayDisplayName(detail) }}</el-descriptions-item>
          <el-descriptions-item label="对象类别">{{ detail.objectNameZh }} · {{ detail.objectClass }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ waterwaySourceLabel(detail) }}</el-descriptions-item>
          <el-descriptions-item label="数据集">{{ detail.datasetName }} · v{{ detail.versionNo }}</el-descriptions-item>
          <el-descriptions-item label="几何类型">{{ detail.geometryType || '未提供' }}</el-descriptions-item>
          <el-descriptions-item label="空间范围">{{ detail.bbox ? detail.bbox.map((value) => value.toFixed(5)).join(', ') : '未提供' }}</el-descriptions-item>
          <el-descriptions-item label="导入更新时间">{{ detail.updatedAt || '未提供' }}</el-descriptions-item>
        </el-descriptions>
        <div class="waterway-detail-section-title">S-57 原始属性 / 中文解释</div>
        <el-table :data="detail.properties" size="small" class="waterway-detail-table" max-height="420">
          <el-table-column prop="field" label="字段" width="92" />
          <el-table-column prop="labelZh" label="中文名" width="150" />
          <el-table-column label="原始值" min-width="120">
            <template #default="{ row }">{{ propertyValue(row) }}</template>
          </el-table-column>
          <el-table-column label="说明" min-width="180">
            <template #default="{ row }">{{ row.description || (row.provided ? '原始 S-57 属性' : '未提供') }}</template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>
  </section>
</template>
