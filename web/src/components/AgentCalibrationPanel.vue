<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import HydrographComparisonChart from './HydrographComparisonChart.vue'
import ReportSectionHead from './ReportSectionHead.vue'
import { api } from '../api/client'
import type { HydrographComparison } from '../types/api'
import type { ResearchTrial } from '../types/research'

const props = defineProps<{
  taskId: string | null
  comparison?: HydrographComparison | null
}>()

const trials = ref<ResearchTrial[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const GATE_REASON_ZH: Record<string, string> = {
  lead_1_guardrail: '第 1 日预见期 NSE 下降超过允许值',
  lead_2_guardrail: '第 2 日预见期 NSE 下降超过允许值',
  lead_3_guardrail: '第 3 日预见期 NSE 下降超过允许值',
  lead_guardrail: '某预见期 NSE 下降超过允许值',
  lead_1_high_flow_guardrail: '第 1 日预见期高峰误差恶化超过允许值',
  lead_2_high_flow_guardrail: '第 2 日预见期高峰误差恶化超过允许值',
  lead_3_high_flow_guardrail: '第 3 日预见期高峰误差恶化超过允许值',
  high_flow_guardrail: '高峰流量误差恶化超过允许值',
  insufficient_absolute_skill: '候选方案绝对技巧未达标',
  insufficient_primary_skill: '候选方案主指标未达采用下限',
  insufficient_primary_improvement: '主指标提升不足，维持原方案',
  insufficient_gbt_scheme_grade: 'GB/T 22482 方案等级未达最低要求',
  missing_standard_evaluation: '缺少标准评价，资格未判定',
  gbt_scheme_grade_ok: 'GB/T 方案等级达标',
  meaningful_primary_improvement: '主指标有实质提升',
  primary_floor_ok: '主指标达到采用下限',
}

const GATE_LABEL: Record<string, string> = {
  ACCEPT: '采用',
  KEEP: '维持',
  ROLLBACK: '回退',
}

const visible = computed(
  () => !!props.comparison?.series?.length || trials.value.length > 0 || loading.value || !!error.value,
)

function formatMetric(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '-'
  return value.toFixed(3)
}

function formatDelta(value: number) {
  const body = value.toFixed(3)
  return value > 0 ? `+${body}` : body
}

function reasonLabel(code: string) {
  if (GATE_REASON_ZH[code]) return GATE_REASON_ZH[code]
  if (code.startsWith('scheme_grade=')) return `方案等级为${code.slice('scheme_grade='.length)}`
  if (code.startsWith('min_scheme_grade=')) return `要求最低等级${code.slice('min_scheme_grade='.length)}`
  return code
}

function changedParams(trial: ResearchTrial) {
  return Object.entries(trial.parameter_delta || {})
    .filter(([, value]) => Number.isFinite(value) && Math.abs(value) > 1e-12)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => ({ key, value }))
}

function gateTone(status: string) {
  if (status === 'ACCEPT') return 'success'
  if (status === 'ROLLBACK') return 'danger'
  if (status === 'KEEP') return 'caution'
  return 'neutral'
}

async function load() {
  if (!props.taskId) {
    trials.value = []
    return
  }
  loading.value = true
  error.value = null
  try {
    const summary = await api.getResearch(props.taskId)
    trials.value = summary.trials || []
  } catch (err) {
    error.value = String((err as Error).message || err)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.taskId, load)
</script>

<template>
  <section v-if="visible" class="agent-calibration" data-test="agent-calibration-panel">
    <ReportSectionHead
      overline="调参过程"
      title="智能体调参"
      subtitle="回退只表示候选未进入最终方案。这里保留与观测的率定窗对比、每一条参数变化，以及回退原因。"
    >
      <template v-if="trials.length" #aside>
        <span class="count">{{ trials.length }} 轮搜索</span>
      </template>
    </ReportSectionHead>

    <div v-if="loading" class="state">正在读取调参记录…</div>
    <div v-else-if="error" class="state is-error" role="alert">{{ error }}</div>

    <template v-if="comparison?.series?.length">
      <div class="chart-title">
        <h3>率定窗里，观测与候选差在哪里</h3>
        <span>观测 / 基准 / 候选 · {{ comparison.windows?.calibration || `${comparison.evaluated_days} 天` }} · m³/s</span>
      </div>
      <HydrographComparisonChart :comparison="comparison" />
    </template>

    <div v-if="trials.length" class="trials">
      <article v-for="(trial, index) in trials" :key="trial.trial_id" class="trial" data-test="agent-calibration-trial">
        <div class="trial-head">
          <div>
            <small>第 {{ index + 1 }} 轮</small>
            <strong>{{ trial.strategy_id }}</strong>
          </div>
          <span class="status-pill" :class="gateTone(trial.development_gate)">{{ GATE_LABEL[trial.development_gate] || trial.development_gate }}</span>
        </div>
        <div class="metrics">
          <div><small>率定窗 NSE</small><strong>{{ formatMetric(trial.baseline_nse) }} → {{ formatMetric(trial.candidate_nse) }}</strong></div>
          <div><small>开发窗主指标</small><strong>{{ formatMetric(trial.base_primary) }} → {{ formatMetric(trial.candidate_primary) }}</strong></div>
          <div><small>模型评估</small><strong>{{ trial.model_evaluations }}</strong></div>
        </div>
        <div v-if="trial.gate_reasons?.length" class="reasons">
          <small>回退 / 未采用原因</small>
          <ul>
            <li v-for="code in trial.gate_reasons" :key="code">
              <span>{{ reasonLabel(code) }}</span>
              <code>{{ code }}</code>
            </li>
          </ul>
        </div>
        <div v-if="changedParams(trial).length" class="params">
          <small>参数变化（候选相对基准）</small>
          <table>
            <thead>
              <tr><th>参数</th><th class="numeric">变化量</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in changedParams(trial)" :key="row.key">
                <td>{{ row.key }}</td>
                <td class="numeric" :class="{ up: row.value > 0, down: row.value < 0 }">{{ formatDelta(row.value) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>
    <p v-else-if="!loading && !error" class="empty">没有产生参数试验；最终方案来自基础方案或直接冻结。</p>
  </section>
</template>

<style scoped>
.agent-calibration {
  margin: 0;
  padding: 24px 24px 8px;
  color: var(--text-primary);
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}
.trial-head,
.chart-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.chart-title h3,
.trial-head strong {
  margin: 0;
}
.count,
.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 3px 9px;
  border-radius: 999px;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 600;
}
.count { color: var(--info); background: var(--info-soft); }
.success { color: var(--accent-text); background: var(--accent-soft); }
.caution { color: var(--caution); background: var(--caution-soft); }
.danger { color: var(--danger); background: var(--danger-soft); }
.neutral { color: var(--neutral); background: var(--neutral-soft); }
.chart-title { margin: 20px 0 0; }
.chart-title h3 { font-size: 16px; }
.chart-title span { color: var(--text-secondary); font-size: 13px; }
.trials { display: grid; gap: 16px; margin: 20px 0 16px; }
.trial {
  padding: 16px;
  background: var(--surface-secondary);
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
}
.trial-head small,
.metrics small,
.reasons small,
.params small {
  display: block;
  color: var(--text-tertiary);
  font-size: 12px;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}
.metrics strong { display: block; margin-top: 4px; font-variant-numeric: tabular-nums; }
.reasons, .params { margin-top: 14px; }
.reasons ul { margin: 8px 0 0; padding: 0; list-style: none; display: grid; gap: 6px; }
.reasons li { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.reasons code { color: var(--text-tertiary); font-size: 11px; }
.params table { width: 100%; margin-top: 8px; border-collapse: collapse; }
.params th, .params td { padding: 8px 0; border-bottom: 1px solid var(--separator); text-align: left; }
.numeric { text-align: right; font-variant-numeric: tabular-nums; }
.up { color: var(--accent-text); }
.down { color: var(--danger); }
.state, .empty { margin: 16px 0; color: var(--text-secondary); }
.state.is-error { color: var(--danger); }
@media (max-width: 720px) {
  .agent-calibration { padding: 16px; }
  .trial-head, .chart-title { flex-direction: column; }
  .metrics { grid-template-columns: 1fr; }
  .reasons li { flex-direction: column; gap: 2px; }
}
</style>
