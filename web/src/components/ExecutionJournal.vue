<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { api } from '../api/client'
import { actionTitle } from '../demo/stages'
import { WORKFLOW } from '../generated/workflow'
import { outputContractLabel, skillTitle } from '../skills/catalog'
import { toolForAction } from '../tools/catalog'
import { currentActionId } from '../workflow/legacyActions'
import type { AgentRoundLogItem, TimelineItem, ToolCallAudit } from '../types/api'

const props = defineProps<{
  taskId?: string | null
  events: TimelineItem[]
  running: boolean
  completed: boolean
  failed: boolean
  elapsed: string
  currentAction?: string | null
  error?: string | null
}>()

const emit = defineEmits<{ refresh: [] }>()
const agentRounds = ref<AgentRoundLogItem[]>([])
const journalList = ref<HTMLElement | null>(null)
let requestSerial = 0

const orderedEvents = computed(() =>
  [...props.events].sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at)),
)

function parsedTime(value?: string | null) {
  if (!value) return Number.NaN
  return Date.parse(value)
}

const currentWorkingEvent = computed<TimelineItem | null>(() => {
  if (!props.running || !props.currentAction) return null
  const last = orderedEvents.value.at(-1)
  if (last?.action === props.currentAction && String(last.status).toLowerCase() === 'running') return null

  const round = [...agentRounds.value].reverse().find((item) => item.action === props.currentAction)
  const lastTime = parsedTime(last?.occurred_at)
  const roundTime = parsedTime(round?.occurred_at)
  if (
    last?.action === props.currentAction &&
    (Number.isNaN(roundTime) || (!Number.isNaN(lastTime) && roundTime <= lastTime))
  ) {
    return null
  }

  return {
    id: `working-${props.currentAction}-${round?.round_number || 'current'}`,
    occurred_at: round?.occurred_at || last?.occurred_at || new Date().toISOString(),
    label: `正在${actionTitle(props.currentAction)}`,
    status: 'running',
    action: props.currentAction,
    evidence_id: null,
    details: {},
  }
})

const displayEvents = computed(() =>
  currentWorkingEvent.value ? [...orderedEvents.value, currentWorkingEvent.value] : orderedEvents.value,
)
const latestEventId = computed(() => displayEvents.value.at(-1)?.id || '')
const statusLabel = computed(() =>
  props.running ? '运行中' : props.completed ? '已完成' : props.failed ? '已受阻' : '等待执行',
)

function scrollToLatest() {
  const container = journalList.value
  if (!container) return
  container.scrollTop = container.scrollHeight
}

watch(
  [() => props.taskId, () => props.events.length, () => props.currentAction],
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
  KEEP: '继续率定',
  ROLLBACK: '回退候选',
  blocked: '已受阻',
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

function observationValue(round: AgentRoundLogItem | null, key: string) {
  const prefix = `${key}=`
  const raw = (round?.tool_observations || []).find((item) => item.startsWith(prefix))
  return raw ? raw.slice(prefix.length).trim() : ''
}

function workflowExplain(action: string | null) {
  if (!action) return ''
  const item = WORKFLOW.actions[currentActionId(action) as keyof typeof WORKFLOW.actions]
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

function optimizerLabel(value: string) {
  if (value === 'dds') return 'DDS'
  if (value === 'sce-ua') return 'SCE-UA'
  if (value === 'random-search') return 'Random'
  return value
}

function calibrationTags(event: TimelineItem) {
  const round = matchingRound(event)
  const tags: string[] = []
  if (event.action === 'A05_OPTIMIZE') {
    const optimizer = observationValue(round, 'optimizer')
    const budget = observationValue(round, 'evaluation_budget')
    const evaluations = observationValue(round, 'model_evaluations')
    if (optimizer && optimizer !== '-') tags.push(optimizerLabel(optimizer))
    if (budget && budget !== '0') tags.push(`预算 ${budget}`)
    if (evaluations && evaluations !== '0') tags.push(`模型运行 ${evaluations}`)
  }
  if (event.action === 'A06_GATE' || event.action === 'A07_RESOLVE') {
    const adoption = observationValue(round, 'adoption_status')
    const qualification = observationValue(round, 'qualification_status')
    const adopted = observationValue(round, 'candidate_adopted')
    if (adoption === 'ADOPT' || adopted === 'true') tags.push('已采用')
    else if (adoption === 'REJECT') tags.push('已拒绝')
    else if (adoption === 'KEEP') tags.push('未替换')
    if (qualification === 'QUALIFIED') tags.push('已达标')
    else if (qualification === 'UNQUALIFIED') tags.push('未达标')
    else if (qualification === 'NOT_EVALUATED') tags.push('待资格评价')
  }
  return [...new Set(tags)]
}

function eventStatus(event: TimelineItem) {
  const round = matchingRound(event)
  if (event.action === 'A07_RESOLVE' && observationValue(round, 'candidate_adopted') === 'true') {
    return observationValue(round, 'qualification_status') === 'QUALIFIED' ? '采用并达标' : '采用并继续率定'
  }
  return STATUS_LABELS[event.status] || event.status || '执行记录'
}

function toolResult(event: TimelineItem, round: AgentRoundLogItem | null) {
  const status = String(event.status || '').toUpperCase()
  const adoption = observationValue(round, 'adoption_status')
  const qualification = observationValue(round, 'qualification_status')
  const adopted = observationValue(round, 'candidate_adopted') === 'true'
  if (status === 'RUNNING') return '工具正在执行，完成后会自动更新结果。'
  if (event.action === 'A05_OPTIMIZE') {
    const optimizer = optimizerLabel(observationValue(round, 'optimizer'))
    const evaluations = observationValue(round, 'model_evaluations')
    if (optimizer && evaluations && evaluations !== '0') return `${optimizer} 完成 ${evaluations} 次有效模型运行并生成候选方案。`
  }
  if (event.action === 'A06_GATE') {
    if (adoption === 'ADOPT' && qualification === 'QUALIFIED') return '候选优于当前方案，并且已经达到资格条件。'
    if (adoption === 'ADOPT') return '候选值得采用为新的工作基线，但尚未达到最终资格条件。'
    if (adoption === 'REJECT') return '候选触发保护条件，本轮实验被拒绝。'
    if (adoption === 'KEEP') return '候选改善幅度不足，当前工作方案保持不变。'
  }
  if (event.action === 'A07_RESOLVE' && adopted) {
    return qualification === 'QUALIFIED'
      ? '候选已成为当前方案并达到资格条件，可以进入冻结与回放。'
      : '候选已成为新的当前方案，但尚未达标；下一轮将基于新基线重新诊断。'
  }
  if (status === 'ROLLBACK') return '本次候选已撤销，当前方案恢复到回退前状态。'
  if (status === 'KEEP') return '当前工作方案保持不变，将根据新证据继续诊断。'
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

function activatedSkills(event: TimelineItem): Array<{ id: string; title: string; contract: string | null }> {
  const round = matchingRound(event)
  const ids = (round?.activated_skill_ids || []).filter(Boolean)
  const audits = round?.activated_skills_audit || []
  return ids.map((id) => {
    const audit = audits.find((item) => item.skill_id === id)
    return {
      id,
      title: skillTitle(id),
      contract: outputContractLabel(audit?.output_contract),
    }
  })
}

type DisplayToolCall = ToolCallAudit & { descriptionZh?: string; algorithm?: string; result?: string }

function toolCalls(event: TimelineItem): DisplayToolCall[] {
  const round = matchingRound(event)
  if (round?.tool_calls?.length) {
    return round.tool_calls.map((call) => ({ ...call, result: toolResult(event, round) }))
  }
  const descriptor = toolForAction(event.action)
  if (!descriptor) return []
  const rawStatus = String(round?.tool_status || event.status || 'pending').toLowerCase()
  const status = rawStatus === 'succeeded' || rawStatus === 'success' ? 'completed' : rawStatus
  const optimizer = event.action === 'A05_OPTIMIZE' ? observationValue(round, 'optimizer') : ''
  return [{
    action: descriptor.action,
    tool_id: descriptor.id,
    tool_name_zh: descriptor.nameZh,
    category: descriptor.category,
    status,
    descriptionZh: descriptor.descriptionZh,
    algorithm: optimizer && optimizer !== '-' ? optimizerLabel(optimizer) : undefined,
    evidence_id: event.evidence_id,
    metrics: round?.tool_metrics || {},
    result: toolResult(event, round),
  }]
}

function toolStatusLabel(status: string) {
  return STATUS_LABELS[status] || STATUS_LABELS[status.toLowerCase()] || status
}

function compactObject(value?: Record<string, unknown>) {
  if (!value || !Object.keys(value).length) return ''
  return Object.entries(value)
    .slice(0, 4)
    .map(([key, item]) => `${key}: ${String(item)}`)
    .join('；')
}

function displayTitle(event: TimelineItem) {
  const status = String(event.status || '').toUpperCase()
  const round = matchingRound(event)
  if (currentActionId(event.action) === 'A07_RESOLVE') {
    const adopted = observationValue(round, 'candidate_adopted') === 'true'
    const qualification = observationValue(round, 'qualification_status')
    if (adopted && qualification === 'QUALIFIED') return '采用候选并通过资格评价'
    if (adopted) return '采用候选，继续率定'
    if (status === 'ROLLBACK') return '回退候选方案'
    if (status === 'KEEP') return '保持当前方案'
    if (status === 'ACCEPT') return '采用候选方案'
  }
  if (currentActionId(event.action) === 'A06_GATE') return '候选采用与资格评价'
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
      <div v-if="!displayEvents.length" class="journal-empty">
        <span aria-hidden="true">⌁</span>
        <h3>等待第一条记录</h3>
        <p>开始后，这里会记录智能体看到了什么、如何判断、决定做什么，以及工具实际返回了什么。</p>
      </div>

      <article
        v-for="(event, index) in displayEvents"
        :key="event.id"
        class="journal-event-card"
        :class="{
          'is-failed': ['failed', 'error', 'blocked'].includes(event.status),
          'is-latest': running && event.status === 'running' && index === displayEvents.length - 1,
        }"
        :data-action="event.action || undefined"
      >
        <div class="event-rail" aria-hidden="true"><span class="event-dot" /><i /></div>
        <div class="event-content">
          <div class="event-meta"><span>{{ eventStatus(event) }}</span></div>
          <div class="event-title-row">
            <h3>{{ displayTitle(event) }}</h3>
            <time v-if="formatTime(event.occurred_at)">{{ formatTime(event.occurred_at) }}</time>
          </div>
          <div v-if="calibrationTags(event).length" class="calibration-tags" aria-label="率定实验状态">
            <span v-for="tag in calibrationTags(event)" :key="tag">{{ tag }}</span>
          </div>
          <p class="event-subtitle">{{ journalCopy(event).analysis }}</p>
          <p v-if="journalCopy(event).observation" class="event-support"><span>观察</span>{{ journalCopy(event).observation }}</p>
          <p v-if="journalCopy(event).decision" class="event-support"><span>决定</span>{{ journalCopy(event).decision }}</p>
          <p v-if="journalCopy(event).result" class="event-support is-result"><span>结果</span>{{ journalCopy(event).result }}</p>

          <div class="capability-disclosures">
            <details
              v-if="toolCalls(event).length"
              class="capability-details tool-details"
              data-test="tool-calls"
            >
              <summary>
                <span class="disclosure-kind">执行工具 <small>TOOL</small></span>
                <span class="disclosure-preview">{{ toolCalls(event).map((tool) => tool.algorithm || tool.tool_name_zh).join('、') }}</span>
                <span class="disclosure-count">{{ toolCalls(event).length }} 个</span>
                <span class="disclosure-chevron" aria-hidden="true">›</span>
              </summary>
              <ul class="tool-call-list">
                <li v-for="tool in toolCalls(event)" :key="tool.tool_call_id || tool.tool_id">
                  <div class="call-heading">
                    <div>
                      <strong>{{ tool.tool_name_zh }}</strong>
                      <small>{{ tool.algorithm || tool.tool_id }}</small>
                    </div>
                    <span class="call-status" :class="`is-${tool.status}`">{{ toolStatusLabel(tool.status) }}</span>
                  </div>
                  <p v-if="tool.descriptionZh">{{ tool.descriptionZh }}</p>
                  <dl v-if="compactObject(tool.input_summary) || compactObject(tool.output_summary) || tool.result">
                    <div v-if="compactObject(tool.input_summary)"><dt>输入</dt><dd>{{ compactObject(tool.input_summary) }}</dd></div>
                    <div v-if="compactObject(tool.output_summary)"><dt>输出</dt><dd>{{ compactObject(tool.output_summary) }}</dd></div>
                    <div v-else-if="tool.result"><dt>结果</dt><dd>{{ tool.result }}</dd></div>
                  </dl>
                </li>
              </ul>
            </details>

            <details
              v-if="activatedSkills(event).length"
              class="capability-details skill-details"
              data-test="activated-skills"
            >
              <summary>
                <span class="disclosure-kind">专业能力 <small>SKILL</small></span>
                <span class="disclosure-preview">{{ activatedSkills(event).map((skill) => skill.title).join('、') }}</span>
                <span class="disclosure-count">{{ activatedSkills(event).length }} 个</span>
                <span class="disclosure-chevron" aria-hidden="true">›</span>
              </summary>
              <ul class="skill-chip-list">
                <li v-for="skill in activatedSkills(event)" :key="skill.id">
                  <span class="skill-chip-title">{{ skill.title }}</span>
                  <small class="skill-chip-id">{{ skill.id }}</small>
                  <span v-if="skill.contract" class="skill-chip-contract">{{ skill.contract }}</span>
                </li>
              </ul>
            </details>
          </div>

          <details v-if="Object.keys(event.details).length" class="technical-details">
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
.journal-list { flex: 1 1 auto; min-width: 0; min-height: 0; overflow-x: hidden; overflow-y: auto; padding: 8px 2px 18px 0; }
.journal-empty { padding: 48px 4px; text-align: center; }
.journal-empty > span { color: var(--text-tertiary); font-size: 40px; }
.journal-empty h3 { margin: 14px 0 10px; font-size: 16px; font-weight: 600; }
.journal-empty p { max-width: 230px; margin: auto; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.journal-event-card { display: grid; min-width: 0; grid-template-columns: 18px minmax(0, 1fr); gap: 10px; padding: 14px 0 16px; border-bottom: 1px solid var(--separator); }
.event-rail { display: flex; align-items: center; flex-direction: column; padding-top: 7px; }
.event-dot { width: 8px; height: 8px; flex: 0 0 auto; border: 2px solid var(--stage-mark); border-radius: 50%; background: var(--surface); }
.event-rail i { width: 1px; flex: 1; min-height: 18px; margin-top: 7px; background: var(--separator); }
.journal-event-card:last-child .event-rail i { display: none; }
.is-latest .event-dot { border-color: var(--accent); box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.08); }
.is-latest .event-meta { color: var(--accent-text); }
.is-failed .event-dot { border-color: var(--danger); box-shadow: none; }
.event-content { min-width: 0; max-width: 100%; overflow: hidden; }
.event-meta { color: var(--text-tertiary); font-size: 10px; font-weight: 650; letter-spacing: 0.03em; }
.event-title-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; min-width: 0; }
.event-title-row h3 { min-width: 0; margin: 4px 0 0; color: var(--text-primary); font-size: 14px; font-weight: 650; line-height: 1.4; overflow-wrap: anywhere; }
.event-title-row time { flex: 0 0 auto; color: var(--text-tertiary); font-size: 10px; font-variant-numeric: tabular-nums; }
.calibration-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.calibration-tags span {
  border: 1px solid var(--separator);
  border-radius: var(--radius-xs, 6px);
  background: var(--surface-secondary);
  padding: 2px 7px;
  color: var(--text-secondary);
  font-size: 9px;
  font-weight: 650;
  line-height: 1.4;
}
.capability-disclosures { display: grid; gap: 6px; margin-top: 10px; }
.capability-details { overflow: hidden; border: 1px solid var(--separator); border-radius: var(--radius-sm, 10px); background: var(--surface-secondary); }
.capability-details summary { display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; gap: 8px; min-height: 36px; padding: 7px 9px; cursor: pointer; list-style: none; color: var(--text-secondary); }
.capability-details summary::-webkit-details-marker { display: none; }
.capability-details summary:hover { background: color-mix(in srgb, var(--surface) 54%, transparent); }
.capability-details summary:active { transform: translateY(1px); }
.capability-details summary:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.capability-details[open] summary { border-bottom: 1px solid var(--separator); }
.disclosure-kind { color: var(--text-primary); font-size: 11px; font-weight: 680; white-space: nowrap; }
.disclosure-kind small { margin-left: 4px; color: var(--text-tertiary); font-size: 8px; font-weight: 700; letter-spacing: 0.05em; }
.tool-details .disclosure-kind small { color: var(--accent-text); }
.disclosure-preview { min-width: 0; overflow: hidden; color: var(--text-tertiary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.disclosure-count { color: var(--text-tertiary); font-size: 9px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.disclosure-chevron { color: var(--text-tertiary); font-size: 18px; line-height: 1; transition: transform 160ms ease; }
.capability-details[open] .disclosure-chevron { transform: rotate(90deg); }
.tool-call-list { display: grid; gap: 7px; margin: 0; padding: 8px; list-style: none; }
.tool-call-list li { border-radius: var(--radius-xs, 6px); background: var(--surface); padding: 8px; }
.call-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.call-heading > div { display: grid; min-width: 0; gap: 2px; }
.call-heading strong { color: var(--text-primary); font-size: 11px; }
.call-heading small { color: var(--text-tertiary); font-family: var(--mono); font-size: 9px; overflow-wrap: anywhere; }
.call-status { flex: 0 0 auto; color: var(--text-secondary); font-size: 9px; font-weight: 650; }
.call-status.is-running { color: var(--accent-text); }
.call-status.is-failed, .call-status.is-error, .call-status.is-blocked { color: var(--danger); }
.tool-call-list p { margin: 6px 0 0; color: var(--text-secondary); font-size: 10px; line-height: 1.5; }
.tool-call-list dl { display: grid; gap: 5px; margin: 7px 0 0; }
.tool-call-list dl div { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 6px; }
.tool-call-list dt { color: var(--text-tertiary); font-size: 9px; font-weight: 700; }
.tool-call-list dd { margin: 0; color: var(--text-secondary); font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; }
.skill-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin: 0;
  padding: 8px;
  list-style: none;
}
.skill-chip-list li {
  display: grid;
  gap: 2px;
  max-width: 100%;
  border: 1px solid var(--separator);
  border-radius: var(--radius-xs, 6px);
  background: var(--surface);
  padding: 5px 8px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.skill-chip-title {
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 650;
}
.skill-chip-id {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: 10px;
}
.skill-chip-contract {
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 600;
}
.event-subtitle { margin: 7px 0 0; color: var(--text-primary); font-size: 12px; font-weight: 560; line-height: 1.65; overflow-wrap: anywhere; }
.event-support { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 6px; margin: 7px 0 0; color: var(--text-secondary); font-size: 11px; line-height: 1.55; overflow-wrap: anywhere; }
.event-support span { color: var(--text-tertiary); font-size: 10px; font-weight: 700; }
.event-support.is-result { color: var(--text-primary); }
.technical-details { max-width: 100%; margin-top: 10px; overflow: hidden; border-top: 1px solid var(--separator); padding-top: 8px; }
.technical-details summary { display: flex; justify-content: space-between; cursor: pointer; list-style: none; color: var(--text-tertiary); font-size: 10px; font-weight: 650; }
.technical-details summary::-webkit-details-marker { display: none; }
.technical-details pre { max-width: 100%; max-height: 220px; margin: 9px 0 0; overflow: auto; border-radius: var(--radius-md); background: var(--surface-secondary); padding: 10px; color: var(--text-secondary); font-family: var(--mono); font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; word-break: break-word; white-space: pre-wrap; }
.inline-error { margin-top: 12px; border: 1px solid var(--danger-edge); border-radius: var(--radius-md); background: var(--danger-soft); padding: 11px; color: var(--danger); font-size: 12px; }
.inline-error p { margin: 5px 0; line-height: 1.5; }
.text-button { border: 0; background: none; color: var(--accent-text); padding: 0; font: inherit; cursor: pointer; }
.blue-dot::before { display: inline-block; width: 6px; height: 6px; margin-right: 6px; border-radius: 50%; background: var(--accent); content: ''; }
@media (prefers-reduced-motion: reduce) { .disclosure-chevron { transition: none; } }
@media (max-width: 520px) {
  .capability-details summary { grid-template-columns: minmax(0, 1fr) auto auto; }
  .disclosure-preview { display: none; }
}
</style>
