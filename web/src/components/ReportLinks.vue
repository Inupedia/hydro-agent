<script setup lang="ts">
const props = defineProps<{ taskId: string; artifacts: string[] }>()

function href(name: string) {
  return `/api/tasks/${props.taskId}/report/${name}`
}
</script>

<template>
  <section>
    <h3>报告</h3>
    <ul>
      <li v-for="name in artifacts" :key="name">
        <a
          :href="href(name)"
          :data-test="name === 'report.json' ? 'report-json' : name === 'report.md' ? 'report-md' : undefined"
        >{{ name }}</a>
      </li>
    </ul>
  </section>
</template>
