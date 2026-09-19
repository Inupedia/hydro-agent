<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import FloodEventMatrix from './FloodEventMatrix.vue'
import HydrographComparisonChart from './HydrographComparisonChart.vue'
import ReportSectionHead from './ReportSectionHead.vue'
import { api } from '../api/client'
import type {
  FloodEventDiagnosis,
  HydrographComparison,
  HydrographDiagnosisPacket,
} from '../types/api'
import type { ResearchExperimentPlan, ResearchTrial } from '../types/research'

const props = defineProps<{
  taskId: string | null
  comparison?: HydrographComparison | null
  diagnosis?: Record<string, unknown> | null
}>()

const trials = ref<ResearchTrial[]>([])
const latestPlan = ref<ResearchExperimentPlan | null>(null)
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

const candidateDiagnosis = computed(() => props.comparison?.candidate_diagnosis || null)

function agentDiagnosisPacket(): HydrographDiagnosisPacket | null {
  const raw = props.diagnosis?.diagnosis_packet
  if (!raw || typeof raw !== 'object') return null
  const packet = raw as Partial<HydrographDiagnosisPacket>
  if (typeof packet.window !== 'string' || !Array.isArray(packet.flood_events)) return null
  return packet as HydrographDiagnosisPacket
}

const processDiagnosis = computed(() => agentDiagnosisPacket() || candidateDiagnosis.value)

const visible = computed(
  () =>
    !!props.comparison?.series?.length ||
    !!processDiagnosis.value?.flood_events?.length ||
    trials.value.length > 0 ||
    loading.value ||
    !!error.value,
)

function eventMetric(event: FloodEventDiagnosis, key: string) {
  const value = event.metrics?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

const eventIds = computed(() =>
  (processDiagnosis.value?.flood_events || []).map((event) => event.event_id),
)

const agentObservations = computed(() => {
  const events = processDiagnosis.value?.flood_events || []
  if (!events.length) return []

  const observations: string[] = []
  const volumeErrors = events
    .map((event) => eventMetric(event, 'volume_relative_error'))
    .filter((value): value is number => value != null)
  if (volumeErrors.length) {
    const withinFivePercent = volumeErrors.filter((value) => Math.abs(value) <= 0.05).length
    if (withinFivePercent === volumeErrors.length) {
      observations.push(`洪量基本正确：${withinFivePercent}/${volumeErrors.length} 场次洪洪量误差在 ±5% 内`)
    } else {
      observations.push(`洪量误差：${withinFivePercent}/${volumeErrors.length} 场次洪在 ±5% 内`)
    }
  }

  const peakErrors = events
    .map((event) => eventMetric(event, 'peak_relative_error'))
    .filter((value): value is number => value != null)
  const lowPeaks = peakErrors.filter((value) => value < 0).length
  if (peakErrors.length) {
    observations.push(
      lowPeaks === peakErrors.length
        ? `洪峰偏低：${lowPeaks}/${peakErrors.length} 场次洪均偏低`
        : `洪峰方向：${lowPeaks}/${peakErrors.length} 场次洪偏低`,
    )
  }

  const timing = events
    .map((event) => eventMetric(event, 'peak_timing_lag_steps'))
    .filter((value): value is number => value != null)
  const latePeaks = timing.filter((value) => value > 0).length
  if (timing.length) {
    observations.push(
      latePeaks === timing.length
        ? `峰现偏晚：${latePeaks}/${timing.length} 场次洪均偏晚`
        : `峰现方向：${latePeaks}/${timing.length} 场次洪偏晚`,
    )
  }

  if (
    events.length > 1 &&
    peakErrors.length === events.length &&
    timing.length === events.length &&
    lowPeaks === peakErrors.length &&
    latePeaks === timing.length
  ) {
    observations.push(`多场洪水出现同类问题：证据来自 ${eventIds.value.join('、')}`)
  }
  return observations
})

const diagnosisPhenomenon = computed(() => {
  const value = props.diagnosis?.phenomenon
  return typeof value === 'string' ? value : ''
})

const diagnosisGroups = computed(() => {
  const raw = props.diagnosis?.recommended_param_groups
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean)
  if (typeof raw === 'string') return raw.split(',').map((item) => item.trim()).filter(Boolean)
  return []
})

const nextStrategy = computed(() => {
  if (latestPlan.value?.strategy_id) return latestPlan.value.strategy_id
  const raw = props.diagnosis?.recommended_strategy_id
  return typeof raw === 'string' ? raw : ''
})

const nextGroups = computed(() =>
  latestPlan.value?.param_groups?.length ? latestPlan.value.param_groups : diagnosisGroups.value,
)

const nextEvidenceRefs = computed(() => {
  const refs = latestPlan.value?.evidence_refs || []
  return Array.from(new Set([...refs, ...eventIds.value]))
})

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
    latestPlan.value = null
    return
  }
  loading.value = true
  error.value = null
  try {
    const summary = await api.getResearch(props.taskId)
    trials.value = summary.trials || []
    latestPlan.value = summary.latest_experiment_plan || null
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

    <div v-if="processDiagnosis?.flood_events?.length" class="process-diagnosis" data-test="process-diagnosis">
      <div class="diagnosis-grid">
        <article class="diagnosis-block" data-test="agent-observations">
          <small>Agent 观察</small>
          <h3>不只看 NSE，而是看过程哪里出了问题</h3>
          <ul>
            <li v-for="item in agentObservations" :key="item">{{ item }}</li>
          </ul>
        </article>

        <article class="diagnosis-block" data-test="hydrologic-diagnosis">
          <small>水文诊断</small>
          <h3>{{ diagnosisPhenomenon || '过程证据已形成，等待 Agent 给出过程层判断' }}</h3>
          <p v-if="diagnosisGroups.length">
            当前怀疑的过程层（来自 Agent 诊断）：<strong>{{ diagnosisGroups.join(' / ') }}</strong>
          </p>
          <p>
            支撑 Evidence / event IDs：
            <code>{{ eventIds.join(' · ') }}</code>
          </p>
        </article>

        <article class="diagnosis-block" data-test="next-experiment">
          <small>下一步实验</small>
          <h3>{{ nextStrategy || '尚未形成新的数值实验计划' }}</h3>
          <p v-if="nextGroups.length">开放过程/参数组：{{ nextGroups.join(' / ') }}</p>
          <p v-if="latestPlan?.objective">目标：{{ latestPlan.objective }}</p>
          <p v-if="nextEvidenceRefs.length">
            依据：<code>{{ nextEvidenceRefs.join(' · ') }}</code>
          </p>
        </article>
      </div>

      <div class="matrix-section">
        <div class="chart-title">
          <h3>次洪矩阵</h3>
          <span>全部指标均来自确定性后端 Evidence，不在前端重新计算</span>
        </div>
        <FloodEventMatrix :events="processDiagnosis.flood_events" />
      </div>
    </div>

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
.process-diagnosis { margin-top: 20px; }
.diagnosis-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.diagnosis-block {
  min-width: 0;
  padding: 16px;
  background: var(--surface-secondary);
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
}
.diagnosis-block small {
  display: block;
  color: var(--text-tertiary);
  font-size: 12px;
}
.diagnosis-block h3 {
  margin: 6px 0 10px;
  font-size: 15px;
  line-height: 1.45;
}
.diagnosis-block p {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.55;
}
.diagnosis-block ul {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.65;
}
.diagnosis-block code {
  white-space: normal;
  color: var(--text-tertiary);
  font-size: 11px;
}
.matrix-section { margin-top: 18px; }
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
  .diagnosis-grid { grid-template-columns: 1fr; }
  .reasons li { flex-direction: column; gap: 2px; }
}
</style>
