<script setup lang="ts">
import { computed } from 'vue'
import type {
  ExperienceEvolutionEvent,
  ExperienceVersion,
  ExperienceVersionDiff,
} from '../types/api'

const props = defineProps<{
  versions: ExperienceVersion[]
  events: ExperienceEvolutionEvent[]
  selectedVersion?: number | null
  diff?: ExperienceVersionDiff | null
}>()

const emit = defineEmits<{
  'select-version': [version: number]
  'select-experience': [experienceId: string]
}>()

const reversedEvents = computed(() => props.events.slice().reverse())

function versionStatus(status: string) {
  if (status === 'promoted') return '当前生效'
  if (status === 'candidate') return '候选'
  if (status === 'rejected') return '未通过'
  if (status === 'superseded') return '历史版本'
  return status
}

function eventLabel(eventType: string) {
  const labels: Record<string, string> = {
    KEEP: '保持',
    REINFORCE: '强化',
    WEAKEN: '减弱',
    CREATE: '新增',
    MERGE: '合并',
    SPLIT: '拆分',
    SUPERSEDE: '替代',
    REJECT: '拒绝',
  }
  return labels[eventType] || eventType
}
</script>

<template>
  <section class="experience-timeline" aria-label="Experience 演化时间线">
    <header>
      <span>VERSION HISTORY</span>
      <h3>版本变化</h3>
    </header>

    <div v-if="versions.length" class="version-list">
      <button
        v-for="version in versions.slice().reverse()"
        :key="version.version"
        type="button"
        class="version-row"
        :class="{ active: version.version === selectedVersion }"
        @click="emit('select-version', version.version)"
      >
        <span class="version-mark">v{{ version.version }}</span>
        <span>
          <strong>{{ versionStatus(version.status) }}</strong>
          <small>{{ version.skill_hash.slice(0, 10) }}…</small>
        </span>
      </button>
    </div>
    <p v-else class="empty">还没有 Experience Skill 版本。</p>

    <div v-if="diff" class="version-diff" data-test="experience-version-diff">
      <strong>v{{ diff.version }} 结构变化</strong>
      <dl>
        <div><dt>新增</dt><dd>{{ diff.added.length }}</dd></div>
        <div><dt>修改</dt><dd>{{ diff.modified.length }}</dd></div>
        <div><dt>替代</dt><dd>{{ diff.superseded.length }}</dd></div>
        <div><dt>拆分 / 合并</dt><dd>{{ diff.split.length }} / {{ diff.merged.length }}</dd></div>
      </dl>
      <button
        v-for="experienceId in [...diff.added, ...diff.modified, ...diff.superseded]"
        :key="experienceId"
        type="button"
        class="diff-ref"
        @click="emit('select-experience', experienceId)"
      >
        {{ experienceId }}
      </button>
      <div v-if="diff.structural_changes?.length" class="structural-reasons" data-test="structural-reasons">
        <article
          v-for="(change, index) in diff.structural_changes"
          :key="`${change.operation}-${index}`"
          class="structural-reason"
        >
          <span>{{ eventLabel(change.operation) }}</span>
          <div>
            <strong>
              {{ change.experience_id || change.source_ids?.join(' + ') || '新规律' }}
              <template v-if="change.proposal_ids?.length"> → {{ change.proposal_ids.join(' / ') }}</template>
            </strong>
            <p>{{ change.reason }}</p>
          </div>
        </article>
      </div>
    </div>

    <div class="event-list">
      <article v-for="event in reversedEvents.slice(0, 14)" :key="event.event_id" class="event-row">
        <span class="event-type">{{ eventLabel(event.event_type) }}</span>
        <div>
          <button
            v-if="event.experience_id"
            type="button"
            class="event-experience"
            @click="emit('select-experience', event.experience_id)"
          >
            {{ event.experience_id }}
          </button>
          <strong v-else>Experience State</strong>
          <p>{{ event.reason }}</p>
          <small v-if="event.task_id">Task · {{ event.task_id }}</small>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.experience-timeline { display: grid; min-height: 0; grid-template-rows: auto auto auto minmax(0, 1fr); gap: 12px; }
header span { color: var(--text-tertiary); font-size: 10px; font-weight: 800; letter-spacing: .12em; }
header h3 { margin: 3px 0 0; font-size: 16px; }
.version-list { display: grid; gap: 6px; }
.version-row { display: grid; grid-template-columns: auto 1fr; gap: 9px; align-items: center; width: 100%; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface); padding: 8px; color: var(--text-primary); text-align: left; cursor: pointer; }
.version-row.active { border-color: color-mix(in srgb, var(--accent) 38%, var(--separator)); background: var(--accent-soft); }
.version-mark { font-family: var(--mono); font-size: 12px; font-weight: 800; }
.version-row strong, .version-row small { display: block; }
.version-row strong { font-size: 11px; }
.version-row small { margin-top: 2px; color: var(--text-tertiary); font-family: var(--mono); font-size: 9px; }
.version-diff { border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface-secondary); padding: 10px; }
.version-diff > strong { font-size: 11px; }
.version-diff dl { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 5px; margin: 8px 0; }
.version-diff dl div { display: flex; justify-content: space-between; gap: 8px; color: var(--text-secondary); font-size: 10px; }
.version-diff dd { margin: 0; color: var(--text-primary); font-weight: 700; }
.diff-ref, .event-experience { border: 0; background: transparent; padding: 0; color: var(--accent-text); font-family: var(--mono); font-size: 10px; cursor: pointer; }
.diff-ref { margin: 2px 7px 2px 0; }
.structural-reasons { display: grid; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--separator); }
.structural-reason { display: grid; grid-template-columns: 40px 1fr; gap: 7px; }
.structural-reason > span { color: var(--accent-text); font-size: 9px; font-weight: 800; }
.structural-reason strong { display: block; font-family: var(--mono); font-size: 9px; overflow-wrap: anywhere; }
.structural-reason p { margin: 2px 0 0; color: var(--text-secondary); font-size: 9px; line-height: 1.4; }
.event-list { display: grid; align-content: start; gap: 7px; min-height: 0; overflow: auto; }
.event-row { display: grid; grid-template-columns: 44px 1fr; gap: 8px; border-left: 2px solid var(--separator); padding: 3px 0 7px 9px; }
.event-type { color: var(--text-tertiary); font-size: 9px; font-weight: 800; }
.event-row strong { font-size: 10px; }
.event-row p { margin: 3px 0; color: var(--text-secondary); font-size: 10px; line-height: 1.45; }
.event-row small { color: var(--text-tertiary); font-size: 9px; }
.empty { margin: 0; color: var(--text-tertiary); font-size: 11px; }
</style>
