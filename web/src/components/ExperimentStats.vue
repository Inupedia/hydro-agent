<script setup lang="ts">
import { computed } from 'vue'
import type { AgentRoundLogItem } from '../types/api'

const props = defineProps<{ rounds: AgentRoundLogItem[] }>()
const skillCount = computed(() => props.rounds.reduce((sum, round) => sum + (round.activated_skill_ids?.length || 0), 0))
const toolCount = computed(() => props.rounds.reduce((sum, round) => sum + (round.tool_calls || []).filter((call) => call.trace_source !== 'legacy_inferred').length, 0))
const modelEvaluations = computed(() => props.rounds.reduce((sum, round) => {
  const direct = round.tool_calls?.reduce((inner, call) => inner + Number(call.metrics?.model_evaluations || 0), 0) || 0
  if (direct) return sum + direct
  const observation = round.tool_observations?.find((item) => item.startsWith('model_evaluations='))
  return sum + Number(observation?.split('=')[1] || 0)
}, 0))
const candidateCount = computed(() => new Set(props.rounds.flatMap((round) => round.tool_observations || [])
  .filter((item) => item.startsWith('candidate_scheme_id='))
  .map((item) => item.slice('candidate_scheme_id='.length))
  .filter(Boolean)).size)
const gatePassCount = computed(() => props.rounds.filter((round) => round.action === 'A06_GATE' && (
  round.tool_observations.includes('adoption_status=ADOPT')
  || round.tool_observations.includes('qualification_status=QUALIFIED')
  || round.tool_status === 'ACCEPT'
)).length)
</script>

<template>
  <dl class="experiment-stats" aria-label="实验执行统计" data-test="experiment-stats">
    <div><dt>Agent 决策</dt><dd>{{ rounds.length }}</dd></div>
    <div><dt>Skills 调用</dt><dd>{{ skillCount }}</dd></div>
    <div><dt>Tools 调用</dt><dd>{{ toolCount }}</dd></div>
    <div><dt>模型计算</dt><dd>{{ modelEvaluations }}</dd></div>
    <div><dt>候选方案</dt><dd>{{ candidateCount }}</dd></div>
    <div><dt>Gate 通过</dt><dd>{{ gatePassCount }}</dd></div>
  </dl>
</template>

<style scoped>
.experiment-stats { display: grid; flex: none; grid-template-columns: repeat(6, minmax(0, 1fr)); grid-auto-rows: max-content; align-self: start; margin: 0; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface); }
.experiment-stats div { min-width: 0; padding: 9px 11px; }
.experiment-stats div + div { border-left: 1px solid var(--separator); }
dt { color: var(--text-secondary); font-size: 11px; font-weight: 550; }
dd { margin: 2px 0 0; color: var(--text-primary); font-family: var(--mono); font-size: 17px; font-weight: 650; }
@media (max-width: 1100px) { .experiment-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); } .experiment-stats div:nth-child(4) { border-top: 1px solid var(--separator); border-left: 0; } .experiment-stats div:nth-child(5), .experiment-stats div:nth-child(6) { border-top: 1px solid var(--separator); } }
@media (max-width: 680px) { .experiment-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } .experiment-stats div:nth-child(odd) { border-left: 0; } .experiment-stats div:nth-child(n + 3) { border-top: 1px solid var(--separator); } }
</style>
