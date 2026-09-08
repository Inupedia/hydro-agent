<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ModeBadge from '../components/ModeBadge.vue'
import StageBar from '../components/StageBar.vue'
import SettingsSheet from '../components/SettingsSheet.vue'
import { useDemoStore } from '../stores/demo'
import { stageStatuses } from '../demo/stages'

const props = defineProps<{
  showStages?: boolean
  taskSummary?: string
}>()

const demo = useDemoStore()
const route = useRoute()
const router = useRouter()
const now = ref(Date.now())
let tick: number | null = null

onMounted(() => {
  tick = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
})
onUnmounted(() => {
  if (tick != null) clearInterval(tick)
})

const elapsed = computed(() => {
  if (!demo.startedAt) return null
  const seconds = Math.max(0, Math.floor((now.value - demo.startedAt) / 1000))
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
})

const statuses = computed(() =>
  stageStatuses(
    demo.timeline.map((t) => t.action || '').filter(Boolean),
    demo.run?.last_action || demo.timeline.at(-1)?.action || null,
    demo.run?.status || null,
  ),
)

function exitDemo() {
  demo.resetSession()
  void router.push({ name: 'prepare' })
}
</script>

<template>
  <div class="demo-shell">
    <header class="top-bar glass">
      <RouterLink class="brand" :to="{ name: 'prepare' }">Hydro-Agent</RouterLink>
      <p class="summary">{{ taskSummary || '演示工作台' }}</p>
      <div class="top-actions">
        <ModeBadge :mode="demo.mode" />
        <button
          v-if="route.name !== 'prepare'"
          type="button"
          class="ghost"
          @click="demo.openSettings()"
        >
          设置
        </button>
        <button
          v-if="route.name !== 'prepare'"
          type="button"
          class="ghost"
          @click="exitDemo"
        >
          退出演示
        </button>
      </div>
    </header>

    <main class="content">
      <slot />
    </main>

    <footer v-if="showStages" class="bottom-bar glass">
      <StageBar :statuses="statuses" />
      <div class="footer-meta">
        <span v-if="elapsed">已运行 {{ elapsed }}</span>
        <span v-else-if="demo.mode === 'replay'">案例回放</span>
        <span v-else />
        <span v-if="!demo.followScreen">画面跟随已暂停</span>
        <div class="footer-actions">
          <button
            v-if="demo.followScreen"
            type="button"
            class="ghost"
            @click="demo.pauseFollow()"
          >
            暂停画面跟随
          </button>
          <button v-else type="button" class="ghost" @click="demo.resumeFollow()">
            恢复画面跟随
          </button>
        </div>
      </div>
    </footer>

    <SettingsSheet />
  </div>
</template>

<style scoped>
.demo-shell {
  min-height: 100dvh;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
}
.glass {
  background: var(--glass-strong);
  backdrop-filter: saturate(180%) blur(22px);
  -webkit-backdrop-filter: saturate(180%) blur(22px);
  border-color: rgba(255, 255, 255, 0.55);
}
.top-bar {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.75rem;
  min-height: 48px;
  padding: 0.4rem 1rem;
  border-bottom: 1px solid var(--separator);
  position: sticky;
  top: 0;
  z-index: 20;
}
.brand {
  color: var(--label);
  text-decoration: none;
  font-weight: 650;
  font-size: 14px;
  letter-spacing: -0.02em;
}
.summary {
  margin: 0;
  text-align: center;
  color: var(--secondary);
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.top-actions,
.footer-actions {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  justify-content: flex-end;
}
.content {
  min-height: 0;
  padding: 1rem 1.25rem 1rem;
}
.bottom-bar {
  display: grid;
  gap: 0.45rem;
  padding: 0.55rem 0.9rem 0.7rem;
  border-top: 1px solid var(--separator);
}
.footer-meta {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
  color: var(--secondary);
  font-size: 12px;
  flex-wrap: wrap;
}
.ghost {
  appearance: none;
  border: 0;
  height: 28px;
  min-height: 28px;
  padding: 0 0.65rem;
  border-radius: 6px;
  background: rgba(120, 120, 128, 0.1);
  color: var(--label);
  cursor: pointer;
  font-weight: 550;
  font-size: 12px;
}
.ghost:hover {
  background: rgba(120, 120, 128, 0.16);
}
@media (max-width: 800px) {
  .top-bar {
    grid-template-columns: 1fr auto;
  }
  .summary {
    display: none;
  }
}
</style>
