<script setup lang="ts">
const props = defineProps<{ taskId: string; artifacts: string[] }>()

function href(name: string) {
  return `/api/tasks/${props.taskId}/report/${name}`
}

function label(name: string) {
  if (name === 'report.md') return '阅读说明（Markdown）'
  if (name === 'report.json') return '下载指标数据（JSON）'
  if (name === 'test-hydrograph.csv') return '独立检验过程线（CSV）'
  if (name === 'calibration-comparison.csv') return '率定对比过程线（CSV）'
  return name
}
</script>

<template>
  <section v-if="artifacts.length">
    <h3>报告下载</h3>
    <p class="lede">说明文档面向阅读；JSON 给需要二次处理的人。</p>
    <ul>
      <li v-for="name in artifacts" :key="name">
        <a
          :href="href(name)"
          :data-test="name === 'report.json' ? 'report-json' : name === 'report.md' ? 'report-md' : undefined"
        >{{ label(name) }}</a>
      </li>
    </ul>
  </section>
</template>
