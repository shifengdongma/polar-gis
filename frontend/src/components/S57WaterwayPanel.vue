<script setup lang="ts">
/**
 * S-57 航道专题面板（左侧图层目录内的独立专题区块）。
 *
 * 只驱动 useS57Waterways，不直接操作 OpenLayers；要素名称缺失时显示
 * “未命名航道要素”，绝不生成假名称。辅助要素与航道主类别分开展示。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Location, Search } from '@element-plus/icons-vue'
import type { S57WaterwaysApi } from '../composables/useS57Waterways'
import type {
  S57WaterwayClass,
  S57WaterwaySearchItem,
  S57WaterwayProperty,
  S57WaterwaySnapshotManifest,
  WaterwayGroup,
} from '../types/s57Waterways'
import {
  waterwayDisplayName,
  waterwayGroupColor,
  waterwaySourceLabel,
} from '../utils/mapS57Waterway'
import { measurePolylineLength } from '../utils/geodesicDistance'

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
const catalogLoading = computed(() => props.waterways.catalogLoading.value)
const catalogError = computed(() => props.waterways.catalogError.value)
const searching = computed(() => props.waterways.searching.value)
const searchError = computed(() => props.waterways.searchError.value)
const detailLoading = computed(() => props.waterways.detailLoading.value)
const detailError = computed(() => props.waterways.detailError.value)
const warnings = computed(() => props.waterways.warnings.value)
const hasWaterwayData = computed(() => props.waterways.hasWaterwayData.value)
const snapshots = computed(() => props.waterways.snapshots.value)
const snapshotsLoading = computed(() => props.waterways.snapshotsLoading.value)
const snapshotsError = computed(() => props.waterways.snapshotsError.value)
const snapshotCreating = computed(() => props.waterways.snapshotCreating.value)
const snapshotError = computed(() => props.waterways.snapshotError.value)
const snapshotDialogVisible = ref(false)
const snapshotListVisible = ref(false)
const helpVisible = ref(false)
const snapshotName = ref('')
const snapshotMaxFeatures = ref(20000)
const snapshotClasses = computed(() =>
  classes.value.filter((item) => selectedClasses.value.has(item.code)),
)
const snapshotClassSummary = computed(
  () =>
    snapshotClasses.value
      .map((item) => `${item.nameZh} ${item.code}`)
      .join('、') || '未选择',
)
const overviewLoading = computed(() => props.waterways.overviewLoading.value)
const overviewError = computed(() => props.waterways.overviewError.value)
const overviewCount = computed(() => props.waterways.overviewCount.value)
const overviewWarnings = computed(() => props.waterways.overviewWarnings.value)
const overviewMatchedTotal = computed(() => props.waterways.overviewMatchedTotal.value)
const overviewHasMore = computed(() => props.waterways.overviewHasMore.value)
const overviewCountComplete = computed(() => props.waterways.overviewCountComplete.value)
const visibleGroups = computed(() => props.waterways.visibleGroups.value)
const visibleCount = computed(() => props.waterways.visibleCount.value)
const displayBudget = computed(() => props.waterways.displayBudget)
const diagnostics = computed(() => props.waterways.diagnostics.value)
const diagnosticsLoading = computed(() => props.waterways.diagnosticsLoading.value)
const diagnosticsError = computed(() => props.waterways.diagnosticsError.value)
const sourceCellFilter = computed(() => props.waterways.sourceCellFilter.value)
const diagnosticsVisible = ref(false)
const stats = computed(() => {
  const data = catalog.value
  const loaded = props.waterways.displayedCount.value
  const matched = overviewMatchedTotal.value
  return {
    cells: data?.linkedCellCount ?? 0,
    layers: data?.searchableLayerCount ?? 0,
    matched,
    loaded,
    visible: visibleCount.value,
    missing: matched === null ? null : Math.max(0, matched - loaded),
    countComplete: (data?.countComplete ?? true) && overviewCountComplete.value,
  }
})
const coverageGap = computed(() => diagnostics.value?.northeastPassage.hasGap ?? false)
const missingRegionNames = computed(
  () =>
    diagnostics.value?.northeastPassage.missingRegions
      .map((item) => item.nameZh)
      .join('、') ?? '',
)
const groupSummary = computed(() => {
  const entries = new Map<
    string,
    { key: string; label: string; count: number; color: string }
  >()
  for (const item of classes.value) {
    if (item.layerCount === 0 && item.count === 0) continue
    const key = item.auxiliary ? 'auxiliary' : item.group
    const entry = entries.get(key) ?? {
      key,
      label: item.auxiliary ? '相关辅助要素' : item.groupNameZh,
      count: 0,
      color: waterwayGroupColor(item.group, item.auxiliary),
    }
    entry.count += item.count
    entries.set(key, entry)
  }
  return [...entries.values()]
})
const overviewMessage = computed(() => {
  if (overviewLoading.value) return '正在从服务器提取选中类别的航道要素…'
  if (overviewError.value) return overviewError.value
  if (overviewCount.value > 0) {
    const matched =
      overviewMatchedTotal.value === null
        ? '匹配总数未知'
        : `匹配 ${overviewMatchedTotal.value} 条`
    const more = overviewHasMore.value ? '，可继续加载' : ''
    return `地图已加载 ${overviewCount.value} 条（${matched}${more}）`
  }
  return ''
})

const REGION_STATUS_LABELS: Record<string, string> = {
  imported_enc_coverage: '已导入相关 ENC（范围近似）',
  only_basemap_or_auxiliary: '只有底图/辅助对象',
  no_waterway_objects: '无航道对象',
  no_enc_imported: '未导入相应 ENC',
  unknown: '覆盖未知',
}

function regionStatusLabel(status: string): string {
  return REGION_STATUS_LABELS[status] ?? status
}

function regionStatusType(
  status: string,
): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'imported_enc_coverage') return 'success'
  if (status === 'no_enc_imported' || status === 'unknown') return 'danger'
  return 'warning'
}

function onViewportOnlyChange(value: string | number | boolean) {
  props.waterways.setViewportOnly(value === true)
}

function onGroupChange(group: string, value: string | number | boolean) {
  props.waterways.setVisibleGroup(group as WaterwayGroup, value === true)
}

function groupVisible(group: string): boolean {
  return visibleGroups.value.has(group as WaterwayGroup)
}

async function loadMoreOnMap() {
  if (props.waterways.displayedCount.value >= displayBudget.value) {
    ElMessage.warning(
      `已达到地图叠加预算 ${displayBudget.value} 条，请缩小视口或减少类别`,
    )
    return
  }
  const before = props.waterways.displayedCount.value
  const ok = await props.waterways.loadMoreOverview()
  if (!ok) {
    if (props.waterways.overviewError.value) {
      ElMessage.warning(props.waterways.overviewError.value)
    }
    return
  }
  const added = props.waterways.displayedCount.value - before
  if (added > 0) ElMessage.success(`已追加 ${added} 条航道要素`)
  else ElMessage.info('没有更多可加载的航道要素')
}

function openDiagnostics() {
  diagnosticsVisible.value = true
  if (!diagnostics.value && !diagnosticsLoading.value) {
    void props.waterways.loadDiagnostics()
  }
}

function toPoints(value: unknown): Array<[number, number]> {
  if (!Array.isArray(value)) return []
  return value
    .filter(
      (point): point is [number, number] =>
        Array.isArray(point) &&
        point.length >= 2 &&
        Number.isFinite(point[0]) &&
        Number.isFinite(point[1]),
    )
    .map((point) => [Number(point[0]), Number(point[1])])
}

function geometryLengthKm(geometry: Record<string, unknown> | null): number | null {
  if (!geometry) return null
  const type = String(geometry.type || '')
  const coordinates = geometry.coordinates
  const lines: Array<Array<[number, number]>> = []
  if (type === 'LineString') {
    lines.push(toPoints(coordinates))
  } else if (type === 'MultiLineString' && Array.isArray(coordinates)) {
    for (const line of coordinates) lines.push(toPoints(line))
  } else {
    return null
  }
  let meters = 0
  let hasLength = false
  for (const line of lines) {
    if (line.length < 2) continue
    const value = measurePolylineLength(line)
    if (Number.isFinite(value) && value > 0) {
      meters += value
      hasLength = true
    }
  }
  return hasLength ? meters / 1000 : null
}

const detailLengthKm = computed(() =>
  detail.value ? geometryLengthKm(detail.value.geometry) : null,
)

function bboxText(bbox: number[] | null): string {
  if (!bbox || bbox.length < 4) return '未提供'
  return bbox.map((value) => value.toFixed(5)).join(', ')
}

function detailCenter(): [number, number] | null {
  const bbox = detail.value?.bbox
  if (!bbox || bbox.length < 4) return null
  return [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]
}

async function copyDetailInfo() {
  const current = detail.value
  if (!current) return
  const center = detailCenter()
  const lines = [
    `名称：${waterwayDisplayName(current)}`,
    `对象类别：${current.objectNameZh} · ${current.objectClass}`,
    `来源 Cell：${current.sourceCell || '未提供'}`,
    `数据集：${current.datasetName} · v${current.versionNo}`,
    `几何类型：${current.geometryType || '未提供'}`,
    `范围：${bboxText(current.bbox)}`,
  ]
  if (center) lines.push(`中心经纬度：${center[1].toFixed(6)}, ${center[0].toFixed(6)}`)
  try {
    await navigator.clipboard.writeText(lines.join('\n'))
    ElMessage.success('已复制经纬度/来源信息')
  } catch {
    ElMessage.warning('浏览器不允许访问剪贴板')
  }
}

function viewSameCell() {
  const cell = detail.value?.sourceCell
  if (!cell) {
    ElMessage.warning('该要素未提供来源 Cell')
    return
  }
  props.waterways.setSourceCellFilter(cell)
  ElMessage.info(`已切换为仅查看 Cell ${cell}`)
}

function clearSourceCellFilter() {
  props.waterways.setSourceCellFilter(null)
}

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

function openSnapshotDialog() {
  if (selectedClasses.value.size === 0) {
    ElMessage.warning('请至少选择一个航道对象类别')
    return
  }
  snapshotName.value = ''
  snapshotMaxFeatures.value = 20000
  props.waterways.snapshotError.value = ''
  snapshotDialogVisible.value = true
}

async function showOverviewOnMap() {
  const shown = await props.waterways.showOverview()
  if (!shown) return
  const count = props.waterways.overviewCount.value
  if (count > 0) {
    ElMessage.success(`已在地图显示 ${count} 条航道要素`)
  } else {
    ElMessage.warning(props.waterways.overviewError.value || '没有可叠加的航道要素')
  }
}

async function saveSnapshot() {
  const manifest = await props.waterways.createSnapshot({
    name: snapshotName.value,
    maxFeatures: snapshotMaxFeatures.value,
  })
  if (!manifest) return
  snapshotDialogVisible.value = false
  ElMessage.success(`已保存 ${manifest.featureCount} 个航道要素`)
  snapshotListVisible.value = true
  void props.waterways.loadSnapshots()
}

function openSnapshotList() {
  snapshotListVisible.value = true
  void props.waterways.loadSnapshots()
}

async function downloadSnapshot(manifest: S57WaterwaySnapshotManifest) {
  await props.waterways.downloadSnapshot(manifest)
  if (props.waterways.snapshotsError.value) {
    ElMessage.error(props.waterways.snapshotsError.value)
  }
}

function formatSnapshotTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function snapshotSourceLabel(snapshot: S57WaterwaySnapshotManifest): string {
  return (
    snapshot.sourceDatasets
      .map((item) => `${item.datasetName} · v${item.versionNo}`)
      .join('；') || '来源未提供'
  )
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

    <!-- 成果入口不依赖当前项目是否有可查询航道要素：
         即使航道图层暂不可用，也必须能查看/下载历史快照。 -->
    <div class="waterway-snapshot-actions">
      <el-button size="small" text @click="openSnapshotDialog">保存提取结果</el-button>
      <el-button size="small" text @click="openSnapshotList">已保存航道数据</el-button>
      <el-button size="small" text @click="openDiagnostics">覆盖诊断</el-button>
      <button
        type="button"
        class="waterway-help-toggle"
        @click="helpVisible = !helpVisible"
      >{{ helpVisible ? '收起说明' : '使用说明' }}</button>
    </div>

    <div v-if="helpVisible" class="waterway-help-body">
      <ol>
        <li>勾选需要的航道类别；计数为 0 的类别表示当前项目没有该类图层/要素。</li>
        <li>点击“在地图显示选中类别”即可把要素叠加到当前底图/海图上并自动缩放，<b>不需要先搜索，也不要求先加载 S-57 WMS 海图图层</b>。</li>
        <li>“搜索”只更新下方结果列表，不会自动上图；可在单条结果上点“定位/显示”。</li>
        <li>“当前视口”是可选筛选：勾选后只查询当前地图范围；不勾选则查询整个项目当前版本。</li>
        <li>点击地图上<b>已经显示</b>的专题要素即可高亮并打开详情，无需先开启额外模式。</li>
        <li>图例颜色对应四个航道组；地图叠加有分页和浏览器预算（默认 6,000 条），达到上限会提示。低缩放仅作类别概览，放大查看细部。</li>
        <li><b>交通分隔制 ≠ 推荐航路；局部 S-57 要素 ≠ 完整规划航线。</b></li>
      </ol>
    </div>

    <div v-if="hasWaterwayData" class="waterway-stats">
      <span>ENC Cell <b>{{ stats.cells }}</b></span>
      <span>可检索层 <b>{{ stats.layers }}</b></span>
      <span>匹配 <b>{{ stats.matched === null ? '未知' : stats.matched }}</b></span>
      <span>已加载 <b>{{ stats.loaded }}</b></span>
      <span>当前可见 <b>{{ stats.visible }}</b></span>
      <span>未加载 <b>{{ stats.missing === null ? '未知' : stats.missing }}</b></span>
    </div>
    <div v-if="!stats.countComplete" class="waterway-overview-note">
      部分对象类数量无法精确统计，界面以“未知”显示。
    </div>
    <div v-if="coverageGap" class="waterway-coverage-warning">
      当前项目未覆盖俄罗斯沿岸主要 NSR 航段（{{ missingRegionNames }}）；地图片段不能视为完整东北航道。如已有合法 ENC，请通过批量导入并关联项目。
    </div>
    <div v-if="sourceCellFilter" class="waterway-cell-filter">
      仅看 Cell <b>{{ sourceCellFilter }}</b>
      <el-button size="small" text @click="clearSourceCellFilter">清除</el-button>
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
          <el-checkbox :model-value="viewportOnly" size="small" @change="onViewportOnlyChange">
            当前视口
          </el-checkbox>
          <el-button size="small" type="primary" :disabled="!waterways.canSearch.value" :loading="searching" @click="onSearch">搜索</el-button>
          <el-button size="small" text @click="waterways.clearFilters()">清空</el-button>
        </div>
      </div>

      <div class="waterway-map-legend">
        <div class="waterway-map-legend-head">
          <span>地图专题图例</span>
          <div class="waterway-legend-actions">
            <el-button
              size="small"
              type="primary"
              plain
              :loading="overviewLoading"
              :disabled="selectedClasses.size === 0"
              @click="showOverviewOnMap"
            >在地图显示选中类别</el-button>
            <el-button
              v-if="overviewHasMore"
              size="small"
              text
              :loading="overviewLoading"
              @click="loadMoreOnMap"
            >加载更多</el-button>
          </div>
        </div>
        <div class="waterway-map-legend-items">
          <span
            v-for="entry in groupSummary"
            :key="entry.key"
            class="waterway-map-legend-item"
          >
            <i :style="{ background: entry.color }"></i>{{ entry.label }}
            <b>{{ entry.count }}</b>
          </span>
        </div>
        <div class="waterway-group-toggles">
          <el-checkbox
            :model-value="groupVisible('fairway_route')"
            size="small"
            @change="(value: string | number | boolean) => onGroupChange('fairway_route', value)"
          >航道/推荐路线</el-checkbox>
          <el-checkbox
            :model-value="groupVisible('traffic_separation')"
            size="small"
            @change="(value: string | number | boolean) => onGroupChange('traffic_separation', value)"
          >交通分隔制</el-checkbox>
          <el-checkbox
            :model-value="groupVisible('restriction')"
            size="small"
            @change="(value: string | number | boolean) => onGroupChange('restriction', value)"
          >航行限制</el-checkbox>
          <el-checkbox
            :model-value="groupVisible('waterway_environment')"
            size="small"
            @change="(value: string | number | boolean) => onGroupChange('waterway_environment', value)"
          >辅助/环境</el-checkbox>
        </div>
        <div class="waterway-map-legend-hint">
          勾选类别后点右侧按钮即可上图，无需先“搜索”；数字来自图层目录统计。交通分隔制 ≠ 推荐航路；低缩放仅作类别概览，放大查看细部。
        </div>
        <div
          v-if="overviewMessage"
          :class="['waterway-overview-note', { error: overviewError }]"
        >{{ overviewMessage }}</div>
        <div
          v-for="warning in overviewWarnings"
          :key="warning"
          class="waterway-overview-note"
        >{{ warning }}</div>
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
        <span>搜索结果 {{ total }} 条 · 已加载 {{ stats.loaded }} · 当前可见 {{ stats.visible }}</span>
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
      append-to-body
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
          <el-descriptions-item label="源 ENC Cell">{{ detail.sourceCell || '未提供' }}</el-descriptions-item>
          <el-descriptions-item label="几何类型">{{ detail.geometryType || '未提供' }}</el-descriptions-item>
          <el-descriptions-item label="空间范围">{{ bboxText(detail.bbox) }}</el-descriptions-item>
          <el-descriptions-item v-if="detailLengthKm !== null" label="当前对象几何长度">
            {{ detailLengthKm.toFixed(3) }} km（WGS84 测地线；不代表整条东北航道里程）
          </el-descriptions-item>
          <el-descriptions-item label="导入更新时间">{{ detail.updatedAt || '未提供' }}</el-descriptions-item>
        </el-descriptions>
        <div class="waterway-detail-actions">
          <el-button size="small" text @click="copyDetailInfo">复制经纬度/来源</el-button>
          <el-button size="small" text :disabled="!detail.sourceCell" @click="viewSameCell">
            查看同 Cell 其他对象
          </el-button>
        </div>
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

    <el-dialog
      v-model="snapshotDialogVisible"
      title="保存航道提取结果"
      width="520px"
      class="waterway-snapshot-dialog"
      append-to-body
    >
      <div class="waterway-snapshot-form">
        <label>成果名称</label>
        <el-input
          v-model="snapshotName"
          size="small"
          maxlength="120"
          placeholder="可选，默认按保存时间命名"
        />
        <label>航道类别</label>
        <div class="waterway-snapshot-summary">{{ snapshotClassSummary }}</div>
        <label>筛选条件</label>
        <div class="waterway-snapshot-filters">
          <span>关键词：{{ waterways.keyword.value.trim() || '无' }}</span>
          <span>当前视口：{{ viewportOnly ? '是' : '否' }}</span>
          <span>辅助要素：{{ includeAuxiliary ? '包含' : '不包含' }}</span>
        </div>
        <label>单次最大要素数</label>
        <el-input-number
          v-model="snapshotMaxFeatures"
          :min="1"
          :max="100000"
          :step="1000"
          size="small"
        />
        <p class="waterway-snapshot-hint">
          服务端会按全部匹配记录分批提取，不是仅当前页；达到上限时会在成果中标注截断。
        </p>
        <div v-if="snapshotError" class="waterway-panel-error">{{ snapshotError }}</div>
      </div>
      <template #footer>
        <el-button @click="snapshotDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="snapshotCreating" @click="saveSnapshot">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="snapshotListVisible"
      title="已保存航道数据"
      size="480px"
      class="waterway-snapshot-drawer"
      append-to-body
    >
      <div v-if="snapshotsLoading" class="waterway-panel-empty">正在加载已保存成果…</div>
      <div v-else-if="snapshotsError" class="waterway-panel-error">
        <span>{{ snapshotsError }}</span>
        <el-button size="small" text @click="waterways.loadSnapshots()">重试</el-button>
      </div>
      <div v-else-if="snapshots.length === 0" class="waterway-panel-empty">
        尚未保存航道数据成果
      </div>
      <div v-else class="waterway-snapshot-list">
        <article
          v-for="snapshot in snapshots"
          :key="snapshot.snapshotId"
          class="waterway-snapshot-item"
        >
          <div class="waterway-snapshot-head">
            <strong>{{ snapshot.name }}</strong>
            <span v-if="snapshot.stale" class="waterway-snapshot-stale">基于旧版海图数据</span>
          </div>
          <div class="waterway-snapshot-meta">
            <span>{{ snapshot.snapshotId }}</span>
            <span>{{ formatSnapshotTime(snapshot.createdAt) }}</span>
          </div>
          <div class="waterway-snapshot-meta">
            <span>{{ snapshotSourceLabel(snapshot) }}</span>
            <span>{{ snapshot.featureCount }} 个要素</span>
          </div>
          <div class="waterway-snapshot-meta">
            <span>类别：{{ snapshot.objectClasses.join('、') || '—' }}</span>
            <span v-if="snapshot.truncated" class="waterway-snapshot-stale">
              已达到单次提取上限
            </span>
          </div>
          <el-button size="small" text @click="downloadSnapshot(snapshot)">下载 GeoJSON</el-button>
        </article>
      </div>
    </el-drawer>

    <el-drawer
      v-model="diagnosticsVisible"
      title="航道完整性诊断 / 东北航道对照"
      size="560px"
      class="waterway-diagnostics-drawer"
      append-to-body
    >
      <div v-if="diagnosticsLoading" class="waterway-panel-empty">正在核查项目关联、图层与覆盖范围…</div>
      <div v-else-if="diagnosticsError" class="waterway-panel-error">
        <span>{{ diagnosticsError }}</span>
        <el-button size="small" text @click="waterways.loadDiagnostics()">重试</el-button>
      </div>
      <template v-else-if="diagnostics">
        <div class="waterway-diagnostic-summary">
          <span>已关联 Cell <b>{{ diagnostics.totals.linkedCellCount }}</b></span>
          <span>航道层 <b>{{ diagnostics.totals.waterwayLayerCount }}</b></span>
          <span>可检索 <b>{{ diagnostics.totals.searchableLayerCount }}</b></span>
          <span>可渲染 <b>{{ diagnostics.totals.renderableLayerCount }}</b></span>
          <span>要素 <b>{{ diagnostics.totals.featureCount }}</b></span>
          <span>数量完整 <b>{{ diagnostics.totals.countComplete ? '是' : '未知' }}</b></span>
        </div>
        <div v-if="diagnostics.northeastPassage.hasGap" class="waterway-coverage-warning">
          {{ diagnostics.northeastPassage.summary }}
        </div>

        <div class="waterway-detail-section-title">按 ENC Cell</div>
        <el-table :data="diagnostics.cells" size="small" max-height="260">
          <el-table-column prop="sourceCell" label="Cell" width="92" />
          <el-table-column prop="versionNos" label="版本" width="60">
            <template #default="{ row }">{{ row.versionNos.join(', ') || '—' }}</template>
          </el-table-column>
          <el-table-column prop="waterwayLayerCount" label="航道层" width="70" />
          <el-table-column prop="waterwayFeatureCount" label="要素" width="70" />
          <el-table-column prop="coverageSource" label="覆盖来源" width="100" />
          <el-table-column label="原因" min-width="150">
            <template #default="{ row }">{{ row.reasons.join('；') || '—' }}</template>
          </el-table-column>
        </el-table>

        <div class="waterway-detail-section-title">东北航道 / 北方海航道对照区域</div>
        <div class="waterway-diagnostic-regions">
          <article
            v-for="region in diagnostics.regions"
            :key="region.code"
            class="waterway-diagnostic-region"
          >
            <div class="waterway-diagnostic-region-head">
              <strong>{{ region.nameZh }}</strong>
              <el-tag size="small" :type="regionStatusType(region.status)">
                {{ regionStatusLabel(region.status) }}
              </el-tag>
            </div>
            <div class="waterway-diagnostic-region-meta">
              Cell：{{ region.cells.join('、') || '无' }} · 航道类：{{ region.waterwayClasses.join('、') || '无' }} · 要素：{{ region.featureCount }}
            </div>
            <div class="waterway-diagnostic-region-note">{{ region.note }}</div>
          </article>
        </div>

        <div class="waterway-detail-section-title">口径与参考</div>
        <div class="waterway-diagnostic-notes">
          <div v-for="note in diagnostics.notes" :key="note">{{ note }}</div>
          <div v-for="warning in diagnostics.warnings" :key="warning">{{ warning }}</div>
        </div>
        <div class="waterway-diagnostic-references">
          <div v-for="reference in diagnostics.references" :key="reference.url">
            <a :href="reference.url" target="_blank" rel="noopener noreferrer">{{ reference.title }}</a>
            <span>（{{ reference.checkedAt }}）</span>
            <div>{{ reference.scope }}</div>
          </div>
        </div>
      </template>
    </el-drawer>
  </section>
</template>
