<script setup lang="ts">
import { PhCaretDown, PhCaretUp } from '@phosphor-icons/vue'
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import { skillTitle } from '../skills/catalog'
import type { AgentRoundLogItem, ToolCallAudit } from '../types/api'
import EvidenceCard from './EvidenceCard.vue'
import ExperimentStats from './ExperimentStats.vue'
import ToolExecutionCard from './ToolExecutionCard.vue'

const props = defineProps<{
  taskId?: string | null
  eventCount: number
  currentAction?: string | null
  currentRoundNumber?: number | null
  running?: boolean
}>()

const rounds = ref<AgentRoundLogItem[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const expanded = ref(false)
let serial = 0

async function load() {
  const requestId = ++serial
  if (!props.taskId) {
    rounds.value = []
    return
  }
  loading.value = true
  error.value = null
  try {
    const response = await api.getAgentLog(props.taskId)
    if (requestId === serial) rounds.value = response.rounds || []
  } catch (err) {
    if (requestId === serial) error.value = String((err as Error).message || err)
  } finally {
    if (requestId === serial) loading.value = false
  }
}

watch(() => [props.taskId, props.eventCount, props.currentAction, props.currentRoundNumber] as const, () => void load(), { immediate: true })

const currentRound = computed(() => {
  if (props.currentRoundNumber) {
    return rounds.value.find((round) => round.round_number === props.currentRoundNumber) || null
  }
  return rounds.value.at(-1) || null
})

function auditPayload(round: AgentRoundLogItem | null) {
  const raw = round?.llm_output?.trim()
  if (!raw) return {} as Record<string, unknown>
  const start = raw.indexOf('{')
  const end = raw.lastIndexOf('}')
  if (start < 0 || end <= start) return {}
  try { return JSON.parse(raw.slice(start, end + 1)) as Record<string, unknown> } catch { return {} }
}

const audit = computed(() => auditPayload(currentRound.value))
const observation = computed(() => String(audit.value.observation_zh || currentRound.value?.input_summary_zh || '等待 Agent 观察当前世界状态。'))
const analysis = computed(() => String(audit.value.analysis_zh || currentRound.value?.judgment_zh || currentRound.value?.rationale_summary || '尚未形成新的分析摘要。'))
const decision = computed(() => String(audit.value.decision_zh || currentRound.value?.action_zh || '等待下一步决策。'))
const paramGroups = computed(() => Array.isArray(audit.value.param_groups) ? audit.value.param_groups.map(String).join(' / ') : '')
const objective = computed(() => typeof audit.value.objective === 'string' ? audit.value.objective : '')
const skills = computed(() => (currentRound.value?.activated_skill_ids || []).map((id) => ({ id, title: skillTitle(id) })))
const tools = computed<ToolCallAudit[]>(() => {
  return currentRound.value?.tool_calls || []
})
const evidence = computed(() => currentRound.value?.evidence_summary || (currentRound.value?.tool_status ? {
  action: currentRound.value.action,
  status: currentRound.value.tool_status,
  observations: currentRound.value.tool_observations,
  metrics: currentRound.value.tool_metrics,
} : null))
const activitySummary = computed(() => currentRound.value?.action_zh || (loading.value ? '正在读取活动记录' : '等待 Agent 开始行动'))
</script>

<template>
  <section
    class="agent-activity-panel"
    :class="{ 'is-expanded': expanded }"
    aria-labelledby="agent-activity-title"
    data-test="agent-activity-panel"
    @keydown.esc="expanded = false"
  >
    <header class="activity-drawer-handle">
      <div class="activity-drawer-summary">
        <span>AGENT ACTIVITY</span>
        <div class="activity-drawer-subtitle">
          <strong id="agent-activity-title">Agent 当前活动</strong>
          <small>{{ activitySummary }}</small>
        </div>
      </div>
      <span v-if="running" class="activity-live">正在更新</span>
      <button
        type="button"
        class="activity-toggle"
        data-test="activity-toggle"
        :aria-expanded="expanded"
        aria-controls="agent-activity-content"
        :aria-label="expanded ? '收起 Agent 当前活动' : '展开 Agent 当前活动'"
        @click="expanded = !expanded"
      >
        <PhCaretUp v-if="!expanded" :size="16" weight="bold" aria-hidden="true" />
        <PhCaretDown v-else :size="16" weight="bold" aria-hidden="true" />
      </button>
    </header>

    <div id="agent-activity-content" class="activity-drawer-body" :aria-hidden="!expanded" :inert="!expanded">
      <ExperimentStats :rounds="rounds" />
      <div class="activity-body-scroll">
        <div class="activity-content-group">
          <div class="activity-head">
            <div>
              <span>EXECUTION TRACE</span>
              <p>专业能力辅助判断，执行工具操作实验环境，Evidence 再进入下一轮决策。</p>
            </div>
          </div>
          <p v-if="error" class="activity-error" role="alert">活动记录读取失败：{{ error }}</p>
          <div v-else-if="loading && !currentRound" class="activity-loading">正在读取 Agent 活动…</div>
          <div v-else class="activity-chain">
            <article class="activity-step observation-step">
              <span class="step-number">01</span><small>OBSERVATION</small><h4>观察</h4>
              <div class="activity-step-copy">
                <p>{{ observation }}</p>
                <p class="secondary-copy">{{ analysis }}</p>
              </div>
            </article>
            <article class="activity-step skill-step">
              <span class="step-number">02</span><small>SKILLS</small><h4>专业能力</h4>
              <div class="activity-step-copy">
                <ul v-if="skills.length"><li v-for="skill in skills" :key="skill.id"><strong>{{ skill.title }}</strong><span>{{ skill.id }}</span></li></ul>
                <p v-else>本轮没有记录到 Skill 激活。</p>
              </div>
            </article>
            <article class="activity-step decision-step">
              <span class="step-number">03</span><small>AGENT DECISION</small><h4>Agent 决策</h4>
              <div class="activity-step-copy">
                <p>{{ decision }}</p>
                <dl v-if="currentRound">
                  <div v-if="currentRound.hypothesis_zh"><dt>假设</dt><dd>{{ currentRound.hypothesis_zh }}</dd></div>
                  <div v-if="currentRound.strategy_id"><dt>策略</dt><dd>{{ currentRound.strategy_id }}</dd></div>
                  <div v-if="paramGroups"><dt>参数组</dt><dd>{{ paramGroups }}</dd></div>
                  <div v-if="objective"><dt>目标</dt><dd>{{ objective }}</dd></div>
                </dl>
              </div>
            </article>
            <article class="activity-step tool-step">
              <span class="step-number">04</span><small>TOOLS</small><h4>执行工具</h4>
              <div class="activity-step-copy">
                <div v-if="tools.length" class="activity-tools"><ToolExecutionCard v-for="tool in tools" :key="tool.tool_call_id || tool.tool_id" :tool-call="tool" compact :active="tool.status === 'running'" /></div>
                <p v-else>等待 Agent 调用执行工具。</p>
              </div>
            </article>
            <article class="activity-step evidence-step">
              <span class="step-number">05</span><small>EVIDENCE</small><h4>新证据</h4>
              <div class="activity-step-copy">
                <EvidenceCard :evidence="evidence" />
              </div>
            </article>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-activity-panel { --activity-handle-height: 58px; position: absolute; inset: 0; z-index: var(--layer-inspector); display: flex; flex-direction: column; min-width: 0; overflow: hidden; border-top: 1px solid var(--border); background: var(--surface-secondary); transform: translateY(calc(100% - var(--activity-handle-height))); transition: transform 260ms var(--ease); container-type: inline-size; }
.agent-activity-panel.is-expanded { transform: translateY(0); }
.activity-drawer-handle { display: flex; flex: 0 0 var(--activity-handle-height); align-items: center; gap: 12px; padding: 8px 14px 8px 16px; border-bottom: 1px solid transparent; background: var(--glass-thick); }
.is-expanded .activity-drawer-handle { border-bottom-color: var(--separator); }
.activity-drawer-summary { display: grid; grid-template-columns: minmax(0, 1fr); align-items: center; gap: 2px 10px; min-width: 0; flex: 1; }
.activity-drawer-summary > span { color: var(--text-tertiary); font-size: 11px; font-weight: 800; letter-spacing: .12em; }
.activity-drawer-subtitle { display: flex; min-width: 0; align-items: baseline; gap: 8px; }
.activity-drawer-subtitle > strong { flex: 0 0 auto; color: var(--text-primary); font-size: 12px; white-space: nowrap; }
.activity-drawer-subtitle > small { min-width: 0; overflow: hidden; color: var(--text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.activity-toggle { display: grid; flex: 0 0 auto; width: 34px; height: 34px; place-items: center; border: 1px solid var(--separator); border-radius: 50%; background: var(--surface); box-shadow: var(--shadow-xs); color: var(--text-primary); cursor: pointer; }
.activity-toggle:hover { border-color: color-mix(in srgb, var(--accent) 38%, var(--separator)); background: var(--accent-soft); color: var(--accent-text); }
.activity-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.activity-drawer-body { display: grid; grid-template-rows: auto minmax(0, 1fr); flex: 1; min-height: 0; overflow: hidden; }
.activity-drawer-body > .experiment-stats { margin: 12px 16px 0; }
.activity-body-scroll { display: flex; min-height: 0; flex-direction: column; overflow: auto; padding: 16px; scrollbar-gutter: stable; overscroll-behavior: contain; }
.activity-content-group { display: flex; flex: 1 1 auto; min-height: 0; flex-direction: column; gap: 12px; }
.activity-head { display: flex; flex: 0 0 auto; align-items: flex-start; justify-content: space-between; gap: 14px; }
.activity-head > div { min-width: 0; }
.activity-head span, .activity-step > small { color: var(--text-tertiary); font-size: 9px; font-weight: 750; letter-spacing: .07em; }
.activity-head h3 { margin: 3px 0 0; color: var(--text-primary); font-size: 17px; }
.activity-head p { margin: 4px 0 0; color: var(--text-secondary); font-size: 11px; line-height: 1.5; }
.activity-live { flex: 0 0 auto; border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--separator)); border-radius: 999px; background: var(--accent-soft); padding: 5px 8px; color: var(--accent-text) !important; letter-spacing: 0 !important; }
.activity-chain { display: grid; flex: 1 1 auto; min-height: 0; grid-template-columns: repeat(5, minmax(0, 1fr)); grid-template-rows: minmax(110px, 1fr); grid-auto-rows: minmax(110px, 1fr); align-content: stretch; gap: 8px; min-width: 0; }
.activity-step { position: relative; display: grid; min-width: 0; min-height: 0; grid-template-rows: auto auto auto minmax(0, 1fr); align-content: start; overflow: hidden; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface); padding: 11px; }
.activity-step-copy { display: grid; min-height: 0; align-content: start; gap: 6px; overflow-y: auto; scrollbar-gutter: stable; }
.activity-step:not(:last-child)::after { position: absolute; top: 19px; right: -7px; width: 5px; height: 5px; border-top: 1px solid var(--text-tertiary); border-right: 1px solid var(--text-tertiary); transform: rotate(45deg); content: ''; }
.step-number { float: right; color: var(--text-tertiary); font-family: var(--mono); font-size: 9px; }
.activity-step h4 { margin: 3px 0 8px; color: var(--text-primary); font-size: 13px; }
.activity-step > p { margin: 0; color: var(--text-secondary); font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; }
.activity-step .secondary-copy { margin-top: 6px; color: var(--text-tertiary); }
.activity-step ul { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
.activity-step li { display: grid; gap: 1px; border-radius: var(--radius-xs); background: var(--surface-secondary); padding: 6px; }
.activity-step li strong { color: var(--text-primary); font-size: 10px; }
.activity-step li span { color: var(--text-tertiary); font-family: var(--mono); font-size: 8px; overflow-wrap: anywhere; }
.activity-step dl { display: grid; gap: 5px; margin: 8px 0 0; }
.activity-step dl div { display: grid; gap: 1px; }
.activity-step dt { color: var(--text-tertiary); font-size: 8px; }
.activity-step dd { margin: 0; color: var(--text-primary); font-size: 9px; overflow-wrap: anywhere; }
.activity-tools { display: grid; gap: 6px; }
.tool-step, .evidence-step { padding: 8px; }
.tool-step > h4, .evidence-step > h4, .tool-step > small, .evidence-step > small { margin-left: 3px; }
.activity-loading, .activity-error { margin: 0; border-radius: var(--radius-sm); background: var(--surface); padding: 18px; color: var(--text-secondary); font-size: 11px; text-align: center; }
.activity-error { color: var(--danger); }
.observation-step { --step-color: var(--trace-observation); }
.skill-step { --step-color: var(--trace-skill); }
.decision-step { --step-color: var(--trace-decision); }
.tool-step { --step-color: var(--trace-tool); }
.evidence-step { --step-color: var(--trace-evidence); }
.activity-step { border-top: 3px solid var(--step-color); padding: 14px; }
.activity-step > small, .activity-step h4 { color: var(--step-color); }
.activity-step > p, .activity-step dd, .activity-step li strong { font-size: 12px; line-height: 1.65; }
.activity-step dt, .activity-step li span, .activity-step > small { font-size: 10px; }
.skill-step li { background: color-mix(in srgb, var(--trace-skill) 8%, var(--surface)); }
@container (max-width: 1000px) { .activity-chain { grid-template-columns: repeat(2, minmax(0, 1fr)); } .activity-step:last-child { grid-column: 1 / -1; } .activity-step::after { display: none; } }
@media (max-width: 1200px) { .activity-chain { grid-template-columns: 1fr 1fr; } .activity-step:last-child { grid-column: 1 / -1; } .activity-step::after { display: none; } }
@container (max-width: 520px) { .activity-drawer-handle { padding-inline: 12px; } .activity-drawer-subtitle { gap: 4px 8px; } .activity-live { display: none; } .activity-body-scroll { padding: 12px; } .activity-chain { grid-template-columns: 1fr; } .activity-step:last-child { grid-column: auto; } }
@media (prefers-reduced-transparency: reduce) { .agent-activity-panel { background: var(--surface-secondary); } }
@media (prefers-reduced-motion: reduce) { .agent-activity-panel { transition: none; } }
</style>
