<script setup lang="ts">
import { AUDIENCE_STAGES, type StageStatus } from '../demo/stages'

defineProps<{
  statuses: Record<string, StageStatus>
}>()

const statusLabel: Record<StageStatus, string> = {
  pending: '尚未开始',
  active: '正在执行',
  done: '已完成',
  skipped: '已跳过',
  blocked: '受阻',
}
</script>

<template>
  <nav class="stage-bar" aria-label="演示阶段">
    <ol>
      <li
        v-for="stage in AUDIENCE_STAGES"
        :key="stage.id"
        :data-status="statuses[stage.id] || 'pending'"
      >
        <span class="mark" aria-hidden="true" />
        <span class="copy">
          <strong>{{ stage.label }}</strong>
          <small>{{ statusLabel[(statuses[stage.id] || 'pending') as StageStatus] }}</small>
        </span>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.stage-bar {
  width: 100%;
}
ol {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.35rem;
}
li {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 36px;
  padding: 0.25rem 0.55rem;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.4);
  border: 1px solid transparent;
  color: var(--secondary);
}
.mark {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c7c7cc;
  flex: 0 0 auto;
}
.copy {
  display: grid;
  gap: 0;
  min-width: 0;
}
strong {
  font-size: 12px;
  font-weight: 600;
  color: inherit;
  letter-spacing: -0.01em;
}
small {
  font-size: 10px;
  color: var(--tertiary);
}
li[data-status='active'] {
  background: var(--blue-soft);
  color: var(--blue);
  border-color: rgba(0, 122, 255, 0.18);
}
li[data-status='active'] .mark {
  background: var(--blue);
  box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.16);
}
li[data-status='done'] {
  color: var(--label);
}
li[data-status='done'] .mark {
  background: var(--success);
}
li[data-status='skipped'] {
  opacity: 0.55;
  color: var(--tertiary);
}
li[data-status='skipped'] .mark {
  background: #d1d1d6;
  box-shadow: none;
}
li[data-status='blocked'] {
  background: var(--danger-soft);
  color: var(--danger);
}
li[data-status='blocked'] .mark {
  background: var(--danger);
}
@media (max-width: 960px) {
  ol {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
