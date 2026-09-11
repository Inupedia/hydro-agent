<script setup lang="ts">
import { computed } from 'vue'
import { diagramHtmlFor } from '../generated/workflow'

const props = withDefaults(
  defineProps<{
    view?: 'happy-path' | 'gate-keep' | 'evidence'
    height?: string
  }>(),
  {
    view: 'happy-path',
    height: '520px',
  },
)

const src = computed(
  () =>
    `/diagrams/${diagramHtmlFor()}?theme=light&present=1&play=1#view=${props.view}`,
)
</script>

<template>
  <section class="archify" data-test="archify-workflow">
    <div class="archify-head">
      <div>
        <h3>流程地图（Archify）</h3>
        <p class="lede">可点击节点、切换视图；KEEP 表示“提升不够、保持原方案”，不是卡死。</p>
      </div>
      <a class="open" :href="src" target="_blank" rel="noreferrer">全屏打开</a>
    </div>
    <iframe
      class="frame"
      title="Hydro-Agent Archify workflow"
      :src="src"
      :style="{ height }"
      loading="lazy"
    />
  </section>
</template>

<style scoped>
.archify {
  margin: 1.25rem 0 1.75rem;
}

.archify-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: end;
  margin-bottom: 0.65rem;
}

.archify-head h3 {
  margin: 0 0 0.25rem;
}

.open {
  color: #1f6b4a;
  white-space: nowrap;
}

.frame {
  width: 100%;
  border: 1px solid rgba(16, 35, 28, 0.12);
  background: #fff;
  border-radius: 4px;
}
</style>
