<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CalibrationComparisonChart from '../components/CalibrationComparisonChart.vue'
import ProcessStory from '../components/ProcessStory.vue'
import ReportLinks from '../components/ReportLinks.vue'
import { api } from '../api/client'
import { useResultsStore } from '../stores/results'
import type { TimelineItem } from '../types/api'

const route = useRoute()
const router = useRouter()
const store = useResultsStore()
const taskId = computed(() => String(route.params.taskId))
const timeline = ref<TimelineItem[]>([])
const showTech = ref(false)
const showInitial = ref(false)

const metricCards = computed(() => {
  const metrics = store.result?.metrics || {}
  return [
    ['NSE', metrics.NSE, '过程吻合'],
    ['KGE', metrics.KGE, '综合一致性'],
    ['MAE', metrics.MAE, '平均绝对误差'],
    ['Bias', metrics.Bias, '系统偏差'],
  ] as const
})
const comparisonTitle = computed(() =>
  store.result?.comparison_scope === 'final_holdout' ? '独立测试：Calibrated vs Observed' : 'Calibrated vs Observed',
)
const hasInitial = computed(() => !!store.result?.comparison?.some((p) => p.initial != null))

onMounted(async () => {
  await store.load(taskId.value)
  try {
    timeline.value = await api.getTimeline(taskId.value)
  } catch {
    timeline.value = []
  }
})

function fmt(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? '—' : Number(value).toFixed(3)
}
</script>

<template>
  <section class="page publication-page">
    <header class="header publication-header">
      <div>
        <span class="eyebrow">MODEL PUBLICATION</span>
        <h1>模型率定结果</h1>
        <p class="lede">发布判断以率定后模型计算流量与实测流量的一致性为核心，内部调参轨迹仅作为审计证据。</p>
      </div>
      <div class="actions">
        <button type="button" class="secondary" @click="router.push(`/tasks/${taskId}/run`)">回看 Agent 过程</button>
        <button type="button" class="secondary" @click="router.push('/')">新建率定任务</button>
      </div>
    </header>

    <section class="hero-result" data-test="publication-comparison">
      <div class="section-title-row">
        <div>
          <span class="eyebrow">PRIMARY EVIDENCE</span>
          <h2>{{ comparisonTitle }}</h2>
          <p>Observed 是实测出口流量；Calibrated 是冻结参数后的模型计算结果。</p>
        </div>
        <label v-if="hasInitial" class="initial-toggle">
          <input v-model="showInitial" type="checkbox" />
          同时显示初始方案
        </label>
      </div>
      <CalibrationComparisonChart
        :points="store.result?.comparison || []"
        :show-initial="showInitial"
      />
    </section>

    <section class="metrics" aria-label="率定评价指标">
      <article v-for="([name, value, note]) in metricCards" :key="name" class="metric-card">
        <span>{{ name }}</span>
        <strong>{{ fmt(value) }}</strong>
        <small>{{ note }}</small>
      </article>
    </section>

    <section class="decision-card">
      <div>
        <span class="eyebrow">AGENT VERDICT</span>
        <h2>是否具备发布条件</h2>
      </div>
      <p>{{ store.result?.story_zh || '等待最终独立检验结果。' }}</p>
    </section>

    <details class="process-details">
      <summary>查看率定过程与水文诊断</summary>
      <ProcessStory :result="store.result" :timeline="timeline" />
    </details>

    <ReportLinks :task-id="taskId" :artifacts="store.result?.report_artifacts || []" />

    <section class="tech">
      <button type="button" class="linkish" data-test="toggle-tech" @click="showTech = !showTech">
        {{ showTech ? '收起技术细节' : '展开技术细节（参数、方案编号、哈希）' }}
      </button>
      <div v-if="showTech && store.result?.scheme" class="tech-panel" data-test="tech-panel">
        <p><strong>冻结方案</strong>：{{ store.result.scheme.status }}</p>
        <p>模型标识：{{ store.result.scheme.model_id }}</p>
        <p>方案编号：{{ store.result.scheme.scheme_id }}</p>
        <p>内容哈希：{{ store.result.scheme.content_hash.slice(0, 12) }}</p>
        <p v-if="store.result.gate">最终 Gate：{{ store.result.gate.status }}</p>
        <p v-if="store.result.scheme.parameter_delta && Object.keys(store.result.scheme.parameter_delta).length">
          参数变化：{{ store.result.scheme.parameter_delta }}
        </p>
      </div>
    </section>
  </section>
</template>

<style scoped>
.publication-page { max-width: 1180px; margin: 0 auto; }
.publication-header { margin-bottom: 20px; }
.eyebrow { display: block; color: var(--secondary); font-size: 11px; font-weight: 700; letter-spacing: .12em; margin-bottom: 6px; }
.hero-result, .decision-card { background: var(--surface); border: 1px solid var(--separator); border-radius: 16px; padding: 22px; box-shadow: var(--shadow); }
.section-title-row { display: flex; align-items: start; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
.section-title-row h2, .decision-card h2 { margin: 0 0 5px; font-size: 18px; }
.section-title-row p, .decision-card p { margin: 0; color: var(--secondary); font-size: 13px; line-height: 1.6; }
.initial-toggle { white-space: nowrap; font-size: 12px; color: var(--secondary); display: flex; align-items: center; gap: 7px; }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 14px 0; }
.metric-card { background: var(--surface); border: 1px solid var(--separator); border-radius: 12px; padding: 15px 17px; display: grid; gap: 5px; }
.metric-card span { font-size: 12px; color: var(--secondary); }
.metric-card strong { font-size: 24px; font-variant-numeric: tabular-nums; }
.metric-card small { font-size: 11px; color: var(--tertiary); }
.decision-card { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 24px; align-items: center; margin-bottom: 14px; }
.process-details { border-top: 1px solid var(--separator); border-bottom: 1px solid var(--separator); padding: 15px 0; margin: 18px 0; }
.process-details summary { cursor: pointer; color: var(--secondary); font-size: 13px; font-weight: 600; }
.secondary { background: transparent; color: #1f6b4a; border: 1px solid rgba(31, 107, 74, 0.35); }
.tech { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid rgba(16, 35, 28, 0.12); }
.tech-panel { margin-top: .75rem; padding: .9rem 1rem; background: rgba(255, 255, 255, .65); border: 1px solid rgba(16, 35, 28, .08); font-size: .9rem; color: rgba(16, 35, 28, .8); }
@media (max-width: 760px) {
  .metrics { grid-template-columns: 1fr 1fr; }
  .decision-card { grid-template-columns: 1fr; }
  .section-title-row { display: grid; }
}
</style>
