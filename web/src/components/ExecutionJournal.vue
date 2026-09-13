<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
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
const journalList = ref<HTMLElement | null>(null)
let requestSerial = 0

const orderedEvents = computed(() =>
  [...props.events].sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at)),
)
const latestEventId = computed(() => orderedEvents.value.at(-1)?.id || '')
const statusLabel = computed(() =>
  props.running ? '运行中' : props.completed ? '已完成' : props.failed ? '已受阻' : '等待执行',
)

function scrollToLatest() {
  const container = journalList.value
  if (!container) return
  container.scrollTop = container.scrollHeight
}

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
    await nextTick()
    scrollToLatest()
  },
  { immediate: true },
)

watch(
  latestEventId,
  async () => {
    await nextTick()
    scrollToLatest()
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

function readable(value: unknown, maxLength = 320) {
  if (typeof value !== 'string') return ''
  const text = value.replace(/\\_/g, '_').replace(/\s+/g, ' ').trim()
  if (!text || text.length > maxLength) return ''
  if (/[{}\[\]]/.test(text)) return ''
  if (/A\d{2}_[A-Z_]+|recommended_|hypotheses_json|input_world_state|strategy_id|skill_id|evidence_id|Gate\s*=/i.test(text)) return ''
  return text
}

type AuditPayload = {
  action?: string
  observation_zh?: string
  analysis_zh?: string
  decision_zh?: string
}

function llmAudit(round: AgentRoundLogItem | null): AuditPayload {
  const raw = round?.llm_output?.trim()
  if (!raw) return {}
  const start = raw.indexOf('{')
  const end = raw.lastIndexOf('}')
  if (start < 0 || end <= start) return {}
  try {
    const payload = JSON.parse(raw.slice(start, end + 1)) as Record<string, unknown>
    return {
      action: typeof payload.action === 'string' ? payload.action : undefined,
      observation_zh: readable(payload.observation_zh, 180) || undefined,
      analysis_zh: readable(payload.analysis_zh, 420) || undefined,
      decision_zh: readable(payload.decision_zh, 180) || undefined,
    }
  } catch {
    return {}
  }
}

function toolResult(event: TimelineItem, round: AgentRoundLogItem | null) {
  const status = String(event.status || '').toUpperCase()
  if (status === 'RUNNING') return '工具正在执行，完成后会自动更新结果。'
  if (status === 'ROLLBACK') return '本次候选已撤销，当前方案恢复到回退前状态。'
  if (status === 'KEEP') return '当前方案保持不变。'
  if (status === 'ACCEPT') return '候选方案已被采用。'
  const observations = (round?.tool_observations || [])
    .map((item) => readable(item, 100))
    .filter(Boolean)
    .slice(0, 2)
  if (observations.length) return observations.join('；')
  if (['FAILED', 'ERROR', 'BLOCKED'].includes(status)) return '本步未正常完成，需要检查技术详情。'
  return event.label ? `${event.label}。` : '本步已执行完成。'
}

type JournalCopy = {
  observation?: string
  analysis: string
  decision?: string
  result?: string
}

function journalCopy(event: TimelineItem): JournalCopy {
  const round = matchingRound(event)
  const audit = llmAudit(round)
  const legacyObservation = readable(round?.input_summary_zh, 180)
  const legacyAnalysis = readable(round?.judgment_zh, 420)
  const rationale = readable(round?.rationale_summary, 220)
  const analysis =
    audit.analysis_zh ||
    legacyAnalysis ||
    rationale ||
    workflowExplain(event.action) ||
    `${event.label || actionTitle(event.action)}正在按既定流程执行。`

  const actionMatches = !audit.action || !round?.action || audit.action === round.action
  const decision = actionMatches
    ? audit.decision_zh || (round?.action_zh ? `${round.action_zh}${rationale ? `：${rationale}` : ''}` : rationale)
    : round?.action_zh
      ? `${round.action_zh}${rationale ? `：${rationale}` : ''}`
      : rationale

  return {
    observation: audit.observation_zh || (legacyObservation && !/^第\s*\d+\s*轮/.test(legacyObservation) ? legacyObservation : undefined),
    analysis,
    decision: readable(decision, 260) || undefined,
    result: toolResult(event, round),
  }
}

function displayTitle(event: TimelineItem) {
  const status = String(event.status || '').toUpperCase()
  if (event.action === 'A09_RESOLVE') {
    if (status === 'ROLLBACK') return '回退原方案'
    if (status === 'KEEP') return '保留原方案'
    if (status === 'ACCEPT') return '采用候选方案'
  }
  return event.label || actionTitle(event.action)
}
</script>

<template>
  <div class="execution-journal">
    <div class="pane-head journal-head">
      <div class="section-heading"><span class="overline">执行记录</span></div>
      <h2>完整执行记录</h2>
      <p class="journal-intro">直接展示智能体每轮给出的观察、分析与决定；工具结果来自真实执行证据，程序数据统一收在“技术详情”里。</p>
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

    <div ref="journalList" class="journal-list" data-test="journal-list">
      <div v-if="!orderedEvents.length" class="journal-empty">
        <span aria-hidden="true">⌁</span>
        <h3>等待第一条记录</h3>
        <p>开始后，这里会记录智能体看到了什么、如何判断、决定做什么，以及工具实际返回了什么。</p>
      </div>

      <article
        v-for="(event, index) in orderedEvents"
        :key="event.id"
        class="journal-event-card"
        :class="{
          'is-failed': ['failed', 'error', 'blocked'].includes(event.status),
          'is-latest': index === orderedEvents.length - 1,
        }"
        :data-action="event.action || undefined"
      >
        <div class="event-rail" aria-hidden="true"><span class="event-dot" /><i /></div>
        <div class="event-content">
          <div class="event-meta"><span>{{ eventStatus(event.status) }}</span></div>
          <div class="event-title-row">
            <h3>{{ displayTitle(event) }}</h3>
            <time v-if="formatTime(event.occurred_at)">{{ formatTime(event.occurred_at) }}</time>
          </div>
          <p class="event-subtitle">{{ journalCopy(event).analysis }}</p>
          <p v-if="journalCopy(event).observation" class="event-support"><span>观察</span>{{ journalCopy(event).observation }}</p>
          <p v-if="journalCopy(event).decision" class="event-support"><span>决定</span>{{ journalCopy(event).decision }}</p>
          <p v-if="journalCopy(event).result" class="event-support is-result"><span>结果</span>{{ journalCopy(event).result }}</p>

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
.execution-journal { display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; overflow: hidden; }
.journal-head { flex: 0 0 auto; }
.section-heading { margin-bottom: 18px; }
.journal-intro { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.journal-status { display: flex; justify-content: space-between; gap: 8px; padding: 12px 0 16px; border-bottom: 1px solid var(--separator); color: var(--text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }
.journal-list { flex: 1 1 auto; min-width: 0; min-height: 0; overflow-x: hidden; overflow-y: auto; padding: 8px 2px 18px 0; scrollbar-gutter: stable; }
.journal-empty { padding: 48px 4px; text-align: center; }
.journal-empty > span { color: var(--text-tertiary); font-size: 40px; }
.journal-empty h3 { margin: 14px 0 10px; font-size: 16px; font-weight: 600; }
.journal-empty p { max-width: 230px; margin: auto; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.journal-event-card { display: grid; min-width: 0; grid-template-columns: 18px minmax(0, 1fr); gap: 10px; padding: 14px 0 16px; border-bottom: 1px solid var(--separator); }
.event-rail { display: flex; align-items: center; flex-direction: column; padding-top: 7px; }
.event-dot { width: 8px; height: 8px; flex: 0 0 auto; border: 2px solid #aeb1b8; border-radius: 50%; background: #fff; }
.event-rail i { width: 1px; flex: 1; min-height: 18px; margin-top: 7px; background: var(--separator); }
.journal-event-card:last-child .event-rail i { display: none; }
.is-latest .event-dot { border-color: var(--accent); box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.08); }
.is-failed .event-dot { border-color: var(--danger); }
.event-content { min-width: 0; max-width: 100%; overflow: hidden; }
.event-meta { color: var(--text-tertiary); font-size: 10px; font-weight: 650; letter-spacing: 0.03em; }
.event-title-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; min-width: 0; }
.event-title-row h3 { min-width: 0; margin: 4px 0 0; color: var(--text-primary); font-size: 14px; font-weight: 650; line-height: 1.4; overflow-wrap: anywhere; }
.event-title-row time { flex: 0 0 auto; color: var(--text-tertiary); font-size: 10px; font-variant-numeric: tabular-nums; }
.event-subtitle { margin: 7px 0 0; color: var(--text-primary); font-size: 12px; font-weight: 560; line-height: 1.65; overflow-wrap: anywhere; }
.event-support { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 6px; margin: 7px 0 0; color: var(--text-secondary); font-size: 11px; line-height: 1.55; overflow-wrap: anywhere; }
.event-support span { color: var(--text-tertiary); font-size: 10px; font-weight: 700; }
.event-support.is-result { color: var(--text-primary); }
.technical-details { max-width: 100%; margin-top: 10px; overflow: hidden; border-top: 1px solid rgba(220, 221, 227, 0.62); padding-top: 8px; }
.technical-details summary { display: flex; justify-content: space-between; cursor: pointer; list-style: none; color: var(--text-tertiary); font-size: 10px; font-weight: 650; }
.technical-details summary::-webkit-details-marker { display: none; }
.technical-details pre { max-width: 100%; max-height: 220px; margin: 9px 0 0; overflow-x: hidden; overflow-y: auto; border-radius: var(--radius-md); background: var(--surface-secondary); padding: 10px; color: var(--text-secondary); font-family: var(--mono); font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; word-break: break-word; white-space: pre-wrap; }
.inline-error { margin-top: 12px; border: 1px solid #f0c8c3; border-radius: var(--radius-md); background: var(--danger-soft); padding: 11px; color: var(--danger); font-size: 12px; }
.inline-error p { margin: 5px 0; line-height: 1.5; }
.text-button { border: 0; background: none; color: var(--accent-text); padding: 0; font: inherit; cursor: pointer; }
.blue-dot::before { display: inline-block; width: 6px; height: 6px; margin-right: 6px; border-radius: 50%; background: var(--accent); content: ''; }
</style>
