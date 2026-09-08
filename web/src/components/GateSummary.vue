<script setup lang="ts">
defineProps<{ gate: Record<string, unknown> | null }>()
</script>

<template>
  <section v-if="gate">
    <h3>Gate 结果</h3>
    <p>状态：{{ gate.status }}</p>
    <p v-if="gate.reasons">原因：{{ Array.isArray(gate.reasons) ? gate.reasons.join('；') : gate.reasons }}</p>
  </section>
</template>
