<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DemoShell from '../layouts/DemoShell.vue'
import { useDemoStore } from '../stores/demo'
import { basinLabel, gateDecisionZh } from '../demo/stages'

const route = useRoute()
const router = useRouter()
const demo = useDemoStore()
const taskId = computed(() => String(route.params.taskId))

const gateStatus = computed(() => {
  const fromResults = demo.results?.gate?.status
  if (typeof fromResults === 'string') return fromResults
  const resolve = [...demo.timeline].reverse().find((t) => t.action === 'A09_RESOLVE')
  const gate = [...demo.timeline].reverse().find((t) => t.action === 'A08_GATE')
  return (resolve?.status || gate?.status || null) as string | null
})

const decision = computed(() => gateDecisionZh(gateStatus.value))
const gatePayload = computed(() => (demo.results?.gate || {}) as Record<string, unknown>)
const metrics = computed(() => demo.results?.metrics || {})
const hasComparable = computed(() => {
  const g = gatePayload.value
  return Boolean(
    g.baseline_metrics ||
      g.candidate_metrics ||
      metrics.value.NSE != null ||
      metrics.value.KGE != null,
  )
})
const compareWindow = computed(() => {
  const g = gatePayload.value
  const start = (g.validation_start as string) || demo.draft.start_date
  const end = (g.validation_end as string) || demo.draft.end_date
  return `${start} 至 ${end}`
})

onMounted(async () => {
  if (!demo.taskId || demo.taskId !== taskId.value) {
    demo.restoreTask(taskId.value)
  }
  await demo.refresh()
})

watch(
  () => [demo.followScreen, demo.isCompleted, demo.isFailed] as const,
  ([follow, completed, failed]) => {
    if (!follow) return
    if (completed || failed) {
      void router.push({ name: 'results', params: { taskId: taskId.value } })
    }
  },
)
</script>

<template>
  <DemoShell
    :show-stages="true"
    :task-summary="`${basinLabel(demo.draft.basin_id)} · 方案判断`"
  >
    <section class="judge">
      <p class="eyebrow">解释判断</p>
      <h1 :data-tone="decision.tone">{{ decision.title }}</h1>
      <p class="reason">{{ decision.reason }}</p>

      <div v-if="hasComparable" class="card">
        <h2>比较说明</h2>
        <p>
          比较时段：{{ compareWindow }}。评价优先看验证窗口上的整体拟合与高流量表现，而不是单一综合分数。
        </p>
        <dl>
          <div>
            <dt>原方案与候选方案</dt>
            <dd>
              检查结论：{{ decision.title }}
              <template v-if="metrics.NSE != null"> · NSE {{ Number(metrics.NSE).toFixed(3) }}</template>
              <template v-if="metrics.KGE != null"> · KGE {{ Number(metrics.KGE).toFixed(3) }}</template>
            </dd>
          </div>
          <div>
            <dt>最终采用</dt>
            <dd>
              {{
                demo.results?.scheme?.scheme_id
                  ? `已锁定方案（${decision.title}）`
                  : '方案锁定尚未完成'
              }}
            </dd>
          </div>
        </dl>
      </div>
      <p v-else class="muted">完整对比数值将在结果可用后展示；此处先说明决定与原因。</p>

      <div class="actions">
        <button type="button" class="secondary" @click="router.push({ name: 'execute', params: { taskId } })">
          返回执行
        </button>
        <button
          type="button"
          class="primary"
          @click="router.push({ name: demo.isCompleted || demo.isFailed ? 'results' : 'execute', params: { taskId } })"
        >
          {{ demo.isCompleted || demo.isFailed ? '查看最终结果' : '继续跟随执行' }}
        </button>
      </div>
    </section>
  </DemoShell>
</template>

<style scoped>
.judge {
  max-width: 880px;
  margin: 0 auto;
  display: grid;
  gap: 1rem;
  padding: 1rem 0 2rem;
  animation: enter 220ms ease-out;
}
@keyframes enter {
  from {
    opacity: 0;
    transform: translateY(6px);
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
  font-size: clamp(32px, 4.5vw, 40px);
  letter-spacing: -0.03em;
}
h1[data-tone='ok'] {
  color: var(--success);
}
h1[data-tone='keep'] {
  color: var(--label);
}
h1[data-tone='rollback'] {
  color: var(--caution);
}
h1[data-tone='unknown'] {
  color: var(--secondary);
}
.reason {
  margin: 0;
  font-size: 22px;
  color: var(--secondary);
  max-width: 36rem;
}
.card {
  padding: 1.15rem 1.2rem;
  border-radius: var(--radius-lg);
  background: var(--surface);
  border: 1px solid var(--separator);
  box-shadow: var(--shadow);
  display: grid;
  gap: 0.7rem;
}
h2 {
  margin: 0;
  font-size: 18px;
}
p,
.muted {
  margin: 0;
  color: var(--secondary);
  font-size: 16px;
}
dl {
  margin: 0;
  display: grid;
  gap: 0.55rem;
}
dl > div {
  display: grid;
  gap: 0.15rem;
}
dt {
  color: var(--tertiary);
  font-size: 12px;
  font-weight: 700;
}
dd {
  margin: 0;
  font-size: 17px;
}
.actions {
  display: flex;
  gap: 0.55rem;
  flex-wrap: wrap;
}
.primary,
.secondary {
  appearance: none;
  border: 0;
  height: var(--control-h);
  min-height: var(--control-h);
  padding: 0 0.85rem;
  border-radius: 8px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
}
.primary {
  background: var(--blue);
  color: #fff;
}
.secondary {
  background: rgba(120, 120, 128, 0.12);
  color: var(--label);
}
</style>
