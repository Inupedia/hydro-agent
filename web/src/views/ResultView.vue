<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ForecastChart from '../components/ForecastChart.vue'
import HydrographComparisonChart from '../components/HydrographComparisonChart.vue'
import ProcessStory from '../components/ProcessStory.vue'
import ReportLinks from '../components/ReportLinks.vue'
import ArchifyWorkflow from '../components/ArchifyWorkflow.vue'
import ResearchEvidencePanel from '../components/ResearchEvidencePanel.vue'
import { api } from '../api/client'
import { useResultsStore } from '../stores/results'
import type { TimelineItem } from '../types/api'
import { hydrographTitleZh } from '../chartTheme'

const route = useRoute()
const router = useRouter()
const store = useResultsStore()
const taskId = computed(() => String(route.params.taskId))
const timeline = ref<TimelineItem[]>([])
const showTech = ref(false)

onMounted(async () => {
  await store.load(taskId.value)
  try {
    timeline.value = await api.getTimeline(taskId.value)
  } catch {
    timeline.value = []
  }
})
</script>

<template>
  <section class="page result-page">
    <header class="header result-header">
      <div>
        <h1>结果说明</h1>
        <p class="lede">下面用普通人能看懂的话，说明系统自动走完了哪些步骤、为什么做出这个决定。</p>
      </div>
      <div class="actions">
        <button type="button" class="secondary" @click="router.push(`/tasks/${taskId}/run`)">
          回看过程
        </button>
        <button type="button" class="secondary" @click="router.push('/')">再建一个任务</button>
      </div>
    </header>

    <ProcessStory :result="store.result" :timeline="timeline" />

    <ArchifyWorkflow view="gate-keep" height="480px" />

    <section v-if="store.result?.test_hydrograph?.series?.length" class="chart-block content-surface">
      <h3>{{ hydrographTitleZh(store.result.test_hydrograph) }}</h3>
      <p class="lede">独立检验窗上的观测与最终冻结方案。KEEP/ROLLBACK 时冻结的仍是原方案，不会标成已率定。</p>
      <HydrographComparisonChart :comparison="store.result.test_hydrograph" />
    </section>

    <ResearchEvidencePanel :task-id="taskId" />

    <section v-if="store.result?.calibration_hydrograph?.series?.length" class="chart-block content-surface">
      <h3>{{ hydrographTitleZh(store.result.calibration_hydrograph) }}</h3>
      <p class="lede">率定窗上的观测、基线方案与候选方案，含预热期阴影。</p>
      <HydrographComparisonChart :comparison="store.result.calibration_hydrograph" />
    </section>

    <section class="chart-block content-surface">
      <h3>预报记录（提前 1 / 2 / 3 天）</h3>
      <p class="lede">横轴是起报日期。这是滚动预报存档，不能替代上面的连续过程线对比。</p>
      <ForecastChart :forecasts="store.result?.forecasts || []" />
    </section>

    <ReportLinks :task-id="taskId" :artifacts="store.result?.report_artifacts || []" />

    <section class="tech content-surface">
      <button type="button" class="linkish" data-test="toggle-tech" @click="showTech = !showTech">
        {{ showTech ? '收起技术细节' : '展开技术细节（方案编号、哈希等）' }}
      </button>
      <div v-if="showTech && store.result?.scheme" class="tech-panel" data-test="tech-panel">
        <p><strong>冻结方案</strong>（技术状态：{{ store.result.scheme.status }}）</p>
        <p>模型标识：{{ store.result.scheme.model_id }}</p>
        <p>方案编号：{{ store.result.scheme.scheme_id }}</p>
        <p>内容哈希：{{ store.result.scheme.content_hash.slice(0, 12) }}</p>
        <p v-if="store.result.gate">Gate 状态：{{ store.result.gate.status }}</p>
        <p v-if="store.result.gate?.reasons">
          Gate 原因码：
          {{
            Array.isArray(store.result.gate.reasons)
              ? store.result.gate.reasons.join('；')
              : store.result.gate.reasons
          }}
        </p>
      </div>
    </section>
  </section>
</template>

<style scoped>
.result-page {
  min-height: 100dvh;
}

.result-header {
  position: sticky;
  top: 0;
  z-index: 20;
  margin: -8px -8px 20px;
  padding: 12px 8px;
  background: var(--glass);
  border-bottom: 1px solid var(--glass-edge);
  -webkit-backdrop-filter: blur(24px) saturate(140%);
  backdrop-filter: blur(24px) saturate(140%);
}

.secondary {
  min-height: var(--control-h);
  padding: 0 14px;
  color: var(--accent-text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.chart-block,
.tech {
  margin: 24px 0;
}

.content-surface {
  padding: 20px 24px;
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}

.tech-panel {
  margin-top: 12px;
  padding: 14px 16px;
  color: var(--text-secondary);
  background: var(--surface-secondary);
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
  font-size: 13px;
}

@media (max-width: 640px) {
  .result-header {
    position: static;
    margin: 0 0 16px;
  }

  .content-surface {
    padding: 16px;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .result-header {
    background: var(--surface);
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
  }
}
</style>
