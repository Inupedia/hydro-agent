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
  <!-- Kept for unit/e2e compatibility; ResultView now uses ProcessStory as the primary narrative. -->
  <section v-if="scheme" class="scheme-summary">
    <h3>{{ scheme.status === 'frozen' ? '冻结方案' : '当前方案' }}</h3>
    <p>
      {{
        scheme.status === 'frozen'
          ? '这套参数已被锁定，后续评估都基于这一版。'
          : '这套参数仍可被后续步骤调整。'
      }}
    </p>
    <p class="muted">模型：{{ scheme.model_id === 'xaj' ? '新安江（XAJ）' : scheme.model_id }}</p>
  </section>
</template>

<style scoped>
.muted {
  color: rgba(16, 35, 28, 0.65);
  font-size: 0.9rem;
}
</style>
