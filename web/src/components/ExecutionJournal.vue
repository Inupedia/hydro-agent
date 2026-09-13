<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import { actionTitle } from '../demo/stages'
import { WORKFLOW } from '../generated/workflow'
import type { AgentRoundLogItem, TimelineItem } from '../types/api'

const props = defineProps<{
  taskId?: string | null
  events: TimelineItem[]
  running: boolean
  completed: boolean
  failed: boolean
  elapsed: string
  error?: string | null
}>()

const emit = defineEmits<{ refresh: [] }>()
const agentRounds = ref<AgentRoundLogItem[]>([])
let requestSerial = 0

const orderedEvents = computed(() =>
  [...props.events].sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at)),
)

const statusLabel = computed(() =>
  props.running ? '运行中' : props.completed ? '已完成' : props.failed ? '已受阻' : '等待执行',
)

watch(
  [() => props.taskId, () => props.events.length],
  async ([taskId]) => {
    const serial = ++requestSerial
    if (!taskId) {
      agentRounds.value = []
      return
    }
    try {
      const log = await api.getAgentLog(taskId)
      if (serial === requestSerial) agentRounds.value = log.rounds || []
    } catch {
      if (serial === requestSerial) agentRounds.value = []
    }
  },
  { immediate: true },
)

const STATUS_LABELS: Record<string, string> = {
  succeeded: '已完成',
  completed: '已完成',
  success: '已完成',
  running: '进行中',
  failed: '失败',
  error: '失败',
  skipped: '已跳过',
  ACCEPT: '采用候选',
  KEEP: '保留原方案',
  ROLLBACK: '回退原方案',
  blocked: '已受阻',
}

function eventStatus(status: string) {
  return STATUS_LABELS[status] || status || '执行记录'
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function matchingRound(event: TimelineItem) {
  if (!event.action) return null
  const candidates = agentRounds.value.filter((round) => round.action === event.action)
  if (!candidates.length) return null
  const eventTime = Date.parse(event.occurred_at)
  if (Number.isNaN(eventTime)) return candidates.at(-1) || null
  return candidates.reduce((best, candidate) => {
    if (!best) return candidate
    const candidateTime = candidate.occurred_at ? Date.parse(candidate.occurred_at) : Number.NaN
    const bestTime = best.occurred_at ? Date.parse(best.occurred_at) : Number.NaN
    const candidateDistance = Number.isNaN(candidateTime) ? Number.POSITIVE_INFINITY : Math.abs(candidateTime - eventTime)
    const bestDistance = Number.isNaN(bestTime) ? Number.POSITIVE_INFINITY : Math.abs(bestTime - eventTime)
    return candidateDistance < bestDistance ? candidate : best
  }, null as AgentRoundLogItem | null)
}

function workflowExplain(action: string | null) {
  if (!action) return ''
  const item = WORKFLOW.actions[action as keyof typeof WORKFLOW.actions]
  return item?.explain_zh || ''
}

function detailText(details: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = details[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function compactMetrics(round: AgentRoundLogItem | null) {
  if (!round?.tool_metrics) return ''
  const entries = Object.entries(round.tool_metrics)
    .filter(([, value]) => Number.isFinite(value))
    .slice(0, 4)
  if (!entries.length) return ''
  return entries.map(([key, value]) => `${key}=${Number(value).toFixed(3)}`).join('，')
}

function narrative(event: TimelineItem) {
  const round = matchingRound(event)
  const explain = workflowExplain(event.action)
  const judgment =
    round?.judgment_zh ||
    round?.hypothesis_zh ||
    detailText(event.details, ['judgment_zh', 'hypothesis_zh', 'judgment', 'hypothesis'])
  const rationale =
    round?.rationale_summary ||
    detailText(event.details, ['rationale_summary', 'reason_zh', 'reason', 'rationale']) ||
    explain
  const action = round?.action_zh || (event.action ? actionTitle(event.action) : event.label) || '系统执行'
  const observations = round?.tool_observations?.filter(Boolean).slice(0, 2) || []
  const metrics = compactMetrics(round)
  const result = observations.length
    ? observations.join('；')
    : metrics
      ? `关键指标：${metrics}`
      : event.status === 'running'
        ? '当前步骤仍在执行，结果尚未形成。'
        : event.label || '已记录本步执行结果。'
  const subtitle = judgment || rationale || explain || `${action}，并记录本步执行证据。`
  return {
    judgment: judgment || '按当前任务状态进入这一步。',
    action,
    rationale: rationale || explain || '由既定工作流和当前证据触发。',
    result,
    subtitle,
  }
}
</script>

<template>
  <div class="execution-journal">
    <div class="pane-head journal-head">
      <div class="section-heading"><span class="overline">执行记录</span></div>
      <h2>完整执行记录</h2>
      <p class="journal-intro">每一步先说明智能体如何判断、做了什么以及依据是什么；原始数据保留在“技术详情”中。</p>
      <div class="journal-status">
        <span :class="{ 'blue-dot': running }">{{ statusLabel }}</span>
        <span>{{ elapsed }}</span>
      </div>
      <div v-if="error" class="inline-error" role="alert">
        <strong>暂时无法继续</strong>
        <p>{{ error }}</p>
        <button v-if="taskId" class="text-button" type="button" @click="emit('refresh')">重新读取状态</button>
      </div>
    </div>

    <div class="journal-list">
      <div v-if="!orderedEvents.length" class="journal-empty">
        <span aria-hidden="true">⌁</span>
        <h3>等待第一条记录</h3>
        <p>开始后，这里会按实际执行顺序记录系统判断、动作、依据与结果。</p>
      </div>

      <article
        v-for="(event, index) in orderedEvents"
        :key="event.id"
        class="journal-event-card"
        :class="{ 'is-failed': ['failed', 'error', 'blocked'].includes(event.status) }"
        :data-action="event.action || undefined"
      >
        <div class="event-rail" aria-hidden="true">
          <span class="event-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <i />
        </div>
        <div class="event-content">
          <div class="event-meta">
            <span>{{ eventStatus(event.status) }}</span>
            <time v-if="formatTime(event.occurred_at)">{{ formatTime(event.occurred_at) }}</time>
          </div>
          <h3>{{ event.label || actionTitle(event.action) }}</h3>
          <p class="event-subtitle">{{ narrative(event).subtitle }}</p>

          <dl class="event-explanation">
            <div><dt>判断</dt><dd>{{ narrative(event).judgment }}</dd></div>
            <div><dt>动作</dt><dd>{{ narrative(event).action }}</dd></div>
            <div><dt>依据</dt><dd>{{ narrative(event).rationale }}</dd></div>
            <div><dt>结果</dt><dd>{{ narrative(event).result }}</dd></div>
          </dl>

          <details class="technical-details">
            <summary><span>技术详情</span><span>JSON</span></summary>
            <pre>{{ JSON.stringify(event.details, null, 2) }}</pre>
          </details>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.execution-journal { display: flex; min-height: 0; flex: 1; flex-direction: column; }
.journal-head { flex: 0 0 auto; }
.section-heading { margin-bottom: 18px; }
.journal-intro { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.journal-status { display: flex; justify-content: space-between; gap: 8px; padding: 12px 0 16px; border-bottom: 1px solid var(--separator); color: var(--text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }
.journal-list { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 8px 2px 18px 0; scrollbar-gutter: stable; }
.journal-empty { padding: 48px 4px; text-align: center; }
.journal-empty > span { color: var(--text-tertiary); font-size: 40px; }
.journal-empty h3 { margin: 14px 0 10px; font-size: 16px; font-weight: 600; }
.journal-empty p { max-width: 220px; margin: auto; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.journal-event-card { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 10px; padding: 14px 0 16px; border-bottom: 1px solid var(--separator); }
.event-rail { display: flex; align-items: center; flex-direction: column; }
.event-index { display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid rgba(0, 122, 255, 0.14); border-radius: 9px; background: rgba(255, 255, 255, 0.88); color: var(--accent-text); font-size: 10px; font-weight: 700; box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.96); }
.event-rail i { width: 1px; flex: 1; min-height: 18px; margin-top: 7px; background: var(--separator); }
.journal-event-card:last-child .event-rail i { display: none; }
.is-failed .event-index { border-color: rgba(215, 0, 21, 0.18); color: var(--danger); }
.event-content { min-width: 0; }
.event-meta { display: flex; justify-content: space-between; gap: 8px; color: var(--text-tertiary); font-size: 10px; font-weight: 650; letter-spacing: 0.03em; }
.event-meta time { font-variant-numeric: tabular-nums; }
.event-content h3 { margin: 4px 0 0; color: var(--text-primary); font-size: 14px; font-weight: 650; line-height: 1.4; }
.event-subtitle { margin: 6px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.event-explanation { display: grid; gap: 7px; margin: 11px 0 0; }
.event-explanation > div { display: grid; grid-template-columns: 38px minmax(0, 1fr); gap: 7px; }
.event-explanation dt { color: var(--text-tertiary); font-size: 10px; font-weight: 700; }
.event-explanation dd { margin: 0; color: var(--text-primary); font-size: 11px; line-height: 1.55; overflow-wrap: anywhere; }
.technical-details { margin-top: 11px; border-top: 1px solid rgba(220, 221, 227, 0.62); padding-top: 8px; }
.technical-details summary { display: flex; justify-content: space-between; cursor: pointer; list-style: none; color: var(--text-tertiary); font-size: 10px; font-weight: 650; }
.technical-details summary::-webkit-details-marker { display: none; }
.technical-details pre { max-height: 220px; margin: 9px 0 0; overflow: auto; border-radius: var(--radius-md); background: var(--surface-secondary); padding: 10px; color: var(--text-secondary); font-family: var(--mono); font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; white-space: pre-wrap; }
.inline-error { margin-top: 12px; border: 1px solid #f0c8c3; border-radius: var(--radius-md); background: var(--danger-soft); padding: 11px; color: var(--danger); font-size: 12px; }
.inline-error p { margin: 5px 0; line-height: 1.5; }
.text-button { border: 0; background: none; color: var(--accent-text); padding: 0; font: inherit; cursor: pointer; }
.blue-dot::before { display: inline-block; width: 6px; height: 6px; margin-right: 6px; border-radius: 50%; background: var(--accent); content: ''; }
</style>
