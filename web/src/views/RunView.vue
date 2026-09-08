<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BusinessTimeline from '../components/BusinessTimeline.vue'
import ArchifyWorkflow from '../components/ArchifyWorkflow.vue'
import { useRunStore } from '../stores/run'

const route = useRoute()
const router = useRouter()
const store = useRunStore()
const taskId = computed(() => String(route.params.taskId))

const statusPlain = computed(() => {
  const status = store.run?.status
  if (status === 'running') return '正在自动执行'
  if (status === 'completed') return '已跑完'
  if (status === 'paused') return '已暂停'
  if (status === 'created') return '刚创建，准备启动'
  return status || '加载中'
})

onMounted(async () => {
  await store.refresh(taskId.value)
  const alreadyDone =
    store.run?.status === 'completed' ||
    (store.run?.phase === 'E' && store.run?.needs_follow_up === false)
  if (!alreadyDone) {
    await store.start(taskId.value)
  }
  store.startPolling(taskId.value)
})
onUnmounted(() => store.stopPolling())
</script>

<template>
  <section class="page">
    <header class="header">
      <div>
        <h1>执行过程</h1>
        <p class="lede">
          系统正在按固定步骤自动工作：预报 → 尝试改进 → 把关 → 锁定 → 回看 → 写报告。
          你不需要勾选任何技术动作。
        </p>
        <p><strong>{{ statusPlain }}</strong></p>
      </div>
      <div class="actions">
        <button type="button" @click="store.pause(taskId)">暂停</button>
        <button type="button" @click="store.resume(taskId)">继续</button>
        <button type="button" @click="router.push(`/tasks/${taskId}/results`)">看结果说明</button>
      </div>
    </header>
    <ArchifyWorkflow view="happy-path" height="460px" />
    <h2>发生了什么</h2>
    <BusinessTimeline :items="store.timeline" />
  </section>
</template>
