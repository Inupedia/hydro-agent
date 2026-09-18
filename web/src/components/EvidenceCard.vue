<script setup lang="ts">
import { computed } from 'vue'
import type { EvidenceAuditSummary } from '../types/api'

const props = defineProps<{ evidence?: EvidenceAuditSummary | null }>()
const metrics = computed(() => Object.entries(props.evidence?.metrics || {}).slice(0, 4))
const observations = computed(() => (props.evidence?.observations || []).filter((item) => !item.includes('=')).slice(0, 3))
</script>

<template>
  <article class="evidence-card" data-test="evidence-card">
    <header><span>EVIDENCE</span><strong>执行证据</strong></header>
    <template v-if="evidence">
      <div v-if="metrics.length" class="evidence-metrics">
        <span v-for="([key, value]) in metrics" :key="key"><small>{{ key }}</small><strong>{{ Number(value).toFixed(3) }}</strong></span>
      </div>
      <ul v-if="observations.length"><li v-for="item in observations" :key="item">{{ item }}</li></ul>
      <p v-if="!metrics.length && !observations.length">工具已返回可追溯记录。</p>
      <footer>下一轮 Agent 将基于这些新事实重新观察并决定下一步。</footer>
    </template>
    <p v-else>等待执行工具返回新事实。</p>
  </article>
</template>

<style scoped>
.evidence-card { min-width: 0; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface); padding: 12px; }
header { display: grid; gap: 2px; }
header span { color: var(--trace-evidence); font-size: 10px; font-weight: 750; letter-spacing: .06em; }
header strong { color: var(--text-primary); font-size: 13px; }
.evidence-metrics { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.evidence-metrics span { display: grid; gap: 1px; min-width: 62px; border-radius: var(--radius-xs); background: var(--surface-secondary); padding: 6px 7px; }
.evidence-metrics small { color: var(--text-tertiary); font-size: 8px; }
.evidence-metrics strong { color: var(--text-primary); font-family: var(--mono); font-size: 11px; }
ul { margin: 8px 0 0; padding-left: 16px; color: var(--text-secondary); font-size: 10px; line-height: 1.5; }
p { margin: 9px 0 0; color: var(--text-secondary); font-size: 10px; line-height: 1.5; }
footer { margin-top: 8px; padding-top: 7px; border-top: 1px solid var(--separator); color: var(--text-secondary); font-size: 11px; line-height: 1.6; }
.evidence-card { border-color: color-mix(in srgb, var(--trace-evidence) 28%, var(--separator)); }
.evidence-metrics span { background: color-mix(in srgb, var(--trace-evidence) 8%, var(--surface)); }
.evidence-metrics small, ul, p { font-size: 12px; }
</style>
