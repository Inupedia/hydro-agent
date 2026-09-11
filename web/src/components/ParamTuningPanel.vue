<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  diagnosis?: Record<string, unknown> | null
  optimize?: Record<string, unknown> | null
  scheme?: {
    parameters?: Record<string, number>
    base_parameters?: Record<string, number>
    parameter_delta?: Record<string, number>
    model_id?: string
    status?: string
  } | null
}>()

const GROUP_ZH: Record<string, string> = {
  evap: '蒸发',
  runoff: '产流',
  routing: '汇流',
}

const OBJECTIVE_ZH: Record<string, string> = {
  nse: 'NSE 吻合度',
  peak: '洪峰',
  composite: '综合（NSE+洪峰）',
}

const PARAM_GROUP_OF: Record<string, string> = {
  K: 'evap',
  UM: 'evap',
  LM: 'evap',
  DM: 'evap',
  C: 'evap',
  B: 'runoff',
  IM: 'runoff',
  SM: 'runoff',
  EX: 'runoff',
  KI: 'runoff',
  KG: 'runoff',
  CS: 'routing',
  CI: 'routing',
  CG: 'routing',
  L: 'routing',
}

type HypothesisRow = {
  id: string
  strength: number
  phenomenon: string
  suggested_action?: string | null
  suggested_strategy_id?: string | null
}

const hypotheses = computed<HypothesisRow[]>(() => {
  const raw = props.diagnosis?.hypotheses_json
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        return parsed.map((item) => ({
          id: String(item.id || 'UNKNOWN'),
          strength: Number(item.strength || 0),
          phenomenon: String(item.phenomenon || ''),
          suggested_action: item.suggested_action ?? null,
          suggested_strategy_id: item.suggested_strategy_id ?? null,
        }))
      }
    } catch {
      /* ignore */
    }
  }
  const hypothesis = props.diagnosis?.hypothesis
  const phenomenon = props.diagnosis?.phenomenon
  if (typeof hypothesis === 'string' || typeof phenomenon === 'string') {
    return [
      {
        id: String(hypothesis || 'UNKNOWN'),
        strength: 1,
        phenomenon: String(phenomenon || ''),
        suggested_action: typeof props.diagnosis?.recommended_action === 'string' ? props.diagnosis.recommended_action : null,
        suggested_strategy_id:
          typeof props.diagnosis?.recommended_strategy_id === 'string'
            ? props.diagnosis.recommended_strategy_id
            : null,
      },
    ]
  }
  return []
})

const strategyId = computed(() =>
  typeof props.optimize?.strategy_id === 'string' ? props.optimize.strategy_id : null,
)
const paramGroups = computed(() => {
  const raw = props.optimize?.param_groups
  if (typeof raw !== 'string' || !raw.trim()) return [] as string[]
  return raw.split(',').map((s) => s.trim()).filter(Boolean)
})
const objective = computed(() =>
  typeof props.optimize?.objective === 'string' ? props.optimize.objective : null,
)
const objectiveValue = computed(() => {
  const metrics = props.optimize?.metrics
  if (metrics && typeof metrics === 'object' && 'objective_value' in metrics) {
    const value = Number((metrics as Record<string, unknown>).objective_value)
    return Number.isFinite(value) ? value : null
  }
  return null
})

const rows = computed(() => {
  const current = props.scheme?.parameters || {}
  const base = props.scheme?.base_parameters || {}
  const delta = props.scheme?.parameter_delta || {}
  const keys = Array.from(new Set([...Object.keys(current), ...Object.keys(base), ...Object.keys(delta)]))
  return keys
    .map((key) => {
      const before = base[key]
      const after = current[key]
      const change = delta[key] ?? (before != null && after != null ? after - before : null)
      return {
        key,
        group: PARAM_GROUP_OF[key] || '',
        before: before ?? null,
        after: after ?? null,
        change,
      }
    })
    .filter((row) => row.change == null || Math.abs(row.change) > 1e-12 || row.before != null || row.after != null)
    .sort((a, b) => Math.abs(b.change || 0) - Math.abs(a.change || 0))
})

const changedRows = computed(() => rows.value.filter((row) => row.change != null && Math.abs(row.change) > 1e-12))
const showPanel = computed(
  () => hypotheses.value.length > 0 || !!strategyId.value || changedRows.value.length > 0 || rows.value.length > 0,
)

function fmt(value: number | null) {
  if (value == null || !Number.isFinite(value)) return '—'
  return Math.abs(value) >= 10 ? value.toFixed(2) : value.toFixed(3)
}

function fmtDelta(value: number | null) {
  if (value == null || !Number.isFinite(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${fmt(value)}`
}
</script>

<template>
  <section v-if="showPanel" class="param-tuning" data-test="param-tuning">
    <header class="param-tuning-head">
      <div>
        <span class="overline">调参与判断</span>
        <h2>新安江参数如何被调整</h2>
        <p>诊断假设 → 水文员手工改参对比（优先）或有界搜索 → 与基础方案对照 → Gate。</p>
      </div>
      <span v-if="scheme?.status" class="status-pill">{{ scheme.status === 'frozen' ? '已冻结' : scheme.status }}</span>
    </header>

    <div v-if="hypotheses.length" class="tuning-block">
      <h3>诊断假设</h3>
      <ul class="hypothesis-list">
        <li v-for="item in hypotheses" :key="`${item.id}-${item.phenomenon}`">
          <div class="hyp-top">
            <strong>{{ item.id }}</strong>
            <span>强度 {{ (item.strength * 100).toFixed(0) }}%</span>
          </div>
          <p>{{ item.phenomenon }}</p>
          <small v-if="item.suggested_action || item.suggested_strategy_id">
            建议：{{ [item.suggested_action, item.suggested_strategy_id].filter(Boolean).join(' · ') }}
          </small>
        </li>
      </ul>
    </div>

    <div v-if="strategyId || paramGroups.length || objective" class="tuning-block">
      <h3>本次优化设定</h3>
      <dl class="tuning-meta">
        <div v-if="strategyId"><dt>策略</dt><dd>{{ strategyId }}</dd></div>
        <div v-if="paramGroups.length">
          <dt>参数组</dt>
          <dd>{{ paramGroups.map((g) => GROUP_ZH[g] || g).join('、') }}</dd>
        </div>
        <div v-if="objective">
          <dt>目标</dt>
          <dd>{{ OBJECTIVE_ZH[objective] || objective }}</dd>
        </div>
        <div v-if="objectiveValue != null">
          <dt>目标值</dt>
          <dd>{{ fmt(objectiveValue) }}</dd>
        </div>
      </dl>
    </div>

    <div v-if="rows.length" class="tuning-block">
      <h3>参数对照{{ changedRows.length ? `（变化 ${changedRows.length} 项）` : '' }}</h3>
      <div class="param-table-wrap">
        <table>
          <thead>
            <tr>
              <th>参数</th>
              <th>组别</th>
              <th>基础</th>
              <th>采用</th>
              <th>变化</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.key"
              :class="{ changed: row.change != null && Math.abs(row.change) > 1e-12 }"
            >
              <td>{{ row.key }}</td>
              <td>{{ GROUP_ZH[row.group] || '—' }}</td>
              <td>{{ fmt(row.before) }}</td>
              <td>{{ fmt(row.after) }}</td>
              <td :class="{ up: (row.change || 0) > 0, down: (row.change || 0) < 0 }">
                {{ fmtDelta(row.change) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!changedRows.length" class="hint">相对基础方案未检测到参数变化（可能仍是 base，或尚未优化）。</p>
    </div>
  </section>
</template>

<style scoped>
.param-tuning {
  margin: 8px 0 18px;
  padding: 20px;
  border: 1px solid var(--separator);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.param-tuning-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 16px;
}
.param-tuning-head h2 {
  margin: 6px 0 6px;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.3px;
}
.param-tuning-head p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.status-pill {
  flex-shrink: 0;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--info-soft);
  color: var(--info);
}
.tuning-block + .tuning-block {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--separator);
}
.tuning-block h3 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}
.hypothesis-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.hypothesis-list li {
  padding: 12px 16px;
  border-radius: var(--radius-md);
  background: var(--surface-secondary);
}
.hyp-top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}
.hypothesis-list p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.55;
}
.hypothesis-list small {
  display: block;
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 12px;
}
.tuning-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px 12px;
  margin: 0;
}
.tuning-meta div {
  background: var(--surface-secondary);
  border-radius: var(--radius-md);
  padding: 10px 12px;
}
.tuning-meta dt {
  font-size: 12px;
  color: var(--text-secondary);
}
.tuning-meta dd {
  margin: 4px 0 0;
  font-size: 14px;
  font-weight: 600;
}
.param-table-wrap {
  overflow: auto;
  border-radius: var(--radius-md);
  border: 1px solid var(--separator);
}
.param-table-wrap table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}
.param-table-wrap th,
.param-table-wrap td {
  padding: 14px 16px;
  text-align: left;
  border-bottom: 1px solid var(--separator);
  white-space: nowrap;
}
.param-table-wrap th {
  background: var(--surface-secondary);
  color: var(--text-secondary);
  font-weight: 600;
  font-size: 13px;
}
.param-table-wrap td {
  font-size: 14px;
}
.param-table-wrap tbody tr:hover td {
  background: var(--table-hover);
}
.param-table-wrap tr.changed td {
  background: var(--accent-soft);
}
.param-table-wrap td.up { color: var(--success); }
.param-table-wrap td.down { color: var(--danger); }
.param-table-wrap th:nth-child(n+3),
.param-table-wrap td:nth-child(n+3) { text-align: right; }
.hint {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
