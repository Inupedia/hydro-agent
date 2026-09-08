<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BusinessTimeline from '../components/BusinessTimeline.vue'
import { useRunStore } from '../stores/run'

const route = useRoute()
const router = useRouter()
const store = useRunStore()
const taskId = computed(() => String(route.params.taskId))

onMounted(async () => {
  await store.start(taskId.value)
  store.startPolling(taskId.value)
})
onUnmounted(() => store.stopPolling())
</script>

<template>
  <section class="page">
    <header class="header">
      <div>
        <h1>运行中</h1>
        <p>阶段 {{ store.run?.phase }} · 状态 {{ store.run?.status }}</p>
        <p>
          剩余决策轮次 {{ store.run?.agent_rounds_remaining }} · 剩余优化周期
          {{ store.run?.optimization_cycles_remaining }}
        </p>
      </div>
      <div class="actions">
        <button type="button" @click="store.pause(taskId)">暂停</button>
        <button type="button" @click="store.resume(taskId)">继续</button>
        <button type="button" @click="router.push(`/tasks/${taskId}/results`)">查看结果</button>
      </div>
    </header>
    <h2>业务时间线</h2>
    <BusinessTimeline :items="store.timeline" />
  </section>
</template>
