<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import ForecastChart from '../components/ForecastChart.vue'
import GateSummary from '../components/GateSummary.vue'
import ReportLinks from '../components/ReportLinks.vue'
import SchemeSummary from '../components/SchemeSummary.vue'
import { useResultsStore } from '../stores/results'

const route = useRoute()
const store = useResultsStore()
const taskId = computed(() => String(route.params.taskId))

onMounted(() => store.load(taskId.value))
</script>

<template>
  <section class="page">
    <h1>结果</h1>
    <SchemeSummary :scheme="store.result?.scheme ?? null" />
    <GateSummary :gate="store.result?.gate ?? null" />
    <section>
      <h3>指标</h3>
      <ul>
        <li v-for="(value, key) in store.result?.metrics || {}" :key="key">{{ key }}：{{ value }}</li>
      </ul>
    </section>
    <ForecastChart :forecasts="store.result?.forecasts || []" />
    <ReportLinks :task-id="taskId" :artifacts="store.result?.report_artifacts || []" />
  </section>
</template>
