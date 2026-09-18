<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import { skillTitle } from '../skills/catalog'
import type { SkillUsageSummary } from '../types/skills'
import type { AgentLogSummary, ToolCallAudit } from '../types/api'
import GlassDialog from './GlassDialog.vue'
import { NumberTicker } from './ui'

const props = defineProps<{ open: boolean; taskId?: string | null }>()
const emit = defineEmits<{ close: [] }>()

const usage = ref<SkillUsageSummary | null>(null)
const agentLog = ref<AgentLogSummary | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const activeTab = ref<'skills' | 'tools'>('skills')
const snapshot = computed(() => {
  const hash = usage.value?.snapshot_sha256
  return hash ? `${hash.slice(0, 8)}…${hash.slice(-6)}` : null
})
const toolCalls = computed(() => agentLog.value?.rounds.flatMap((round) => round.tool_calls || []) || [])
const modelEvaluations = computed(() => toolCalls.value.reduce((sum, call) => sum + Number(call.metrics?.model_evaluations || 0), 0))
const toolsById = computed(() => {
  const grouped = new Map<string, { tool: ToolCallAudit; count: number; successCount: number; failureCount: number; rounds: Set<number> }>()
  for (const round of agentLog.value?.rounds || []) {
    for (const tool of round.tool_calls || []) {
      const succeeded = ['completed', 'succeeded', 'ACCEPT', 'KEEP', 'ROLLBACK'].includes(tool.status)
      const failed = ['failed', 'blocked'].includes(tool.status)
      const current = grouped.get(tool.tool_id)
      if (current) {
        current.count += 1
        if (succeeded) current.successCount += 1
        if (failed) current.failureCount += 1
        current.rounds.add(round.round_number)
      } else {
        grouped.set(tool.tool_id, {
          tool,
          count: 1,
          successCount: succeeded ? 1 : 0,
          failureCount: failed ? 1 : 0,
          rounds: new Set([round.round_number]),
        })
      }
    }
  }
  return [...grouped.values()]
})

async function loadUsage() {
  if (!props.taskId) {
    usage.value = null
    agentLog.value = null
    return
  }
  loading.value = true
  error.value = null
  try {
    const [skillUsage, log] = await Promise.all([
      api.getTaskSkillUsage(props.taskId),
      api.getAgentLog(props.taskId),
    ])
    usage.value = skillUsage
    agentLog.value = log
  } catch (err) {
    usage.value = null
    agentLog.value = null
    error.value = String((err as Error).message || err)
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.open, props.taskId] as const,
  ([open]) => {
    if (open) void loadUsage()
  },
  { immediate: true },
)
</script>

<template>
  <GlassDialog
    :open="open"
    size="wide"
    test-id="case-skill-usage"
    overline="案例回放"
    title="Agent 能力调用"
    labelled-by="case-skill-usage-title"
    @close="emit('close')"
  >
    <p v-if="loading" class="case-usage-muted">正在加载 Skills 与 Tools 调用记录…</p>
    <p v-else-if="error" class="case-usage-error" role="alert">{{ error }}</p>
    <p v-else-if="!usage" class="case-usage-muted">暂无 Skill Snapshot 或调用记录。</p>
    <template v-else>
      <section class="case-usage-overview" aria-label="使用概览">
        <div>
          <small>Skills</small>
          <strong><NumberTicker :value="usage.usage_by_skill.length" :decimal-places="0" :duration="560" /> <em>种</em></strong>
          <span>{{ usage.invocation_count }} 次调用</span>
        </div>
        <div>
          <small>Tools</small>
          <strong><NumberTicker :value="toolsById.length" :decimal-places="0" :duration="700" :delay="80" /> <em>种</em></strong>
          <span>{{ toolCalls.length }} 次调用</span>
        </div>
        <div>
          <small>模型计算</small>
          <strong><NumberTicker :value="modelEvaluations" :decimal-places="0" :duration="760" :delay="120" /> <em>次</em></strong>
        </div>
        <div>
          <small>Agent Decisions</small>
          <strong><NumberTicker :value="agentLog?.rounds.length || 0" :decimal-places="0" :duration="760" :delay="160" /> <em>轮</em></strong>
        </div>
      </section>

      <p v-if="snapshot" class="case-usage-snapshot">冻结快照 <code>{{ snapshot }}</code></p>
      <div class="case-usage-tabs" role="tablist" aria-label="能力调用类型">
        <button id="case-skills-tab" type="button" role="tab" :aria-selected="activeTab === 'skills'" aria-controls="case-skills-panel" @click="activeTab = 'skills'">Skills</button>
        <button id="case-tools-tab" type="button" role="tab" :aria-selected="activeTab === 'tools'" aria-controls="case-tools-panel" @click="activeTab = 'tools'">Tools</button>
      </div>

      <section v-show="activeTab === 'tools'" id="case-tools-panel" class="case-usage-section" role="tabpanel" aria-labelledby="case-tools-tab">
        <header>
          <h3 id="case-usage-tools-title">本次调用的执行工具</h3>
          <span>{{ toolsById.length }} 项</span>
        </header>
        <div v-if="toolsById.length" class="case-usage-records">
          <article v-for="row in toolsById" :key="row.tool.tool_id" class="case-usage-item">
            <div class="case-usage-item-main">
              <strong>{{ row.tool.tool_name_zh }}</strong>
              <small>{{ row.tool.tool_id }}</small>
            </div>
            <div class="case-usage-count"><NumberTicker :value="row.count" :decimal-places="0" :duration="520" /> <span>次调用</span></div>
            <p class="case-usage-contracts">
              <span>{{ row.tool.category }}</span>
              <span>成功 {{ row.successCount }}</span>
              <span>失败 {{ row.failureCount }}</span>
              <span>轮次 {{ [...row.rounds].join(' / ') }}</span>
              <span v-if="row.tool.metrics?.model_evaluations">模型计算 {{ row.tool.metrics.model_evaluations }} 次</span>
            </p>
          </article>
        </div>
        <p v-else class="case-usage-empty">本案例没有记录到 Tool 调用。</p>
      </section>
      <section v-show="activeTab === 'skills'" id="case-skills-panel" class="case-usage-section" role="tabpanel" aria-labelledby="case-skills-tab">
        <header>
          <h3 id="case-usage-skills-title">本次调用的技能</h3>
          <span>{{ usage.usage_by_skill.length }} 项</span>
        </header>
        <div v-if="usage.usage_by_skill.length" class="case-usage-records">
          <article v-for="row in usage.usage_by_skill" :key="row.skill_id" class="case-usage-item">
            <div class="case-usage-item-main">
              <strong>{{ skillTitle(row.skill_id) }}</strong>
              <small>{{ row.skill_id }}</small>
            </div>
            <div class="case-usage-count"><NumberTicker :value="row.invocation_count" :decimal-places="0" :duration="520" /> <span>次调用</span></div>
            <p v-if="row.output_contracts.length" class="case-usage-contracts">
              <span v-for="contract in row.output_contracts" :key="contract.contract">{{ contract.contract }} × {{ contract.count }}</span>
            </p>
          </article>
        </div>
        <p v-else class="case-usage-empty">本案例没有记录到实际 Skill 调用。</p>
      </section>

      <section v-if="usage.invocations.length" class="case-usage-section case-usage-timeline" aria-labelledby="case-usage-timeline-title">
        <header>
          <h3 id="case-usage-timeline-title">调用时间线</h3>
          <span>{{ usage.invocations.length }} 条</span>
        </header>
        <ol>
          <li v-for="(item, index) in usage.invocations" :key="`${item.decision_id || index}-${item.skill_id}`">
            <span class="case-usage-round">R{{ item.round_number ?? '-' }}</span>
            <div>
              <strong>{{ skillTitle(item.skill_id) }}</strong>
              <small>{{ item.output_contract || 'AgentDecision' }}<template v-if="item.action"> · {{ item.action }}</template></small>
            </div>
          </li>
        </ol>
      </section>
    </template>
  </GlassDialog>
</template>

<style scoped>
.case-usage-muted,
.case-usage-error {
  margin: 36px 0;
  color: var(--text-secondary);
  text-align: center;
}
.case-usage-error { color: var(--danger); }
.case-usage-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
  background: var(--surface-secondary);
}
.case-usage-overview > div { padding: 15px 16px; }
.case-usage-overview > div + div { border-left: 1px solid var(--separator); }
.case-usage-overview small,
.case-usage-snapshot,
.case-usage-section > header span,
.case-usage-item small,
.case-usage-contracts,
.case-usage-timeline small,
.case-usage-empty { color: var(--text-secondary); font-size: 12px; }
.case-usage-overview small { display: block; margin-bottom: 4px; }
.case-usage-overview > div > span { display: block; margin-top: 2px; color: var(--text-tertiary); font-size: 10px; }
.case-usage-overview strong { color: var(--text-primary); font-size: 26px; font-variant-numeric: tabular-nums; letter-spacing: -0.03em; }
.case-usage-overview em { color: var(--text-secondary); font-size: 13px; font-style: normal; font-weight: 500; letter-spacing: 0; }
.case-usage-snapshot { margin: -1px 0 8px; font-variant-numeric: tabular-nums; }
.case-usage-snapshot code { color: var(--text-tertiary); font-family: var(--mono); font-size: 11px; }
.case-usage-tabs { display: inline-flex; justify-self: start; overflow: hidden; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface-secondary); padding: 2px; }
.case-usage-tabs button { min-width: 84px; border: 0; border-radius: calc(var(--radius-sm) - 3px); background: transparent; padding: 7px 12px; color: var(--text-secondary); font: inherit; font-size: 12px; font-weight: 620; cursor: pointer; }
.case-usage-tabs button[aria-selected='true'] { background: var(--surface); color: var(--text-primary); box-shadow: 0 1px 4px color-mix(in srgb, var(--text-primary) 8%, transparent); }
.case-usage-tabs button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.case-usage-section { display: grid; gap: 6px; }
.case-usage-section > header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 8px 2px 2px; }
.case-usage-section h3 { margin: 0; color: var(--text-primary); font-size: 14px; font-weight: 600; }
.case-usage-records,
.case-usage-timeline ol { overflow: hidden; margin: 0; padding: 0; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface); list-style: none; }
.case-usage-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 16px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--separator);
}
.case-usage-item:last-child,
.case-usage-timeline li:last-child { border-bottom: 0; }
.case-usage-item-main { min-width: 0; }
.case-usage-item strong,
.case-usage-item small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.case-usage-item strong,
.case-usage-timeline strong { color: var(--text-primary); font-size: 13px; }
.case-usage-count { align-self: center; color: var(--text-primary); font-size: 17px; font-variant-numeric: tabular-nums; font-weight: 650; letter-spacing: -0.02em; white-space: nowrap; }
.case-usage-count span { color: var(--text-secondary); font-size: 11px; font-weight: 500; letter-spacing: 0; }
.case-usage-contracts { display: flex; flex-wrap: wrap; grid-column: 1 / -1; gap: 0 8px; margin: 1px 0 0; }
.case-usage-contracts span + span { padding-left: 8px; border-left: 1px solid var(--separator); }
.case-usage-empty { margin: 0; padding: 22px 14px; border: 1px dashed var(--separator); border-radius: var(--radius-sm); text-align: center; }
.case-usage-timeline li {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 10px;
  align-items: baseline;
  padding: 11px 14px;
  border-bottom: 1px solid var(--separator);
}
.case-usage-round { color: var(--accent-text); font-family: var(--mono); font-size: 11px; font-variant-numeric: tabular-nums; font-weight: 600; }
.case-usage-timeline small { display: block; margin-top: 2px; }
@media (max-width: 520px) {
  .case-usage-overview { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .case-usage-overview > div:nth-child(3) { border-top: 1px solid var(--separator); border-left: 0; }
  .case-usage-overview > div:nth-child(4) { border-top: 1px solid var(--separator); }
  .case-usage-overview > div { padding: 13px; }
  .case-usage-overview strong { font-size: 23px; }
  .case-usage-item { padding: 11px 12px; }
}
</style>
