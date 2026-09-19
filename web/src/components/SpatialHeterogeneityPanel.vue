<script setup lang="ts">
import { computed } from 'vue'
import type {
  BasinSpatialProfile,
  UnitSchemeCandidate,
  UnitSchemeRecommendation,
} from '../types/api'

const props = defineProps<{
  profile?: BasinSpatialProfile | null
  profileStatus?: 'available' | 'partial' | 'unknown' | null
  candidates?: UnitSchemeCandidate[]
  recommendation?: UnitSchemeRecommendation | null
}>()

function formatNumber(value: number | null | undefined, unit = '') {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '资料缺失（未知）'
  const numeric = Number(value)
  const digits = Math.abs(numeric) >= 100 ? 0 : Math.abs(numeric) >= 10 ? 1 : 2
  return `${numeric.toFixed(digits)}${unit}`
}

function candidateKindLabel(kind: string) {
  if (kind === 'lumped') return '集总方案'
  if (kind === 'topology_subbasin') return '拓扑子流域'
  if (kind === 'heterogeneity_aware') return '异质性保留'
  return kind
}

const evidenceRows = computed(() => {
  const profile = props.profile
  if (!profile) return []
  const numeric = (
    key: 'elevation' | 'slope' | 'precipitation',
    label: string,
    unit: string,
  ) => {
    const item = profile[key]
    return {
      key,
      label,
      status: item.status,
      summary:
        item.status === 'available'
          ? `均值 ${formatNumber(item.mean, unit)} · 标准差 ${formatNumber(item.std, unit)}`
          : '资料缺失（未知）',
    }
  }
  const categorical = (key: 'land_cover' | 'soil', label: string) => {
    const item = profile[key]
    const entries = Object.entries(item.fractions || {})
      .sort((left, right) => right[1] - left[1])
      .slice(0, 3)
    return {
      key,
      label,
      status: item.status,
      summary:
        item.status === 'available' && entries.length
          ? entries.map(([name, fraction]) => `${name} ${Math.round(fraction * 100)}%`).join(' · ')
          : '资料缺失（未知）',
    }
  }
  const drainage = profile.drainage
  return [
    numeric('elevation', '高程', ' m'),
    numeric('slope', '坡度', '°'),
    numeric('precipitation', '降雨', ' mm'),
    categorical('land_cover', '土地利用'),
    categorical('soil', '土壤'),
    {
      key: 'drainage',
      label: '河网',
      status: drainage.status,
      summary:
        drainage.status === 'available'
          ? `河网密度 ${formatNumber(drainage.stream_density_km_per_km2, ' km/km²')}`
          : '资料缺失（未知）',
    },
  ]
})

const recommendedCandidate = computed(() => {
  if (!props.recommendation) return null
  return (
    props.candidates?.find(
      (candidate) => candidate.candidate_id === props.recommendation?.candidate_id,
    ) || null
  )
})
</script>

<template>
  <section class="spatial-panel" data-test="spatial-review-panel">
    <div class="section">
      <div class="heading">
        <strong>空间异质性证据</strong>
        <span>
          {{
            profileStatus === 'available'
              ? '资料齐全'
              : profileStatus === 'partial'
                ? '部分资料'
                : '资料未知'
          }}
        </span>
      </div>
      <div v-if="evidenceRows.length" class="evidence-grid">
        <article
          v-for="item in evidenceRows"
          :key="item.key"
          class="evidence-item"
          :data-status="item.status"
        >
          <span>{{ item.label }}</span>
          <b>{{ item.status === 'available' ? '已获得' : '资料缺失（未知）' }}</b>
          <small>{{ item.summary }}</small>
        </article>
      </div>
      <p v-else class="empty">空间画像资料缺失（未知）。</p>
    </div>

    <div v-if="candidates?.length" class="section">
      <div class="heading">
        <strong>候选方案</strong>
        <span>只引用确定性 GIS 边界</span>
      </div>
      <div class="candidate-list">
        <article
          v-for="candidate in candidates"
          :key="candidate.candidate_id"
          class="candidate-card"
          :data-recommended="candidate.candidate_id === recommendation?.candidate_id || undefined"
        >
          <div>
            <b>{{ candidateKindLabel(candidate.kind) }}</b>
            <span>{{ candidate.unit_count }} 个单元</span>
          </div>
          <small v-if="candidate.preserved_contrasts?.length">
            保留：{{ candidate.preserved_contrasts.join(' / ') }}
          </small>
          <small v-if="candidate.lost_contrasts?.length">
            损失：{{ candidate.lost_contrasts.join(' / ') }}
          </small>
          <small>证据：{{ candidate.evidence_refs.join(' / ') }}</small>
        </article>
      </div>
    </div>

    <div v-if="recommendation" class="section recommendation">
      <div class="heading">
        <strong>Agent 推荐</strong>
        <span>
          {{ recommendation.source === 'agent' ? 'Agent 选择' : '确定性回退' }}
          · 置信度 {{ Math.round(recommendation.confidence * 100) }}%
        </span>
      </div>
      <p>{{ recommendation.rationale }}</p>
      <p v-if="recommendedCandidate" class="meta">
        推荐候选：{{ candidateKindLabel(recommendedCandidate.kind) }} ·
        {{ recommendedCandidate.unit_count }} 个单元
      </p>
      <p class="meta">evidence_refs：{{ recommendation.evidence_refs.join(' / ') || '无' }}</p>
      <p class="meta">uncertainties：{{ recommendation.uncertainties.join(' / ') || '无' }}</p>
    </div>
  </section>
</template>

<style scoped>
.spatial-panel {
  display: grid;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--separator);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--surface) 94%, var(--background));
}
.section {
  display: grid;
  gap: 10px;
}
.section + .section {
  padding-top: 12px;
  border-top: 1px solid var(--separator);
}
.heading {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: baseline;
}
.heading strong {
  color: var(--text-primary);
  font-size: 14px;
}
.heading span,
.meta,
.empty {
  color: var(--text-tertiary);
  font-size: 12px;
}
.evidence-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.evidence-item,
.candidate-card {
  min-width: 0;
  padding: 10px 11px;
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
  background: var(--surface);
}
.evidence-item {
  display: grid;
  gap: 3px;
}
.evidence-item > span,
.candidate-card span {
  color: var(--text-secondary);
  font-size: 12px;
}
.evidence-item > b {
  color: var(--success);
  font-size: 12px;
}
.evidence-item[data-status='unknown'] > b {
  color: var(--text-tertiary);
}
.evidence-item small,
.candidate-card small {
  color: var(--text-secondary);
  font-size: 11px;
  overflow-wrap: anywhere;
}
.candidate-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}
.candidate-card {
  display: grid;
  gap: 6px;
}
.candidate-card[data-recommended='true'] {
  border-color: color-mix(in srgb, var(--accent) 42%, var(--separator));
  background: var(--accent-soft);
}
.candidate-card > div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.recommendation > p {
  margin: 0;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.55;
}
.recommendation > .meta {
  color: var(--text-secondary);
  font-size: 12px;
}
@media (max-width: 720px) {
  .evidence-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
