<script setup lang="ts">
import { computed } from 'vue'
import type { ToolCallAudit } from '../types/api'
import { toolForAction } from '../tools/catalog'

const props = defineProps<{ toolCall: ToolCallAudit; compact?: boolean; active?: boolean }>()
const descriptor = computed(() => toolForAction(props.toolCall.action))
const title = computed(() => props.toolCall.tool_name_zh || descriptor.value?.nameZh || props.toolCall.tool_id)
const description = computed(() => props.toolCall.description_zh || descriptor.value?.descriptionZh || '')
const statusText = computed(() => ({
  pending: '等待执行', running: '正在执行', completed: '已完成', succeeded: '已完成',
  failed: '执行失败', blocked: '已阻断', ACCEPT: '已完成', KEEP: '已完成', ROLLBACK: '已完成',
}[props.toolCall.status] || props.toolCall.status))
const inputRows = computed(() => Object.entries(props.toolCall.input_summary || {}).slice(0, props.compact ? 2 : 5))
const outputRows = computed(() => Object.entries(props.toolCall.output_summary || {}).slice(0, props.compact ? 2 : 5))
const metricRows = computed(() => Object.entries(props.toolCall.metrics || {}).slice(0, props.compact ? 3 : 6))
function valueText(value: unknown) {
  if (Array.isArray(value)) return value.join('；')
  if (value && typeof value === 'object') return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}: ${String(item)}`).join('；')
  return String(value)
}
</script>

<template>
  <article class="tool-execution-card" :class="[`is-${toolCall.status}`, { 'is-active': active, 'is-compact': compact }]" data-test="tool-execution-card">
    <header>
      <div>
        <span>TOOL</span>
        <strong>{{ title }}</strong>
        <small>{{ toolCall.tool_id }}</small>
      </div>
      <em>{{ statusText }}</em>
    </header>
    <p v-if="description">{{ description }}</p>
    <dl v-if="inputRows.length || outputRows.length || metricRows.length">
      <div v-for="([key, value]) in inputRows" :key="`input-${key}`"><dt>输入 · {{ key }}</dt><dd>{{ valueText(value) }}</dd></div>
      <div v-for="([key, value]) in outputRows" :key="`output-${key}`"><dt>输出 · {{ key }}</dt><dd>{{ valueText(value) }}</dd></div>
      <div v-for="([key, value]) in metricRows" :key="`metric-${key}`"><dt>指标 · {{ key }}</dt><dd>{{ valueText(value) }}</dd></div>
    </dl>
  </article>
</template>

<style scoped>
.tool-execution-card { min-width: 0; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface); padding: 12px; }
.tool-execution-card.is-active { border-color: color-mix(in srgb, var(--accent) 42%, var(--separator)); box-shadow: inset 0 1px 0 color-mix(in srgb, var(--accent) 12%, transparent); }
header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
header > div { display: grid; min-width: 0; gap: 2px; }
header span { color: var(--accent-text); font-size: 9px; font-weight: 750; letter-spacing: .06em; }
header strong { color: var(--text-primary); font-size: 13px; line-height: 1.35; }
header small { color: var(--text-tertiary); font-family: var(--mono); font-size: 9px; overflow-wrap: anywhere; }
header em { flex: 0 0 auto; color: var(--text-secondary); font-size: 10px; font-style: normal; font-weight: 650; }
.is-running header em { color: var(--accent-text); }
.is-failed header em, .is-blocked header em { color: var(--danger); }
p { margin: 8px 0 0; color: var(--text-secondary); font-size: 11px; line-height: 1.55; }
dl { display: grid; gap: 6px; margin: 9px 0 0; padding-top: 8px; border-top: 1px solid var(--separator); }
dl div { display: grid; gap: 2px; }
dt { color: var(--text-tertiary); font-size: 9px; font-weight: 650; }
dd { margin: 0; color: var(--text-primary); font-size: 10px; line-height: 1.45; overflow-wrap: anywhere; }
.is-compact { padding: 10px; }
.is-compact p { display: none; }
header span { color: var(--trace-tool); }
header small, dt { font-size: 11px; }
dd { font-size: 12px; line-height: 1.6; }
header { flex-wrap: wrap; }
@media (prefers-reduced-transparency: reduce) { .tool-execution-card { background: var(--surface); } }
</style>
