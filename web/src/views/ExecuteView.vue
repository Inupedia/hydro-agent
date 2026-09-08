<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DemoShell from '../layouts/DemoShell.vue'
import { useDemoStore } from '../stores/demo'
import { actionExplain, actionTitle, basinLabel, providerErrorZh } from '../demo/stages'

const route = useRoute()
const router = useRouter()
const demo = useDemoStore()
const taskId = computed(() => String(route.params.taskId))
const visitedJudgment = ref(false)
const retryBusy = ref(false)

const currentAction = computed(
  () => demo.run?.llm_decision_action || demo.run?.last_action || demo.timeline.at(-1)?.action || null,
)
const latestEvent = computed(() => {
  const last = demo.timeline.at(-1)
  if (!last) return '尚未收到执行事件'
  return last.label || last.action || '已有执行进展'
})
const hasJudgment = computed(() => demo.timeline.some((t) => t.action === 'A09_RESOLVE'))
const providerError = computed(() => providerErrorZh(demo.run?.llm_error || demo.error))

const summary = computed(
  () => `${basinLabel(demo.draft.basin_id)} · 任务 ${taskId.value}`,
)

onMounted(() => {
  if (!demo.taskId || demo.taskId !== taskId.value) demo.restoreTask(taskId.value)
  else demo.startPolling()
})

watch(
  () => [demo.followScreen, hasJudgment.value, demo.isCompleted, demo.isFailed] as const,
  ([follow, judgment, completed, failed]) => {
    if (!follow) return
    if (providerError.value) return
    if (judgment && !visitedJudgment.value && !completed && !failed) {
      visitedJudgment.value = true
      void router.push({ name: 'judgment', params: { taskId: taskId.value } })
      return
    }
    if (completed || failed) {
      if (route.name !== 'results') {
        void router.push({ name: 'results', params: { taskId: taskId.value } })
      }
    }
  },
)

async function retryProvider() {
  retryBusy.value = true
  try {
    await demo.resumeCompute()
  } catch (err) {
    demo.error = String((err as Error).message || err)
  } finally {
    retryBusy.value = false
  }
}
</script>

<template>
  <DemoShell :show-stages="true" :task-summary="summary">
    <section class="execute">
      <p class="eyebrow">展示执行</p>
      <h1>{{ actionTitle(currentAction) }}</h1>
      <p class="explain">{{ actionExplain(currentAction) }}</p>

      <div class="progress-card">
        <div>
          <p class="label">最近进展</p>
          <p class="value">{{ latestEvent }}</p>
        </div>
        <div>
          <p class="label">运行状态</p>
          <p class="value">
            {{
              demo.mode === 'replay'
                ? '案例回放中'
                : demo.run?.paused
                  ? '已暂停计算'
                  : demo.isRunning
                    ? '正在实际运行'
                    : demo.isCompleted
                      ? '执行已完成'
                      : demo.isFailed
                        ? '执行失败'
                        : demo.run?.status || '等待中'
            }}
          </p>
        </div>
      </div>

      <div v-if="providerError" class="error-box">
        <p class="error">{{ providerError }}</p>
        <button
          type="button"
          class="primary"
          :disabled="retryBusy || demo.isRunning"
          @click="retryProvider"
        >
          {{ retryBusy ? '正在重试…' : '重试继续' }}
        </button>
      </div>
      <p v-else-if="demo.error" class="error">{{ demo.error }}</p>

      <div class="actions">
        <button type="button" class="secondary" @click="router.push({ name: 'process', params: { taskId } })">
          查看完整过程
        </button>
        <button
          v-if="hasJudgment"
          type="button"
          class="secondary"
          @click="router.push({ name: 'judgment', params: { taskId } })"
        >
          查看方案判断
        </button>
        <button
          v-if="demo.isCompleted || demo.isFailed"
          type="button"
          class="primary"
          @click="router.push({ name: 'results', params: { taskId } })"
        >
          查看结果
        </button>
      </div>
    </section>
  </DemoShell>
</template>

<style scoped>
.execute {
  max-width: 920px;
  margin: 0 auto;
  padding: 1rem 0 2rem;
  display: grid;
  gap: 1rem;
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
.explain {
  margin: 0;
  color: var(--secondary);
  font-size: 22px;
  max-width: 36rem;
}
.progress-card {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 0.85rem;
  padding: 1.1rem;
  border-radius: var(--radius-lg);
  background: var(--surface);
  border: 1px solid var(--separator);
  box-shadow: var(--shadow);
}
.label {
  margin: 0 0 0.25rem;
  color: var(--tertiary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.value {
  margin: 0;
  font-size: 18px;
  letter-spacing: -0.01em;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
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
.error {
  margin: 0;
  color: var(--danger);
  font-size: 14px;
}
.error-box {
  display: grid;
  gap: 0.55rem;
  justify-items: start;
  padding: 0.75rem 0.85rem;
  border-radius: 10px;
  background: var(--danger-soft);
  border: 1px solid rgba(215, 0, 21, 0.18);
}
@media (max-width: 720px) {
  .progress-card {
    grid-template-columns: 1fr;
  }
}
</style>
