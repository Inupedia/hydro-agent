<script setup lang="ts">
import { computed } from 'vue'
import type { ResultSummary, TimelineItem } from '../types/api'

const props = defineProps<{
  result: ResultSummary | null
  timeline: TimelineItem[]
}>()

const gateStatus = computed(() => {
  const status = props.result?.gate?.status
  return typeof status === 'string' ? status : null
})

const decisionPlain = computed(() => {
  const reasons = props.result?.gate?.reasons
  const metrics = (props.result?.gate?.metrics as Record<string, unknown> | undefined) || null
  const reasonCodes = Array.isArray(reasons) ? reasons.map(String) : []
  const absoluteFail = reasonCodes.some((r) => r.includes('insufficient_absolute_skill'))
  if (gateStatus.value === 'KEEP') {
    return {
      title: '系统决定：先不换方案',
      body: absoluteFail
        ? '候选方案相对略好，但绝对技巧仍低于门槛（insufficient_absolute_skill），因此保留原方案，避免把失败技能冻结成“成功”。'
        : '它试着微调了参数，但主指标提升幅度不够大（insufficient_primary_delta）。这不是卡死，而是主动选择“继续用原来更稳的方案”。',
    }
  }
  if (gateStatus.value === 'ACCEPT') {
    return {
      title: '系统决定：采用改进后的方案',
      body: '微调后的参数在关键指标上有稳定提升，且绝对技巧过线，因此采纳新方案并继续后续锁定与评估。',
    }
  }
  if (gateStatus.value === 'ROLLBACK') {
    return {
      title: '系统决定：退回原方案',
      body: '候选方案没有通过安全门槛，系统回到改动前的方案，避免把风险带进正式预报。',
    }
  }
  void metrics
  return {
    title: '系统决策',
    body: '已完成一次“预报 → 尝试改进 → 把关 → 锁定 → 回看 → 写报告”的自动流程。',
  }
})

const paramDeltaPlain = computed(() => {
  const delta = props.result?.scheme?.parameter_delta || {}
  const lines = Object.entries(delta)
    .sort((a, b) => Math.abs(Number(b[1])) - Math.abs(Number(a[1])))
    .slice(0, 8)
    .map(([key, value]) => `${key} ${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(3)}`)
  return lines.length ? lines.join('，') : null
})

const optimizePlain = computed(() => {
  const o = props.result?.optimize
  if (!o) return null
  const bits = [
    typeof o.strategy_id === 'string' ? `策略 ${o.strategy_id}` : null,
    typeof o.param_groups === 'string' && o.param_groups ? `参数组 ${o.param_groups}` : null,
    typeof o.objective === 'string' && o.objective ? `目标 ${o.objective}` : null,
  ].filter(Boolean)
  return bits.length ? bits.join('；') : null
})

const steps = computed(() => {
  const labels = props.timeline.map((item) => item.label)
  if (labels.length) {
    return labels.map((label, index) => ({
      n: index + 1,
      text: label,
    }))
  }
  return [
    { n: 1, text: '用现有方案做一次基础流量预报' },
    { n: 2, text: '在允许范围内尝试微调参数' },
    { n: 3, text: '用门槛规则检查是否值得换方案' },
    { n: 4, text: '锁定最终采用的方案，防止再被改动' },
    { n: 5, text: '按历史日期回放几次起报，看趋势' },
    { n: 6, text: '汇总评分并生成可读报告' },
  ]
})

const metricCards = computed(() => {
  const m = props.result?.metrics || {}
  return [
    {
      key: 'NSE',
      value: m.NSE,
      name: '整体吻合度',
      hint: '越接近 1 越好。演示值约 0.5，表示“大致跟得上，但仍有明显误差”。',
    },
    {
      key: 'KGE',
      value: m.KGE,
      name: '综合评分',
      hint: '同时看流量大小、波动形状和系统性偏差。',
    },
    {
      key: 'MAE',
      value: m.MAE,
      name: '平均误差',
      hint: '平均每次预报大约偏多少立方米每秒（m³/s）。',
    },
    {
      key: 'Bias',
      value: m.Bias,
      name: '整体偏向',
      hint: '负数表示整体略偏低，正数表示略偏高。',
    },
  ]
})

const schemePlain = computed(() => {
  const scheme = props.result?.scheme
  if (!scheme) return null
  if (scheme.status === 'frozen') {
    return '当前采用的方案已锁定（冻结）：后面评估和报告都基于这一版，不会再偷偷改参数。'
  }
  return '当前仍在使用工作方案，尚未锁定。'
})

const modelPlain = computed(() => {
  const id = props.result?.scheme?.model_id
  if (id === 'xaj') return '新安江模型（XAJ）：一种常见的流域产汇流概念模型，用来把降雨转换成河川流量。'
  return id ? `模型：${id}` : ''
})
</script>

<template>
  <section class="story" data-test="process-story">
    <header class="story-hero">
      <p class="eyebrow">这次自动做了什么</p>
      <h2>{{ decisionPlain.title }}</h2>
      <p class="lede">{{ decisionPlain.body }}</p>
      <p v-if="schemePlain" class="lede">{{ schemePlain }}</p>
      <p v-if="modelPlain" class="lede">{{ modelPlain }}</p>
      <p v-if="optimizePlain" class="lede">调参设定：{{ optimizePlain }}</p>
      <p v-if="paramDeltaPlain" class="lede">相对基础方案的参数变化：{{ paramDeltaPlain }}</p>
    </header>

    <section>
      <h3>过程（按时间顺序）</h3>
      <ol class="steps">
        <li v-for="step in steps" :key="step.n">
          <span class="step-n">{{ step.n }}</span>
          <span>{{ step.text }}</span>
        </li>
      </ol>
    </section>

    <section>
      <h3>怎么读这些分数</h3>
      <div class="metric-grid">
        <article v-for="card in metricCards" :key="card.key" class="metric-card">
          <p class="metric-name">{{ card.name }} <span class="metric-key">{{ card.key }}</span></p>
          <p class="metric-value">{{ card.value ?? '—' }}</p>
          <p class="metric-hint">{{ card.hint }}</p>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.story {
  display: grid;
  gap: 1.75rem;
  margin-bottom: 2rem;
}

.story-hero {
  padding: 1.25rem 1.35rem;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(16, 35, 28, 0.1);
}

.eyebrow {
  margin: 0 0 0.35rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-size: 0.75rem;
  color: rgba(16, 35, 28, 0.55);
}

.story-hero h2 {
  margin: 0 0 0.6rem;
  font-family: "IBM Plex Serif", Georgia, serif;
  font-size: 1.55rem;
}

.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.65rem;
}

.steps li {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
  padding: 0.7rem 0.85rem;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(16, 35, 28, 0.08);
}

.step-n {
  flex: 0 0 1.6rem;
  height: 1.6rem;
  border-radius: 999px;
  display: inline-grid;
  place-items: center;
  background: #1f6b4a;
  color: #fff;
  font-size: 0.85rem;
}

.metric-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.metric-card {
  padding: 0.85rem 0.95rem;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(16, 35, 28, 0.08);
}

.metric-name {
  margin: 0;
  font-size: 0.92rem;
}

.metric-key {
  color: rgba(16, 35, 28, 0.45);
  font-size: 0.8rem;
}

.metric-value {
  margin: 0.35rem 0;
  font-size: 1.45rem;
  font-family: "IBM Plex Serif", Georgia, serif;
}

.metric-hint {
  margin: 0;
  color: rgba(16, 35, 28, 0.7);
  font-size: 0.88rem;
}
</style>
