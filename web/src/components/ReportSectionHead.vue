<script setup lang="ts">
defineProps<{
  overline: string
  title: string
  subtitle?: string
  titleId?: string
}>()
</script>

<template>
  <header class="report-section-head">
    <div class="report-section-copy">
      <span class="overline">{{ overline }}</span>
      <h2 :id="titleId">{{ title }}</h2>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.aside" class="report-section-aside">
      <slot name="aside" />
    </div>
  </header>
</template>

<style scoped>
.report-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.report-section-copy {
  min-width: 0;
}
.overline {
  display: block;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.report-section-head h2 {
  margin: 4px 0 0;
  font-size: 22px;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: -0.3px;
}
.report-section-head p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.6;
}
.report-section-aside {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-start;
  padding-top: 4px;
}
@media (max-width: 720px) {
  .report-section-head {
    flex-direction: column;
  }
}
</style>
