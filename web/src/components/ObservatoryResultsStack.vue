<script setup lang="ts">
import { ref } from 'vue'
import HydrographComparisonChart from './HydrographComparisonChart.vue'
import SchemeComparisonMetricsChart from './SchemeComparisonMetricsChart.vue'
import AgentCalibrationPanel from './AgentCalibrationPanel.vue'
import ResearchEvidencePanel from './ResearchEvidencePanel.vue'
import ParamTuningPanel from './ParamTuningPanel.vue'
import ReportSectionHead from './ReportSectionHead.vue'
import type { HydrographComparison, ResultSummary } from '../types/api'

defineProps<{
  taskId: string | null
  comparison: HydrographComparison | null
  results: ResultSummary | null
  showTuning: boolean
  overline: string
  title: string
  subtitle: string
  meta: string
}>()

const forecastSurface = ref<HTMLElement | null>(null)
const tuningMount = ref<HTMLElement | null>(null)

defineExpose({ forecastSurface, tuningMount })
</script>

<template>
  <div class="results-stack" data-test="forecast-surface">
    <section ref="forecastSurface" class="report-module">
      <ReportSectionHead :overline="overline" :title="title" :subtitle="subtitle">
        <template #aside>
          <span class="module-meta">{{ meta }}</span>
        </template>
      </ReportSectionHead>
      <template v-if="comparison">
        <HydrographComparisonChart :comparison="comparison" />
      </template>
      <SchemeComparisonMetricsChart :comparison="comparison" :gate="results?.gate" />
    </section>
    <AgentCalibrationPanel
      v-if="taskId"
      :task-id="taskId"
      :comparison="results?.calibration_hydrograph"
      :diagnosis="results?.diagnosis"
    />
    <ResearchEvidencePanel v-if="taskId" :task-id="taskId" />
    <div v-if="showTuning" ref="tuningMount" class="tuning-mount">
      <ParamTuningPanel
        :diagnosis="results?.diagnosis"
        :optimize="results?.optimize"
        :scheme="results?.scheme"
      />
    </div>
  </div>
</template>
