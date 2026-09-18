<script setup lang="ts">
import { computed } from 'vue'
import type { ExperienceEntryDetail, ExperienceEvidenceRef } from '../types/api'

const props = defineProps<{ entry?: ExperienceEntryDetail | null }>()

const confidence = computed(() =>
  props.entry ? `${Math.round(props.entry.confidence * 100)}%` : '—',
)
const patternRows = computed(() => Object.entries(props.entry?.pattern || {}))
const decisionRows = computed(() => Object.entries(props.entry?.decision || {}))

function renderValue(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join(' / ')
  if (value && typeof value === 'object') return JSON.stringify(value)
  return String(value ?? '—')
}

function evidenceLabel(ref: ExperienceEvidenceRef) {
  return ref.evidence_id || ref.experiment_id || ref.task_id
}
</script>

<template>
  <section class="experience-detail" aria-label="Experience 详情">
    <template v-if="entry">
      <header>
        <span>EXPERIENCE DETAIL</span>
        <h3>{{ entry.experience_id }}</h3>
        <div class="detail-meta">
          <strong>{{ confidence }}</strong>
          <span>revision {{ entry.revision }}</span>
          <span>{{ entry.status }}</span>
        </div>
      </header>

      <section class="detail-block">
        <h4>适用范围</h4>
        <p>模型：{{ entry.scope.model_ids?.join(' / ') || '通用' }}</p>
        <p>流域：{{ entry.scope.basin_ids?.join(' / ') || '可迁移' }}</p>
      </section>

      <section class="detail-block">
        <h4>触发模式</h4>
        <dl><div v-for="[key, value] in patternRows" :key="key"><dt>{{ key }}</dt><dd>{{ renderValue(value) }}</dd></div></dl>
      </section>

      <section class="detail-block">
        <h4>经验决策</h4>
        <dl><div v-for="[key, value] in decisionRows" :key="key"><dt>{{ key }}</dt><dd>{{ renderValue(value) }}</dd></div></dl>
      </section>

      <section class="detail-block">
        <h4>支持证据 · {{ entry.supporting_evidence.length }}</h4>
        <div class="evidence-links">
          <a
            v-for="ref in entry.supporting_evidence"
            :key="`support-${ref.task_id}-${ref.evidence_id || ref.experiment_id || ''}`"
            :href="`/tasks/${encodeURIComponent(ref.task_id)}`"
          >
            {{ evidenceLabel(ref) }}
            <small>{{ ref.task_id }}</small>
          </a>
          <span v-if="!entry.supporting_evidence.length" class="empty">暂无支持证据</span>
        </div>
      </section>

      <section class="detail-block counter">
        <h4>反例 · {{ entry.contradicting_evidence.length }}</h4>
        <div class="evidence-links">
          <a
            v-for="ref in entry.contradicting_evidence"
            :key="`counter-${ref.task_id}-${ref.evidence_id || ref.experiment_id || ''}`"
            :href="`/tasks/${encodeURIComponent(ref.task_id)}`"
          >
            {{ evidenceLabel(ref) }}
            <small>{{ ref.task_id }}</small>
          </a>
          <span v-if="!entry.contradicting_evidence.length" class="empty">当前没有反例</span>
        </div>
      </section>

      <section v-if="entry.revisions.length > 1" class="detail-block">
        <h4>Revision 历史</h4>
        <div class="revision-strip">
          <span v-for="revision in entry.revisions" :key="revision.revision">
            r{{ revision.revision }} · {{ Math.round(revision.confidence * 100) }}%
          </span>
        </div>
      </section>
    </template>
    <div v-else class="detail-empty">
      <strong>选择一条 Experience</strong>
      <span>查看它由哪些任务和实验形成，以及当前如何影响 Agent。</span>
    </div>
  </section>
</template>

<style scoped>
.experience-detail { display: grid; align-content: start; gap: 11px; min-height: 0; overflow: auto; }
header span { color: var(--text-tertiary); font-size: 10px; font-weight: 800; letter-spacing: .12em; }
header h3 { margin: 3px 0 7px; font-family: var(--mono); font-size: 15px; overflow-wrap: anywhere; }
.detail-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.detail-meta > * { border-radius: 999px; background: var(--surface-secondary); padding: 4px 7px; color: var(--text-secondary); font-size: 9px; }
.detail-meta strong { background: var(--accent-soft); color: var(--accent-text); }
.detail-block { border-top: 1px solid var(--separator); padding-top: 9px; }
.detail-block h4 { margin: 0 0 6px; font-size: 11px; }
.detail-block p { margin: 3px 0; color: var(--text-secondary); font-size: 10px; line-height: 1.45; }
.detail-block dl { display: grid; gap: 5px; margin: 0; }
.detail-block dl div { display: grid; grid-template-columns: minmax(72px,.7fr) minmax(0,1.3fr); gap: 7px; font-size: 10px; }
.detail-block dt { color: var(--text-tertiary); }
.detail-block dd { margin: 0; color: var(--text-primary); overflow-wrap: anywhere; }
.evidence-links { display: grid; gap: 5px; }
.evidence-links a { display: grid; gap: 1px; border: 1px solid var(--separator); border-radius: var(--radius-xs); background: var(--surface-secondary); padding: 6px 7px; color: var(--text-primary); font-family: var(--mono); font-size: 9px; text-decoration: none; }
.evidence-links a:hover { border-color: color-mix(in srgb, var(--accent) 35%, var(--separator)); background: var(--accent-soft); }
.evidence-links small { color: var(--text-tertiary); font-family: inherit; }
.counter .evidence-links a { border-color: color-mix(in srgb, var(--danger) 20%, var(--separator)); }
.revision-strip { display: flex; flex-wrap: wrap; gap: 5px; }
.revision-strip span { border-radius: 999px; background: var(--surface-secondary); padding: 4px 7px; color: var(--text-secondary); font-size: 9px; }
.empty { color: var(--text-tertiary); font-size: 10px; }
.detail-empty { display: grid; place-items: center; align-content: center; min-height: 240px; gap: 4px; color: var(--text-secondary); text-align: center; }
.detail-empty strong { color: var(--text-primary); font-size: 13px; }
.detail-empty span { max-width: 240px; font-size: 10px; line-height: 1.5; }
</style>
