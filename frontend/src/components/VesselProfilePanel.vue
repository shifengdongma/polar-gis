<script setup lang="ts">
import { computed } from 'vue'
import type { VesselProfile } from '../types/navigation'

const props = defineProps<{
  vessels: VesselProfile[]
  selectedId?: string | null
  loading?: boolean
  error?: string
}>()
const emit = defineEmits<{
  (event: 'select', id: string): void
}>()

const selected = computed(
  () => props.vessels.find((vessel) => vessel.id === props.selectedId) ?? props.vessels[0] ?? null,
)

function select(id: string) {
  emit('select', id)
}
</script>

<template>
  <section class="vessel-profile-panel">
    <div class="vessel-panel-heading">
      <div>
        <span class="eyebrow">VESSEL</span>
        <h3>船舶资料</h3>
      </div>
      <el-tag size="small" type="info">静态资料</el-tag>
    </div>

    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />

    <el-select
      :model-value="selected?.id ?? selectedId ?? ''"
      placeholder="选择船舶"
      :loading="loading"
      class="full-width"
      @update:model-value="select"
    >
      <el-option v-for="vessel in vessels" :key="vessel.id" :label="vessel.name" :value="vessel.id" />
    </el-select>

    <template v-if="selected">
      <el-descriptions :column="2" border size="small" class="vessel-descriptions">
        <el-descriptions-item label="船型">{{ selected.vesselType }}</el-descriptions-item>
        <el-descriptions-item label="冰级">{{ selected.iceClass ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="船长">{{ selected.lengthM }} m</el-descriptions-item>
        <el-descriptions-item label="船宽">{{ selected.beamM }} m</el-descriptions-item>
        <el-descriptions-item label="设计吃水">{{ selected.designDraftM }} m</el-descriptions-item>
        <el-descriptions-item label="富余水深 UKC">{{ selected.ukcM }} m</el-descriptions-item>
        <el-descriptions-item label="所需水深">{{ selected.requiredDepthM }} m</el-descriptions-item>
        <el-descriptions-item label="推进功率">{{ selected.totalPropulsionPowerMw }} MW</el-descriptions-item>
        <el-descriptions-item label="服务航速">{{ selected.serviceSpeedMinKn }}–{{ selected.serviceSpeedMaxKn }} kn</el-descriptions-item>
        <el-descriptions-item label="最大航速">{{ selected.maximumSpeedKn }} kn</el-descriptions-item>
        <el-descriptions-item label="连续破冰">{{ selected.continuousIceThicknessM }} m</el-descriptions-item>
        <el-descriptions-item label="续航">{{ selected.enduranceNmi ?? '—' }} nmi</el-descriptions-item>
      </el-descriptions>

      <el-alert
        :title="selected.liveStateNote"
        type="info"
        :closable="false"
        show-icon
        class="vessel-live-note"
      />
      <div v-if="selected.sources.length" class="vessel-source-list">
        <div class="vessel-source-title">资料来源</div>
        <div v-for="source in selected.sources" :key="source.title" class="vessel-source-item">
          <a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title }}</a>
          <span v-else>{{ source.title }}</span>
        </div>
      </div>
    </template>
    <el-empty v-else description="暂无船舶资料" :image-size="36" />
  </section>
</template>
