<script setup lang="ts">
import { computed } from 'vue'
import type { CalibrationComparisonPoint } from '../types/api'

const props = withDefaults(
  defineProps<{
    points: CalibrationComparisonPoint[]
    showInitial?: boolean
  }>(),
  { showInitial: false },
)

const width = 960
const height = 340
const pad = { left: 58, right: 24, top: 24, bottom: 44 }
const plotWidth = width - pad.left - pad.right
const plotHeight = height - pad.top - pad.bottom

const values = computed(() => {
  const rows = props.points.flatMap((p) => [p.observed, p.calibrated, ...(props.showInitial && p.initial != null ? [p.initial] : [])])
  return rows.length ? rows : [0, 1]
})
const minY = computed(() => Math.min(0, ...values.value))
const maxY = computed(() => Math.max(...values.value, 1))
const rangeY = computed(() => Math.max(1e-9, maxY.value - minY.value))

function x(index: number) {
  if (props.points.length <= 1) return pad.left + plotWidth / 2
  return pad.left + (index / (props.points.length - 1)) * plotWidth
}
function y(value: number) {
  return pad.top + ((maxY.value - value) / rangeY.value) * plotHeight
}
function line(key: 'observed' | 'calibrated' | 'initial') {
  const rows = props.points
    .map((point, index) => {
      const value = point[key]
      return value == null ? null : `${x(index).toFixed(1)},${y(value).toFixed(1)}`
    })
    .filter(Boolean)
  return rows.join(' ')
}
const ticks = computed(() => [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
  y: pad.top + ratio * plotHeight,
  value: maxY.value - ratio * rangeY.value,
})))
const dateLabels = computed(() => {
  if (!props.points.length) return []
  const indexes = [...new Set([0, Math.floor((props.points.length - 1) / 2), props.points.length - 1])]
  return indexes.map((index) => ({ index, label: props.points[index]?.time || '' }))
})
</script>

<template>
  <div class="comparison-chart" data-test="calibration-comparison-chart">
    <div v-if="!points.length" class="empty">
      暂无可发布的率定后计算流量与实测流量对比序列。
    </div>
    <template v-else>
      <div class="legend" aria-label="图例">
        <span><i class="observed" />Observed 实测</span>
        <span><i class="calibrated" />Calibrated 率定后</span>
        <span v-if="showInitial && points.some((p) => p.initial != null)"><i class="initial" />Initial 初始方案</span>
      </div>
      <svg :viewBox="`0 0 ${width} ${height}`" role="img" aria-label="率定后模拟流量与实测流量过程线">
        <g class="grid">
          <template v-for="tick in ticks" :key="tick.y">
            <line :x1="pad.left" :x2="width - pad.right" :y1="tick.y" :y2="tick.y" />
            <text :x="pad.left - 10" :y="tick.y + 4" text-anchor="end">{{ tick.value.toFixed(1) }}</text>
          </template>
        </g>
        <polyline class="series observed" :points="line('observed')" />
        <polyline class="series calibrated" :points="line('calibrated')" />
        <polyline v-if="showInitial" class="series initial" :points="line('initial')" />
        <g class="dates">
          <text
            v-for="item in dateLabels"
            :key="item.index"
            :x="x(item.index)"
            :y="height - 14"
            :text-anchor="item.index === 0 ? 'start' : item.index === points.length - 1 ? 'end' : 'middle'"
          >{{ item.label }}</text>
        </g>
        <text class="axis-title" x="16" :y="height / 2" transform="rotate(-90 16 170)" text-anchor="middle">Q (m³/s)</text>
      </svg>
    </template>
  </div>
</template>

<style scoped>
.comparison-chart { width: 100%; }
.empty { min-height: 220px; display: grid; place-items: center; color: var(--secondary); border: 1px dashed var(--separator); border-radius: 12px; }
.legend { display: flex; flex-wrap: wrap; gap: 18px; margin: 0 0 10px; font-size: 12px; color: var(--secondary); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 18px; height: 3px; border-radius: 99px; display: inline-block; }
.legend .observed { background: #111827; }
.legend .calibrated { background: #2563eb; }
.legend .initial { background: #9ca3af; }
svg { width: 100%; min-height: 280px; overflow: visible; }
.grid line { stroke: rgba(100, 116, 139, 0.16); stroke-width: 1; }
.grid text, .dates text, .axis-title { fill: #64748b; font-size: 11px; }
.series { fill: none; stroke-width: 2.2; stroke-linejoin: round; stroke-linecap: round; vector-effect: non-scaling-stroke; }
.series.observed { stroke: #111827; }
.series.calibrated { stroke: #2563eb; }
.series.initial { stroke: #9ca3af; stroke-dasharray: 6 5; stroke-width: 1.4; }
</style>
