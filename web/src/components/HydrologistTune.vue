<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type HydrologistSession } from '../api/client'

const props = defineProps<{
  planId?: string | null
  taskId?: string | null
  locked?: boolean
}>()

const session = ref<HydrologistSession | null>(null)
const busy = ref(false)
const error = ref('')
const note = ref('')
const edits = ref<Record<string, number>>({})

const stageLabel: Record<string, string> = {
  created: '已创建',
  baseline: '基准模拟中',
  baseline_ready: '基准已完成',
  params_updated: '参数已修改',
  compare: '对比中',
  compared: '已完成对比',
  submitted: '已提交候选',
}

const canBaseline = computed(() => {
  if (!session.value) return false
  if (session.value.status === 'failed') return true
  return ['created', 'baseline_ready'].includes(session.value.stage)
})
const canEdit = computed(() => !!session.value && ['baseline_ready', 'compared', 'params_updated'].includes(session.value.stage))
const canCompare = computed(() => session.value?.stage === 'params_updated')
const canSubmit = computed(() => session.value?.stage === 'compared' && !!props.taskId)

const metricRows = computed(() => {
  const base = session.value?.baseline_metrics || {}
  const cand = session.value?.candidate_metrics || {}
  const delta = session.value?.comparison?.metric_delta || {}
  const keys = ['nse', 'rmse_m3s', 'pbias_percent', 'simulated_peak_m3s']
  return keys
    .filter((k) => k in base || k in cand)
    .map((k) => ({
      key: k,
      baseline: base[k],
      candidate: cand[k],
      delta: delta[k],
    }))
})

watch(
  () => session.value?.current_params,
  (params) => {
    if (!params) return
    edits.value = { ...params }
  },
  { immediate: true },
)

async function createSession() {
  if (!props.planId) {
    error.value = '请先选择已就绪的模型方案'
    return
  }
  busy.value = true
  error.value = ''
  try {
    session.value = await api.createHydrologistSession({
      plan_id: props.planId,
      task_id: props.taskId || null,
    })
  } catch (e) {
    error.value = String((e as Error).message || e)
  } finally {
    busy.value = false
  }
}

async function step(stepName: 'baseline' | 'update_params' | 'compare' | 'submit') {
  if (!session.value) return
  busy.value = true
  error.value = ''
  try {
    const body: {
      step: typeof stepName
      params?: Record<string, number>
      note?: string
      task_id?: string | null
    } = { step: stepName, task_id: props.taskId }
    if (stepName === 'update_params') {
      body.params = { ...edits.value }
      body.note = note.value
    }
    session.value = await api.hydrologistStep(session.value.session_id, body)
  } catch (e) {
    error.value = String((e as Error).message || e)
  } finally {
    busy.value = false
  }
}

function fmt(value: unknown) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(4) : String(value)
}
</script>

<template>
  <section class="hydrologist-tune" data-test="hydrologist-tune">
    <header>
      <span class="overline">水文员调参 / 老师 notebook §6</span>
      <h2>手工改参 · 重跑 · 对比</h2>
      <p>按老师流程：先跑基准，再改参数对比，确认后再提交候选给 Gate。不是黑盒随机搜索。</p>
    </header>

    <div class="actions">
      <button type="button" :disabled="locked || busy || !planId" @click="createSession">新建调参会话</button>
      <button type="button" :disabled="locked || busy || !session || !canBaseline" @click="step('baseline')">跑基准模拟</button>
      <button type="button" :disabled="locked || busy || !canEdit" @click="step('update_params')">保存参数</button>
      <button type="button" :disabled="locked || busy || !canCompare" @click="step('compare')">重跑并对比</button>
      <button type="button" :disabled="locked || busy || !canSubmit" @click="step('submit')">提交候选给 Gate</button>
    </div>

    <p v-if="error" class="tune-error" role="alert">{{ error }}</p>
    <p v-if="session" class="session-meta">
      <strong>{{ stageLabel[session.stage] || session.stage }}</strong>
      <span>{{ session.session_id }}</span>
      <span v-if="session.candidate_scheme_id">候选 {{ session.candidate_scheme_id }}</span>
    </p>

    <div v-if="session" class="param-grid">
      <label v-for="key in session.editable" :key="key">
        {{ key }}
        <input v-model.number="edits[key]" type="number" step="any" :disabled="locked || busy || !canEdit" />
        <small v-if="session.baseline_params?.[key] != null">基准 {{ fmt(session.baseline_params[key]) }}</small>
      </label>
    </div>

    <label v-if="session" class="note-field">改参说明<input v-model="note" type="text" :disabled="locked || busy || !canEdit" placeholder="例如：抬高 CS 减轻洪峰滞后" /></label>

    <table v-if="metricRows.length" class="metric-table">
      <thead><tr><th>指标</th><th>基准</th><th>改参后</th><th>差值</th></tr></thead>
      <tbody>
        <tr v-for="row in metricRows" :key="row.key">
          <td>{{ row.key }}</td>
          <td>{{ fmt(row.baseline) }}</td>
          <td>{{ fmt(row.candidate) }}</td>
          <td>{{ fmt(row.delta) }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.hydrologist-tune{padding:20px;background:rgba(255,255,255,.78);border:1px solid #d5e1ea;border-radius:16px}
.hydrologist-tune h2{font-size:22px;margin:8px 0}
.hydrologist-tune p{color:#596f80;line-height:1.55;font-size:13px}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.actions button{padding:10px 12px;border:0;border-radius:8px;background:#1769ad;color:#fff;cursor:pointer;font-size:12px}
.actions button:disabled{opacity:.45;cursor:default}
.session-meta{display:flex;flex-wrap:wrap;gap:10px;font-size:12px}
.param-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;margin:12px 0}
.param-grid label{display:grid;gap:4px;font-size:12px}
.param-grid input,.note-field input{padding:8px;border:1px solid #c6d6e5;border-radius:8px;width:100%}
.note-field{display:grid;gap:6px;font-size:12px;margin-bottom:12px}
.metric-table{width:100%;border-collapse:collapse;font-size:12px}
.metric-table th,.metric-table td{border-bottom:1px solid #e1ebf2;padding:8px;text-align:left}
.tune-error{color:#ac3b2c!important;white-space:pre-wrap}
</style>
