<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ForecastChart from '../components/ForecastChart.vue'
import ProcessStory from '../components/ProcessStory.vue'
import ReportLinks from '../components/ReportLinks.vue'
import ArchifyWorkflow from '../components/ArchifyWorkflow.vue'
import { api } from '../api/client'
import { useResultsStore } from '../stores/results'
import type { TimelineItem } from '../types/api'

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
  <section class="page">
    <header class="header">
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

    <section class="chart-block">
      <h3>预报曲线（演示数据）</h3>
      <p class="lede">横轴是起报日期，纵轴是流量（立方米/秒）。三条线分别是提前 1 / 2 / 3 天的预报。</p>
      <ForecastChart :forecasts="store.result?.forecasts || []" />
    </section>

    <ReportLinks :task-id="taskId" :artifacts="store.result?.report_artifacts || []" />

    <section class="tech">
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
.secondary {
  background: transparent;
  color: #1f6b4a;
  border: 1px solid rgba(31, 107, 74, 0.35);
}

.chart-block {
  margin: 1.5rem 0 2rem;
}

.tech {
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(16, 35, 28, 0.12);
}

.tech-panel {
  margin-top: 0.75rem;
  padding: 0.9rem 1rem;
  background: rgba(255, 255, 255, 0.65);
  border: 1px solid rgba(16, 35, 28, 0.08);
  font-size: 0.9rem;
  color: rgba(16, 35, 28, 0.8);
}
</style>
