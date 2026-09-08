<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ gate: Record<string, unknown> | null }>()

const plain = computed(() => {
  const status = props.gate?.status
  if (status === 'KEEP') {
    return '没有换方案：微调带来的提升不够大。'
  }
  if (status === 'ACCEPT') {
    return '采纳了改进方案：关键指标有稳定提升。'
  }
  if (status === 'ROLLBACK') {
    return '退回了原方案：候选方案未过安全门槛。'
  }
  return status ? `决策状态：${status}` : ''
})
</script>

<template>
  <section v-if="gate">
    <h3>把关结论</h3>
    <p>{{ plain }}</p>
  </section>
</template>
