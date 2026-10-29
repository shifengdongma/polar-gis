<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  modelValue: string
  disabled?: boolean
}>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
  (event: 'refresh'): void
}>()

const local = ref(props.modelValue)
watch(
  () => props.modelValue,
  (value) => {
    local.value = value
  },
)

function apply() {
  const value = local.value.trim()
  if (!value) return
  const normalized = value.endsWith('Z') ? value : `${value}Z`
  emit('update:modelValue', normalized)
  emit('refresh')
}
</script>

<template>
  <div class="environment-time-control">
    <div class="environment-time-label">环境时间（UTC）</div>
    <div class="environment-time-row">
      <el-date-picker
        v-model="local"
        type="datetime"
        value-format="YYYY-MM-DDTHH:mm:ss"
        format="YYYY-MM-DD HH:mm"
        placeholder="选择 UTC 时间"
        :disabled="disabled"
        size="small"
        class="environment-time-picker"
      />
      <el-button size="small" type="primary" :disabled="disabled" @click="apply">刷新</el-button>
    </div>
    <div class="environment-time-hint">各图层按实际可用时次匹配，匹配时间在图层行显示</div>
  </div>
</template>
