<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DemoShell from '../layouts/DemoShell.vue'
import { useDemoStore } from '../stores/demo'
import { basinLabel, forcingLabel } from '../demo/stages'

const route = useRoute()
const router = useRouter()
const demo = useDemoStore()
const busy = ref(false)
const localError = ref<string | null>(null)

const taskId = computed(() => String(route.params.taskId))
const summary = computed(
  () =>
    `${basinLabel(demo.draft.basin_id)} · ${demo.draft.start_date} 至 ${demo.draft.end_date}`,
)
const historicalTitle = computed(
  () => demo.mode === 'replay' || demo.draft.forcing_mode === 'R',
)

onMounted(() => {
  if (!demo.taskId) {
    demo.restoreTask(taskId.value, demo.mode)
  }
})

async function start() {
  localError.value = null
  busy.value = true
  try {
    if (!demo.taskId) demo.taskId = taskId.value
    await demo.startRun()
    if (demo.mode === 'replay' && demo.isCompleted) {
      await router.push({ name: 'results', params: { taskId: taskId.value } })
    } else {
      await router.push({ name: 'execute', params: { taskId: taskId.value } })
    }
  } catch (err) {
    localError.value = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <DemoShell :task-summary="summary">
    <section class="brief">
      <p class="eyebrow">交代目标</p>
      <h1>
        {{
          historicalTitle
            ? '用历史资料演示一次三天流量预测'
            : '查看这个流域未来三天的流量变化'
        }}
      </h1>
      <p class="meta">
        {{ basinLabel(demo.draft.basin_id) }}
        <span aria-hidden="true">·</span>
        {{ demo.draft.start_date }} 至 {{ demo.draft.end_date }}
        <span aria-hidden="true">·</span>
        {{ forcingLabel(demo.draft.forcing_mode) }}
      </p>
      <p class="lede">系统将检查资料、完成计算，并整理结果与判断依据。</p>
      <p v-if="demo.mode === 'replay'" class="mode-note">
        当前为案例回放，展示已完成任务的真实记录，不会重新启动计算。
      </p>
      <p v-if="localError" class="error">{{ localError }}</p>
      <button class="primary" type="button" :disabled="busy" @click="start">
        {{
          busy
            ? '正在启动…'
            : demo.mode === 'replay'
              ? '开始回放'
              : '开始运行'
        }}
      </button>
    </section>
  </DemoShell>
</template>

<style scoped>
.brief {
  min-height: calc(100dvh - 120px);
  display: grid;
  align-content: center;
  justify-items: start;
  gap: 1rem;
  max-width: 920px;
  margin: 0 auto;
  padding: 2rem 0 4rem;
  animation: enter 240ms ease-out;
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
  font-size: clamp(40px, 5.8vw, 56px);
  line-height: 1.12;
  letter-spacing: -0.035em;
  max-width: 14ch;
}
.meta {
  margin: 0;
  color: var(--secondary);
  font-size: 18px;
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}
.lede {
  margin: 0.25rem 0 0.5rem;
  color: var(--secondary);
  font-size: 22px;
  max-width: 34rem;
}
.mode-note {
  margin: 0;
  color: var(--caution);
  font-size: 16px;
}
.primary {
  appearance: none;
  border: 0;
  height: var(--control-h-lg);
  min-height: var(--control-h-lg);
  padding: 0 1.1rem;
  border-radius: 8px;
  background: var(--blue);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  width: auto;
}
.primary:active {
  transform: scale(0.98);
}
.primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.error {
  margin: 0;
  color: var(--danger);
}
</style>
