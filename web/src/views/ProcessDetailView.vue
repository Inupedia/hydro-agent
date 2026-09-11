<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DemoShell from '../layouts/DemoShell.vue'
import { useDemoStore } from '../stores/demo'
import { actionTitle, basinLabel } from '../demo/stages'
import { diagramHtmlFor } from '../generated/workflow'

const route = useRoute()
const router = useRouter()
const demo = useDemoStore()
const taskId = computed(() => String(route.params.taskId))
const diagramSrc = computed(
  () => `/diagrams/${diagramHtmlFor(demo.taskMeta?.workflow_version)}?theme=light&embed=true&motion=still`,
)

onMounted(() => {
  if (!demo.taskId) demo.restoreTask(taskId.value)
})
</script>

<template>
  <DemoShell
    :show-stages="true"
    :task-summary="`${basinLabel(demo.draft.basin_id)} · 完整过程`"
  >
    <section class="process">
      <header class="head">
        <div>
          <p class="eyebrow">详细过程</p>
          <h1>系统实际执行路径</h1>
          <p class="lede">蓝色强调对应最近动作。流程图用于解释，不作为主操作入口。</p>
        </div>
        <button type="button" class="secondary" @click="router.back()">返回</button>
      </header>

      <div class="frame">
        <iframe :src="diagramSrc" title="Hydro-Agent 流程详图" />
      </div>

      <div class="log card">
        <h2>执行记录</h2>
        <ol v-if="demo.timeline.length">
          <li v-for="item in demo.timeline" :key="item.id" :data-status="item.status">
            <strong>{{ item.action ? actionTitle(item.action) : item.label }}</strong>
            <span>{{ item.label }}</span>
            <em>{{
              item.status === 'ok' || item.status === 'done' || item.status === 'completed'
                ? '已完成'
                : item.status === 'skipped'
                  ? '已跳过'
                  : item.status === 'failed' || item.status === 'error'
                    ? '失败'
                    : item.status
            }}</em>
          </li>
        </ol>
        <p v-else class="muted">暂无执行记录。</p>
      </div>
    </section>
  </DemoShell>
</template>

<style scoped>
.process {
  max-width: 1100px;
  margin: 0 auto;
  display: grid;
  gap: 1rem;
}
.head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: start;
}
.eyebrow {
  margin: 0 0 0.35rem;
  color: var(--tertiary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
h1 {
  margin: 0;
  font-size: 28px;
  letter-spacing: -0.03em;
}
.lede {
  margin: 0.4rem 0 0;
  color: var(--secondary);
}
.frame {
  border-radius: var(--radius-lg);
  overflow: hidden;
  border: 1px solid var(--separator);
  background: var(--surface);
  box-shadow: var(--shadow);
  min-height: 520px;
}
iframe {
  width: 100%;
  height: min(62vh, 640px);
  border: 0;
  background: #fff;
}
.card {
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: var(--radius-lg);
  padding: 1rem 1.1rem;
  box-shadow: var(--shadow);
}
h2 {
  margin: 0 0 0.7rem;
  font-size: 16px;
}
ol {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.55rem;
}
li {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.4fr) auto;
  gap: 0.6rem;
  padding: 0.7rem 0.8rem;
  border-radius: 12px;
  background: #fafafa;
}
.muted {
  margin: 0;
  color: var(--secondary);
}
.secondary {
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
}
@media (max-width: 800px) {
  li {
    grid-template-columns: 1fr;
  }
}
</style>
