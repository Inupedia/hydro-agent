<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api/client'
import ReportSectionHead from './ReportSectionHead.vue'
import NumberTicker from './ui/NumberTicker.vue'
import type { EvidenceSlice, ResearchSummary } from '../types/research'

const props = defineProps<{ taskId: string | null }>()
const summary = ref<ResearchSummary | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const protocol = computed(() => summary.value?.protocol || {})
const plan = computed(() => summary.value?.latest_experiment_plan || null)
const trials = computed(() => summary.value?.trials || [])
const evidence = computed(() => summary.value?.final_test_evidence || null)
const audit = computed(() => summary.value?.final_test_audit || null)

const protocolModeLabel = computed(() =>
  protocol.value.protocol_mode === 'smoke' ? '烟雾验证协议' : '正式研究协议',
)

const finalTestStatus = computed(() => {
  if (!audit.value?.consumed) return '尚未读取'
  if (audit.value.read_only && audit.value.single_use) return '只读 · 单次消费完成'
  return '已读取 · 审计信息不完整'
})

const annualStabilityStatus = computed(() => {
  const canonical = evidence.value?.annual_stability?.status
  if (canonical) return canonical
  return Object.values(evidence.value?.years || {}).some((item) => item.status === 'available')
    ? 'available'
    : 'insufficient_data'
})

function range(start?: string, end?: string) {
  if (!start && !end) return '-'
  return `${start || '-'} → ${end || '-'}`
}

function formatMetric(value: number | undefined) {
  if (value == null || !Number.isFinite(value)) return '-'
  if (Math.abs(value) >= 100) return value.toFixed(1)
  return value.toFixed(3)
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    ACCEPT: '采用',
    KEEP: '维持',
    ROLLBACK: '回退',
    ADOPT: '采用候选',
    REJECT: '拒绝候选',
    QUALIFIED: '达标',
    UNQUALIFIED: '未达标',
    NOT_EVALUATED: '未评价',
    supported: '假设获支持',
    refuted: '假设被证伪',
    inconclusive: '证据不足',
  }
  return labels[value] || value || '-'
}

function statusTone(value: string) {
  if (['ACCEPT', 'ADOPT', 'QUALIFIED', 'supported'].includes(value)) return 'success'
  if (['ROLLBACK', 'REJECT', 'UNQUALIFIED', 'refuted'].includes(value)) return 'danger'
  if (['KEEP', 'NOT_EVALUATED', 'inconclusive'].includes(value)) return 'caution'
  return 'neutral'
}

function optimizerLabel(value?: string | null) {
  const labels: Record<string, string> = {
    dds: '动态维搜索',
    'sce-ua': '复合进化',
    'random-search': '随机搜索',
    manual: '手工',
  }
  return labels[value || ''] || value || '-'
}

function objectiveLabel(value?: string | null) {
  const labels: Record<string, string> = {
    nse: 'NSE',
    kge: 'KGE',
    peak: '洪峰',
    composite: 'KGE',
  }
  return labels[value || ''] || (value ? value.toUpperCase() : '-')
}

function paramGroupLabel(value: string) {
  const labels: Record<string, string> = {
    evap: '蒸发',
    runoff: '产流',
    routing: '汇流',
  }
  return labels[value] || value
}

function sourceLabel(value?: string | null) {
  const labels: Record<string, string> = {
    persisted_evidence: '已落库证据',
    composite_to_kge: '综合目标记为 KGE',
    'composite->kge': '综合目标记为 KGE',
  }
  return labels[value || ''] || value || '-'
}

function sliceState(slice: EvidenceSlice | undefined) {
  if (!slice) return 'unavailable'
  return slice.status
}

async function load() {
  if (!props.taskId) {
    summary.value = null
    return
  }
  loading.value = true
  error.value = null
  try {
    summary.value = await api.getResearch(props.taskId)
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
  <section class="research-panel" data-test="research-evidence-panel" aria-labelledby="research-evidence-title">
    <ReportSectionHead
      overline="研究审计"
      title="研究证据"
      subtitle="把实验协议、每轮试验与最终独立检验放在同一条可审计链路里。"
      title-id="research-evidence-title"
    >
      <template v-if="summary" #aside>
        <span class="protocol-badge">{{ protocolModeLabel }}</span>
      </template>
    </ReportSectionHead>

    <div v-if="loading" class="research-state" aria-live="polite">正在读取研究证据…</div>
    <div v-else-if="error" class="research-state is-error" role="alert">
      <strong>研究证据暂时无法读取</strong>
      <span>{{ error }}</span>
      <button type="button" class="retry-button" @click="load">重试</button>
    </div>
    <div v-else-if="!summary" class="research-state">任务完成后会显示研究协议与试验账本。</div>

    <template v-else>
      <section class="research-section protocol-section">
        <div class="section-title-row">
          <div><span>01</span><h3>实验协议</h3></div>
          <span class="audit-chip" :class="audit?.read_only && audit?.single_use ? 'success' : 'neutral'">{{ finalTestStatus }}</span>
        </div>
        <div class="protocol-grid">
          <article>
            <small>率定窗</small>
            <strong>{{ range(protocol.calibration_start_date, protocol.calibration_end_date) }}</strong>
            <span>用于参数搜索与实验生成</span>
          </article>
          <article>
            <small>开发验证窗</small>
            <strong>{{ range(protocol.development_start_date, protocol.development_end_date) }}</strong>
            <span>候选方案门控，可反复比较</span>
          </article>
          <article class="final-test-card">
            <small>最终独立检验</small>
            <strong>{{ range(protocol.final_test_start_date, protocol.final_test_end_date) }}</strong>
            <span>冻结后只读，绝不参与参数选择</span>
          </article>
        </div>
        <p class="contract-note">
          滚动预报技巧与连续模拟技巧分开报告，不做混合平均。
        </p>
      </section>

      <section class="research-section plan-section">
        <div class="section-title-row">
          <div><span>02</span><h3>最新实验计划</h3></div>
          <span v-if="plan?.sensitivity_method" class="audit-chip neutral">{{ plan.sensitivity_method === 'morris' ? '全局敏感性筛选' : plan.sensitivity_method }}</span>
        </div>
        <div v-if="plan" class="plan-grid">
          <div><small>策略</small><strong>{{ plan.strategy_id || '-' }}</strong></div>
          <div><small>优化器</small><strong>{{ optimizerLabel(plan.optimizer) }}</strong></div>
          <div><small>目标</small><strong>{{ objectiveLabel(plan.objective) }}</strong></div>
          <div><small>模型评估预算</small><strong>{{ plan.evaluation_budget ?? '-' }}</strong></div>
          <div class="plan-wide"><small>参数组</small><strong>{{ plan.param_groups.length ? plan.param_groups.map(paramGroupLabel).join(' · ') : '-' }}</strong></div>
          <div class="plan-wide"><small>本轮依据</small><span>{{ plan.reason_codes.length ? plan.reason_codes.join(' · ') : '由当前诊断证据生成' }}</span></div>
          <div v-if="plan.active_parameters.length" class="plan-wide"><small>活动参数</small><span>{{ plan.active_parameters.join(' · ') }}</span></div>
        </div>
        <p v-else class="empty-copy">本任务没有执行参数优化，因此没有实验计划。</p>
      </section>

      <section class="research-section ledger-section">
        <div class="section-title-row">
          <div><span>03</span><h3>试验账本</h3></div>
          <span class="audit-chip neutral">{{ trials.length }} 次受控实验</span>
        </div>
        <div v-if="trials.length" class="ledger-scroll" tabindex="0" aria-label="试验账本，可横向滚动">
          <table>
            <thead>
              <tr>
                <th>轮次</th>
                <th>策略</th>
                <th class="numeric">模型评估</th>
                <th>开发门控</th>
                <th>采用</th>
                <th>资格</th>
                <th>假设结果</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(trial, index) in trials" :key="trial.trial_id">
                <td class="numeric">{{ index + 1 }}</td>
                <td><strong>{{ trial.strategy_id }}</strong><small>{{ trial.plan_id.slice(0, 20) }}</small></td>
                <td class="numeric">{{ trial.model_evaluations }}</td>
                <td><span class="status-pill" :class="statusTone(trial.development_gate)">{{ statusLabel(trial.development_gate) }}</span></td>
                <td><span class="status-pill" :class="statusTone(trial.adoption_status)">{{ statusLabel(trial.adoption_status) }}</span></td>
                <td><span class="status-pill" :class="statusTone(trial.qualification_status)">{{ statusLabel(trial.qualification_status) }}</span></td>
                <td><span class="status-pill" :class="statusTone(trial.hypothesis_outcome)">{{ statusLabel(trial.hypothesis_outcome) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty-copy">没有产生参数实验；最终方案来自基础方案或直接冻结。</p>
      </section>

      <section class="research-section evidence-section">
        <div class="section-title-row">
          <div><span>04</span><h3>最终独立检验证据</h3></div>
          <span v-if="evidence" class="audit-chip" :class="evidence.quality.coverage >= 0.95 ? 'success' : 'caution'">
            有效覆盖 {{ Math.round(evidence.quality.coverage * 100) }}%
          </span>
        </div>
        <template v-if="evidence">
          <div v-if="sliceState(evidence.overall) === 'available'" class="metric-grid">
            <div><small>NSE</small><strong><NumberTicker :value="evidence.overall.metrics.nse" :format="formatMetric" /></strong></div>
            <div><small>KGE</small><strong><NumberTicker :value="evidence.overall.metrics.kge" :format="formatMetric" /></strong></div>
            <div><small>RMSE</small><strong><NumberTicker :value="evidence.overall.metrics.rmse" :format="formatMetric" /></strong></div>
            <div><small>PBIAS %</small><strong><NumberTicker :value="evidence.overall.metrics.pbias_percent" :format="formatMetric" /></strong></div>
            <div><small>样本</small><strong><NumberTicker :value="evidence.overall.sample_count" :decimal-places="0" /></strong></div>
          </div>
          <div v-else class="insufficient-note">最终检验有效样本不足，不能形成稳定的总体统计结论。</div>

          <div class="evidence-availability">
            <div>
              <small>年度稳定性</small>
              <strong>{{ annualStabilityStatus === 'available' ? '有可用证据' : '样本不足' }}</strong>
            </div>
            <div>
              <small>流量历时曲线</small>
              <strong>{{ evidence.fdc.status === 'available' ? '有可用证据' : '样本不足' }}</strong>
            </div>
            <div>
              <small>洪水事件</small>
              <strong>{{ evidence.flood_events.some((item) => item.status === 'available') ? `${evidence.flood_events.filter((item) => item.status === 'available').length} 场可用` : '样本不足' }}</strong>
            </div>
          </div>
          <p v-if="evidence.fdc.status !== 'available' || annualStabilityStatus !== 'available'" class="insufficient-note">
            “样本不足”不是零分：当前窗口不支持年度稳定性或流量历时曲线等结论，系统不会用短样本伪造稳定性证据。
          </p>
        </template>
        <p v-else class="empty-copy">最终检验过程线尚未形成，当前不展示推断性证据。</p>
      </section>

      <details class="research-technical">
        <summary>审计字段</summary>
        <dl>
          <div><dt>最终检验窗</dt><dd>{{ audit?.window || range(protocol.final_test_start_date, protocol.final_test_end_date) }}</dd></div>
          <div><dt>试验来源</dt><dd>{{ sourceLabel(summary.contracts.trial_ledger_source) }}</dd></div>
          <div v-if="summary.contracts.evidence_source_priority"><dt>证据来源</dt><dd>{{ sourceLabel(summary.contracts.evidence_source_priority) }}</dd></div>
          <div><dt>目标别名</dt><dd>{{ sourceLabel(summary.contracts.objective_alias) }}</dd></div>
          <div v-if="plan?.experiment_signature"><dt>实验签名</dt><dd>{{ plan.experiment_signature }}</dd></div>
        </dl>
      </details>
    </template>
  </section>
</template>

<style scoped>
.research-panel {
  margin: 0;
  padding: 24px;
  color: var(--text-primary);
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}

.section-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.section-title-row h3 {
  margin: 0;
}

.section-title-row h3 { font-size: 16px; }

.protocol-badge,
.audit-chip,
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
.protocol-badge { color: var(--info); background: var(--info-soft); }
.success { color: var(--accent-text); background: var(--accent-soft); }
.caution { color: var(--caution); background: var(--caution-soft); }
.danger { color: var(--danger); background: var(--danger-soft); }
.neutral { color: var(--neutral); background: var(--neutral-soft); }

.research-section {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid var(--separator);
}
.section-title-row > div { display: flex; align-items: center; gap: 10px; }
.section-title-row > div > span { color: var(--text-tertiary); font-variant-numeric: tabular-nums; }
.section-title-row h3 { font-size: 16px; }

.protocol-grid,
.metric-grid,
.evidence-availability,
.plan-grid {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}
.protocol-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.metric-grid { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.evidence-availability { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.plan-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }

.protocol-grid article,
.metric-grid > div,
.evidence-availability > div,
.plan-grid > div {
  min-width: 0;
  padding: 14px 16px;
  background: var(--surface-secondary);
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
}
.final-test-card { box-shadow: inset 3px 0 0 var(--accent); }
.plan-wide { grid-column: span 2; }
.protocol-grid small,
.metric-grid small,
.evidence-availability small,
.plan-grid small { display: block; color: var(--text-tertiary); font-size: 12px; }
.protocol-grid strong,
.metric-grid strong,
.evidence-availability strong,
.plan-grid strong { display: block; margin-top: 4px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.protocol-grid span,
.plan-grid span { display: block; margin-top: 4px; color: var(--text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.metric-grid strong { font-size: 22px; font-weight: 600; }

.contract-note,
.empty-copy,
.insufficient-note {
  margin: 12px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.insufficient-note {
  padding: 10px 12px;
  color: var(--caution);
  background: var(--caution-soft);
  border-radius: var(--radius-xs);
}

.ledger-scroll {
  margin-top: 16px;
  overflow-x: auto;
  scrollbar-gutter: stable;
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
}
.ledger-scroll table { min-width: 760px; }
.ledger-scroll th,
.ledger-scroll td { padding: 11px 12px; }
.ledger-scroll td small { display: block; margin-top: 2px; color: var(--text-tertiary); font-size: 11px; }

.research-state {
  margin-top: 16px;
  padding: 16px;
  color: var(--text-secondary);
  background: var(--surface-secondary);
  border-radius: var(--radius-sm);
}
.research-state.is-error { color: var(--danger); background: var(--danger-soft); }
.research-state.is-error span { display: block; margin-top: 4px; }
.retry-button {
  min-height: 32px;
  margin-top: 10px;
  padding: 4px 12px;
  color: var(--danger);
  background: var(--surface);
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
}

.research-technical { margin-top: 20px; color: var(--text-secondary); }
.research-technical summary { cursor: pointer; font-weight: 600; }
.research-technical dl { margin: 12px 0 0; }
.research-technical dl div { display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 12px; padding: 6px 0; }
.research-technical dt { color: var(--text-tertiary); }
.research-technical dd { margin: 0; overflow-wrap: anywhere; font-family: var(--mono); font-size: 12px; }

@media (max-width: 960px) {
  .protocol-grid,
  .plan-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 640px) {
  .research-panel { padding: 16px; }
  .section-title-row { align-items: stretch; flex-direction: column; }
  .protocol-grid,
  .plan-grid,
  .metric-grid,
  .evidence-availability { grid-template-columns: 1fr; }
  .plan-wide { grid-column: auto; }
  .research-technical dl div { grid-template-columns: 1fr; gap: 2px; }
}
</style>