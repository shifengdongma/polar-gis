<script setup lang="ts">
/**
 * Inline S-57 chart layer legend.
 *
 * Requests `/layers/{id}/legend` only after this component is mounted (the user
 * expanded the row). The real GeoServer GetLegendGraphic image is shown when
 * available; otherwise a simplified swatch derived from the backend's
 * `s57_styles.py` preset is shown. If neither exists, only the object code and
 * description are displayed — no invented symbols.
 */
import { computed, onMounted, ref } from 'vue'
import { apiErrorMessage } from '../api/client'
import type { MapLayerConfig } from '../types'
import {
  fetchLayerLegend,
  invalidateLayerLegend,
  type S57LegendFallback,
  type S57LegendPayload,
} from '../utils/s57LayerLegend'
import { s57ObjectDescription, s57ObjectName } from '../utils/s57ObjectNames'

const props = defineProps<{ layer: MapLayerConfig }>()

const payload = ref<S57LegendPayload | null>(null)
const loading = ref(true)
const error = ref('')
const imageFailed = ref(false)

const code = computed(() => payload.value?.objectClass || props.layer.objectClass || '')
const title = computed(
  () =>
    s57ObjectName(code.value) ||
    props.layer.objectNameZh ||
    props.layer.name,
)
const description = computed(
  () =>
    s57ObjectDescription(code.value) ||
    '暂未提供该对象类别的说明，仅显示 S-57 对象代码。',
)
const fallback = computed<S57LegendFallback | null>(() => payload.value?.fallback ?? null)
const fallbackStyle = computed<Record<string, string>>(() => {
  const item = fallback.value
  const style: Record<string, string> = {}
  if (!item) return style
  style['--legend-color'] = item.color
  style['--legend-fill'] = item.fillColor || item.color
  style['--legend-opacity'] = String(item.opacity ?? 1)
  return style
})

async function load() {
  loading.value = true
  error.value = ''
  imageFailed.value = false
  try {
    payload.value = await fetchLayerLegend(props.layer)
  } catch (caught) {
    error.value = apiErrorMessage(caught, '图例加载失败')
  } finally {
    loading.value = false
  }
}

function retry() {
  invalidateLayerLegend(props.layer)
  void load()
}

function onImageLoad(event: Event) {
  const image = event.target as HTMLImageElement
  // GeoServer may answer with a 1–2 px transparent image when a layer has no
  // legend rule; treat that as unusable instead of showing an empty box.
  if (image.naturalWidth <= 2 || image.naturalHeight <= 2) {
    imageFailed.value = true
  }
}

onMounted(load)
</script>

<template>
  <div class="s57-layer-legend">
    <div class="s57-layer-legend-head">
      <strong>{{ title }}</strong>
      <code v-if="code">{{ code }}</code>
    </div>
    <div v-if="loading" class="s57-layer-legend-empty">正在加载图例…</div>
    <template v-else>
      <div class="s57-layer-legend-symbol">
        <img
          v-if="payload?.url && !imageFailed"
          :src="payload.url"
          :alt="`${title} 图例`"
          @error="imageFailed = true"
          @load="onImageLoad"
        />
        <span
          v-else-if="fallback"
          :class="['s57-legend-swatch', `is-${fallback.geometry}`]"
          :style="fallbackStyle"
          :title="fallback.label || title"
        ></span>
        <span v-else class="s57-layer-legend-empty">无可用图例/预设符号</span>
      </div>
      <p class="s57-layer-legend-description">{{ description }}</p>
      <p v-if="error" class="s57-layer-legend-note">
        {{ error }}
        <button type="button" @click="retry">重试</button>
      </p>
      <p v-else-if="imageFailed" class="s57-layer-legend-note">
        GeoServer 图例不可用，显示当前系统预设样式的简化符号。
      </p>
      <p class="s57-layer-legend-note">
        图例为当前 GeoServer 样式的示意，同一类别可能随比例尺/属性变化；S-57
        海图对象为制图数据，不代表实时航行状态或已验证的安全通道。
      </p>
    </template>
  </div>
</template>
