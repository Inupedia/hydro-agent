<script setup lang="ts">
defineProps<{
  scheme: {
    scheme_id: string
    status: string
    content_hash: string
    model_id: string
    provenance: Record<string, unknown>
  } | null
}>()
</script>

<template>
  <section v-if="scheme">
    <h3>{{ scheme.status === 'frozen' ? '冻结方案' : '当前方案' }}</h3>
    <p>模型：{{ scheme.model_id }}</p>
    <p>方案：{{ scheme.scheme_id }}</p>
    <p>哈希：{{ scheme.content_hash.slice(0, 12) }}</p>
  </section>
</template>
