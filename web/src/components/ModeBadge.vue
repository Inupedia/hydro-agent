<script setup lang="ts">
import type { RunMode } from '../stores/demo'

defineProps<{ mode: RunMode }>()

const labels: Record<RunMode, string> = {
  live: '实时执行',
  replay: '案例回放',
  simulated: '模拟演示',
}
</script>

<template>
  <span class="mode-badge" :data-mode="mode" role="status">
    <span class="dot" aria-hidden="true" />
    {{ labels[mode] }}
  </span>
</template>

<style scoped>
.mode-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  height: 24px;
  min-height: 24px;
  padding: 0 0.5rem;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid var(--separator);
  color: var(--secondary);
  font-size: 11px;
  font-weight: 550;
}
.mode-badge[data-mode='live'] {
  color: var(--blue);
  background: var(--blue-soft);
  border-color: transparent;
}
.mode-badge[data-mode='replay'] {
  color: var(--caution);
  background: var(--caution-soft);
  border-color: transparent;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.mode-badge[data-mode='live'] .dot {
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.18);
}
</style>
