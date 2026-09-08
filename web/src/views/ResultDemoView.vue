<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DemoShell from '../layouts/DemoShell.vue'
import ForecastChart from '../components/ForecastChart.vue'
import { useDemoStore } from '../stores/demo'
import { actionDoneTitle, basinLabel, gateDecisionZh } from '../demo/stages'

const route = useRoute()
const router = useRouter()
const demo = useDemoStore()
const taskId = computed(() => String(route.params.taskId))

const gateStatus = computed(() => {
  const status = demo.results?.gate?.status
  return typeof status === 'string' ? status : null
})
const decision = computed(() => gateDecisionZh(gateStatus.value))
const doneActions = computed(() => {
  const seen = new Set<string>()
  const out: string[] = []
  for (const item of demo.timeline) {
    if (!item.action) continue
    if (item.status === 'failed' || item.status === 'error' || item.status === 'skipped') continue
    if (seen.has(item.action)) continue
    seen.add(item.action)
    out.push(item.action)
  }
  return out
})
const reports = computed(() => demo.results?.report_artifacts || [])
const modeLabel = computed(() => {
  if (demo.mode === 'live') return '实时执行记录'
  if (demo.mode === 'replay') return '历史案例回放'
  return '模拟演示'
})
const conclusion = computed(() => {
  if (demo.isFailed) {
    return {
      title: '本次执行未成功完成',
      body: '流程在中途受阻。下方仅展示已经产生的产物，不等于检查通过或业务可用。',
    }
  }
  if (!demo.results && !demo.isCompleted && demo.mode !== 'replay') {
    return {
      title: '结果尚未齐备',
      body: '运行状态仍在更新。可稍后重新加载，或先查看执行记录。',
    }
  }
  if (!demo.results) {
    return {
      title: '结果加载中',
      body: '正在读取已有运行记录。若长时间无数据，请点「重新加载结果」。',
    }
  }
  return {
    title: `执行已完成，${decision.value.title}`,
    body: '执行完成、检查通过、预测准确和业务可用是不同结论。本页展示的是本次运行产出，不自动等同于业务可用。',
  }
})

onMounted(async () => {
  if (!demo.taskId || demo.taskId !== taskId.value) {
    demo.restoreTask(taskId.value)
  }
  await demo.refresh()
  if (!demo.results) {
    await new Promise((r) => setTimeout(r, 600))
    await demo.refresh()
  }
})
</script>

<template>
  <DemoShell
    :show-stages="true"
    :task-summary="`${basinLabel(demo.draft.basin_id)} · 最终结果`"
  >
    <section class="results">
      <p class="eyebrow">展示结果</p>
      <h1>{{ conclusion.title }}</h1>
      <p class="lede">{{ conclusion.body }}</p>
      <p class="mode-line">
        数据来源：<strong>{{ modeLabel }}</strong>。历史资料计算不等于当前业务预报。
      </p>

      <div class="chart-card">
        <div class="chart-head">
          <h2>流量曲线</h2>
          <p>
            横轴为日期，纵轴为流量（m³/s）。蓝色为主预测提前期；观测对照仅在结果中提供时绘制。无依据时不绘制置信区间。
          </p>
        </div>
        <ForecastChart :forecasts="demo.results?.forecasts || []" />
      </div>

      <div class="info-grid">
        <article>
          <h3>预测时段</h3>
          <p>{{ demo.draft.start_date }} 至 {{ demo.draft.end_date }}</p>
        </article>
        <article>
          <h3>方案决定</h3>
          <p>{{ decision.title }}</p>
        </article>
        <article>
          <h3>评价情况</h3>
          <p>
            <template v-if="demo.results?.metrics?.NSE != null">
              NSE {{ Number(demo.results.metrics.NSE).toFixed(3) }}
            </template>
            <template v-else>尚未提供评价摘要</template>
          </p>
        </article>
      </div>

      <div class="card">
        <h2>工作回顾</h2>
        <ul v-if="doneActions.length">
          <li v-for="action in doneActions" :key="action">{{ actionDoneTitle(action) }}</li>
        </ul>
        <p v-else class="muted">还没有可回顾的完成动作。</p>
      </div>

      <div class="actions">
        <button type="button" class="secondary" @click="router.push({ name: 'judgment', params: { taskId } })">
          查看评价依据
        </button>
        <button type="button" class="secondary" @click="router.push({ name: 'process', params: { taskId } })">
          查看执行记录
        </button>
        <button type="button" class="secondary" @click="demo.refresh()">重新加载结果</button>
        <a
          v-for="name in reports"
          :key="name"
          class="secondary link"
          :href="`/api/tasks/${encodeURIComponent(taskId)}/report/${encodeURIComponent(name)}`"
          target="_blank"
          rel="noreferrer"
        >
          打开报告 · {{ name }}
        </a>
      </div>
    </section>
  </DemoShell>
</template>

<style scoped>
.results {
  max-width: 980px;
  margin: 0 auto;
  display: grid;
  gap: 1rem;
  padding: 0.5rem 0 2rem;
  animation: enter 260ms ease-out;
}
@keyframes enter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.eyebrow {
  margin: 0;
  color: var(--tertiary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
h1 {
  margin: 0;
  font-size: clamp(32px, 4.2vw, 40px);
  letter-spacing: -0.03em;
  max-width: 28ch;
}
.lede,
.mode-line {
  margin: 0;
  color: var(--secondary);
  font-size: 18px;
  max-width: 46rem;
}
.mode-line {
  font-size: 16px;
}
.chart-card,
.card,
.info-grid article {
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}
.chart-card {
  padding: 1rem 1.1rem 0.5rem;
}
.chart-head h2,
.card h2 {
  margin: 0 0 0.35rem;
  font-size: 18px;
}
.chart-head p,
.muted {
  margin: 0 0 0.75rem;
  color: var(--secondary);
  font-size: 16px;
}
.info-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
}
.info-grid article {
  padding: 1rem;
}
h3 {
  margin: 0 0 0.35rem;
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--tertiary);
}
.info-grid p {
  margin: 0;
  font-size: 22px;
  letter-spacing: -0.02em;
}
.card {
  padding: 1rem 1.1rem;
}
ul {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--secondary);
  font-size: 17px;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}
.secondary,
.link {
  appearance: none;
  border: 0;
  height: var(--control-h);
  min-height: var(--control-h);
  padding: 0 0.85rem;
  border-radius: 8px;
  background: rgba(120, 120, 128, 0.1);
  color: var(--label);
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  text-decoration: none;
}
@media (max-width: 800px) {
  .info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
