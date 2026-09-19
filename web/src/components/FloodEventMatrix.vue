<script setup lang="ts">
import type { FloodEventDiagnosis } from '../types/api'

defineProps<{
  events: FloodEventDiagnosis[]
}>()

function metric(event: FloodEventDiagnosis, key: string) {
  const value = event.metrics?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function percent(value: number | null) {
  if (value == null) return '-'
  const body = (value * 100).toFixed(1)
  return `${value > 0 ? '+' : ''}${body}%`
}

function lag(value: number | null) {
  if (value == null) return '-'
  const body = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return `${value > 0 ? '+' : ''}${body} 步`
}

function magnitude(value: number | null) {
  if (value == null) return '-'
  return value.toFixed(2)
}

function evidenceLabel(event: FloodEventDiagnosis) {
  const status = event.status === 'available' ? '可用' : event.status || '未知'
  const basis = event.basis === 'rainfall_runoff' ? '降雨-径流' : '仅流量'
  return `${status} · ${basis}`
}
</script>

<template>
  <div class="matrix-wrap" data-test="flood-event-matrix">
    <table class="event-matrix">
      <thead>
        <tr>
          <th>事件</th>
          <th>时段</th>
          <th class="numeric">洪峰误差</th>
          <th class="numeric">峰现偏差</th>
          <th class="numeric">洪量误差</th>
          <th class="numeric">涨水段</th>
          <th class="numeric">退水段</th>
          <th>证据状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="event in events" :key="event.event_id">
          <td><code>{{ event.event_id }}</code></td>
          <td>{{ event.start }} → {{ event.end }}</td>
          <td class="numeric">{{ percent(metric(event, 'peak_relative_error')) }}</td>
          <td class="numeric">{{ lag(metric(event, 'peak_timing_lag_steps')) }}</td>
          <td class="numeric">{{ percent(metric(event, 'volume_relative_error')) }}</td>
          <td class="numeric">{{ magnitude(metric(event, 'rising_limb_mae')) }}</td>
          <td class="numeric">{{ magnitude(metric(event, 'recession_mae')) }}</td>
          <td>{{ evidenceLabel(event) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.matrix-wrap {
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
  background: var(--surface-secondary);
}
.event-matrix {
  width: 100%;
  min-width: 880px;
  border-collapse: collapse;
  font-size: 13px;
}
.event-matrix th,
.event-matrix td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--separator);
  text-align: left;
  white-space: nowrap;
}
.event-matrix th {
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 600;
}
.event-matrix tbody tr:last-child td {
  border-bottom: 0;
}
.event-matrix code {
  color: var(--text-secondary);
  font-size: 12px;
}
.numeric {
  text-align: right !important;
  font-variant-numeric: tabular-nums;
}
</style>
