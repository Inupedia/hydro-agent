<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useExperienceStore } from '../stores/experience'
import ExperienceDetail from './ExperienceDetail.vue'
import ExperienceTimeline from './ExperienceTimeline.vue'

const props = withDefaults(
  defineProps<{
    taskId?: string | null
    initialExperienceId?: string | null
  }>(),
  { taskId: null, initialExperienceId: null },
)

const experience = useExperienceStore()

const statusLabel = computed(() => {
  const labels = {
    learning: '学习中',
    converging: '趋于收敛',
    converged: '已收敛',
    reopened: '重新打开',
  }
  const status = experience.summary?.status
  return status ? labels[status] : '尚未形成'
})

const currentVersionLabel = computed(() =>
  experience.summary?.current_version
    ? `Experience Skill v${experience.summary.current_version}`
    : 'Experience Skill 尚未发布',
)

async function selectExperience(experienceId: string) {
  try {
    await experience.loadEntry(experienceId)
  } catch {
    // The store keeps the API error; preserve the previous readable state.
  }
}

async function selectVersion(version: number) {
  try {
    await experience.loadVersionDiff(version)
  } catch {
    // Keep the last successful selection visible.
  }
}

async function refresh() {
  try {
    await experience.refresh()
    const targetId =
      props.initialExperienceId ||
      experience.selectedExperienceId ||
      experience.entries[0]?.experience_id
    if (targetId) await selectExperience(targetId)

    const targetVersion =
      experience.summary?.current_version ??
      experience.selectedVersion ??
      experience.versions.at(-1)?.version
    if (targetVersion != null) await selectVersion(targetVersion)
  } catch {
    // Error state is rendered in the panel.
  }
}

watch(
  () => props.initialExperienceId,
  (experienceId) => {
    if (experienceId) void selectExperience(experienceId)
  },
)

onMounted(() => void refresh())
</script>

<template>
  <section class="experience-evolution-panel" data-test="experience-evolution-panel">
    <header class="evolution-hero">
      <div>
        <span>AGENT EVOLUTION</span>
        <h2>{{ currentVersionLabel }}</h2>
        <p>经验由任务证据累积而来；State 可持续调整，只有结构变化才生成新的 Skill 候选版本。</p>
      </div>
      <div class="convergence-badge" :data-status="experience.summary?.status || 'empty'">
        <small>CONVERGENCE</small>
        <strong>{{ statusLabel }}</strong>
        <span>{{ experience.summary?.reason || '等待更多跨任务经验' }}</span>
      </div>
    </header>

    <p v-if="experience.error" class="evolution-error" role="alert">{{ experience.error }}</p>

    <div class="evolution-stats">
      <article><span>Active Experience</span><strong>{{ experience.summary?.active_count ?? 0 }}</strong></article>
      <article><span>高置信经验</span><strong>{{ experience.summary?.high_confidence_count ?? 0 }}</strong></article>
      <article><span>候选版本</span><strong>{{ experience.summary?.candidate_count ?? 0 }}</strong></article>
      <article><span>历史版本</span><strong>{{ experience.summary?.version_count ?? 0 }}</strong></article>
    </div>

    <div class="evolution-grid">
      <ExperienceTimeline
        :versions="experience.versions"
        :events="experience.timeline"
        :selected-version="experience.selectedVersion"
        :diff="experience.selectedDiff"
        @select-version="selectVersion"
        @select-experience="selectExperience"
      />

      <section class="experience-index" aria-label="Experience 索引">
        <header>
          <span>EXPERIENCE STATE</span>
          <h3>当前经验</h3>
          <small>{{ experience.entries.length }} 条经验记录</small>
        </header>
        <div class="experience-list">
          <button
            v-for="entry in experience.entries"
            :key="entry.experience_id"
            type="button"
            class="experience-row"
            :class="{ active: entry.experience_id === experience.selectedExperienceId }"
            @click="selectExperience(entry.experience_id)"
          >
            <span>
              <strong>{{ entry.experience_id }}</strong>
              <small>{{ entry.scope.model_ids?.join(' / ') || '通用模型' }} · {{ entry.scope.basin_ids?.join(' / ') || '可迁移' }}</small>
            </span>
            <span class="confidence">{{ Math.round(entry.confidence * 100) }}%</span>
          </button>
          <p v-if="!experience.entries.length && !experience.loading" class="empty">还没有可展示的 Experience。</p>
        </div>
      </section>

      <ExperienceDetail :entry="experience.selectedEntry" />
    </div>
  </section>
</template>

<style scoped>
.experience-evolution-panel { display: grid; min-height: 0; grid-template-rows: auto auto minmax(0,1fr); gap: 12px; flex: 1; overflow: hidden; }
.evolution-hero { display: flex; align-items: stretch; justify-content: space-between; gap: 16px; }
.evolution-hero > div:first-child { min-width: 0; }
.evolution-hero > div:first-child > span, .experience-index header > span { color: var(--text-tertiary); font-size: 10px; font-weight: 800; letter-spacing: .12em; }
.evolution-hero h2 { margin: 3px 0 4px; font-size: 19px; }
.evolution-hero p { max-width: 680px; margin: 0; color: var(--text-secondary); font-size: 11px; line-height: 1.55; }
.convergence-badge { display: grid; min-width: 190px; align-content: center; border: 1px solid var(--separator); border-radius: var(--radius-md); background: var(--surface-secondary); padding: 10px 12px; }
.convergence-badge small { color: var(--text-tertiary); font-size: 8px; font-weight: 800; letter-spacing: .1em; }
.convergence-badge strong { margin: 2px 0; color: var(--accent-text); font-size: 15px; }
.convergence-badge span { color: var(--text-secondary); font-size: 9px; line-height: 1.4; }
.evolution-stats { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 7px; }
.evolution-stats article { display: flex; align-items: center; justify-content: space-between; gap: 8px; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface); padding: 8px 10px; }
.evolution-stats span { color: var(--text-secondary); font-size: 9px; }
.evolution-stats strong { font-family: var(--mono); font-size: 15px; }
.evolution-grid { display: grid; min-height: 0; grid-template-columns: minmax(220px,.85fr) minmax(250px,1fr) minmax(260px,1.05fr); gap: 10px; overflow: hidden; }
.evolution-grid > * { min-height: 0; border: 1px solid var(--separator); border-radius: var(--radius-md); background: color-mix(in srgb, var(--surface) 88%, transparent); padding: 12px; }
.experience-index { display: grid; grid-template-rows: auto minmax(0,1fr); gap: 10px; }
.experience-index h3 { margin: 3px 0 1px; font-size: 16px; }
.experience-index header small { color: var(--text-tertiary); font-size: 9px; }
.experience-list { display: grid; align-content: start; gap: 6px; min-height: 0; overflow: auto; }
.experience-row { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 8px; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface); padding: 8px; color: var(--text-primary); text-align: left; cursor: pointer; }
.experience-row.active { border-color: color-mix(in srgb, var(--accent) 38%, var(--separator)); background: var(--accent-soft); }
.experience-row strong, .experience-row small { display: block; }
.experience-row strong { font-family: var(--mono); font-size: 10px; overflow-wrap: anywhere; }
.experience-row small { margin-top: 3px; color: var(--text-tertiary); font-size: 9px; }
.confidence { flex: 0 0 auto; border-radius: 999px; background: var(--surface-secondary); padding: 4px 6px; color: var(--accent-text); font-family: var(--mono); font-size: 10px; font-weight: 800; }
.evolution-error { margin: 0; border-radius: var(--radius-sm); background: var(--danger-soft); padding: 8px 10px; color: var(--danger); font-size: 10px; }
.empty { color: var(--text-tertiary); font-size: 10px; }
@media (max-width: 900px) {
  .evolution-grid { grid-template-columns: 1fr; overflow: auto; }
  .evolution-grid > * { min-height: 260px; }
  .evolution-stats { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .evolution-hero { display: grid; }
  .convergence-badge { min-width: 0; }
}
</style>
