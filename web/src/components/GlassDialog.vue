<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    overline: string
    title: string
    testId?: string
    labelledBy?: string
    size?: 'default' | 'wide' | 'workbench'
    closeOnBackdrop?: boolean
  }>(),
  { size: 'default', closeOnBackdrop: true },
)

const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null
const stackId = Symbol('glass-dialog')

type OpenEntry = { id: symbol; close: () => void }
const openStack = ((globalThis as { __hydroGlassDialogStack?: OpenEntry[] }).__hydroGlassDialogStack ||=
  [])

const layerIndex = ref(0)
const backdropStyle = computed(() => ({ zIndex: String(50 + layerIndex.value) }))

function close() {
  emit('close')
}

function onBackdrop() {
  if (props.closeOnBackdrop) close()
}

function onKey(event: KeyboardEvent) {
  if (!props.open || event.key !== 'Escape') return
  const top = openStack.at(-1)
  if (top?.id !== stackId) return
  event.preventDefault()
  event.stopPropagation()
  close()
}

function pushStack() {
  const existing = openStack.findIndex((entry) => entry.id === stackId)
  if (existing >= 0) openStack.splice(existing, 1)
  openStack.push({ id: stackId, close })
  layerIndex.value = openStack.length - 1
}

function popStack() {
  const index = openStack.findIndex((entry) => entry.id === stackId)
  if (index >= 0) openStack.splice(index, 1)
  layerIndex.value = 0
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
      document.body.style.overflow = 'hidden'
      pushStack()
      await nextTick()
      const preferred = panel.value?.querySelector<HTMLElement>('[data-autofocus], [autofocus]')
      const focusable =
        preferred ||
        panel.value?.querySelector<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        )
      focusable?.focus()
      return
    }
    popStack()
    if (!openStack.length) document.body.style.overflow = ''
    previousFocus?.focus()
    previousFocus = null
  },
)

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  popStack()
  if (!openStack.length) document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="glass-dialog-backdrop"
      :style="backdropStyle"
      :data-test="testId"
      @click.self="onBackdrop"
    >
      <section
        ref="panel"
        class="glass-dialog-panel glass-pane"
        :class="{
          'has-toolbar': !!$slots.toolbar,
          'size-wide': size === 'wide',
          'size-workbench': size === 'workbench',
        }"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="labelledBy || 'glass-dialog-title'"
      >
        <header class="glass-dialog-head">
          <div>
            <span class="overline">{{ overline }}</span>
            <h2 :id="labelledBy || 'glass-dialog-title'">{{ title }}</h2>
          </div>
          <button type="button" class="glass-dialog-close" aria-label="关闭" @click="close">×</button>
        </header>
        <div v-if="$slots.toolbar" class="glass-dialog-toolbar">
          <slot name="toolbar" />
        </div>
        <div class="glass-dialog-body">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="glass-dialog-footer">
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.glass-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50; /* raised via inline style when nested */
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(26, 28, 34, 0.2);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  overflow-x: clip;
  overscroll-behavior: none;
}
.glass-dialog-panel {
  width: min(520px, 100%);
  max-width: 100%;
  max-height: min(80dvh, 760px);
  padding: 20px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  border-radius: 24px;
  box-shadow: var(--shadow-modal);
  overflow: hidden;
  min-width: 0;
  justify-self: center;
  align-self: center;
}
.glass-dialog-panel.size-wide {
  width: min(720px, 100%);
}
.glass-dialog-panel.size-workbench {
  width: min(1100px, calc(100vw - 32px));
  max-height: min(88dvh, 860px);
}
.glass-dialog-panel.size-workbench .glass-dialog-body {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.glass-dialog-panel.has-toolbar {
  grid-template-rows: auto auto minmax(0, 1fr) auto;
}
.glass-dialog-head,
.glass-dialog-toolbar,
.glass-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.glass-dialog-head > div {
  min-width: 0;
}
.glass-dialog-head h2 {
  margin: 4px 0 0;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.glass-dialog-close {
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 50%;
  background: var(--neutral-soft);
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
}
.glass-dialog-toolbar {
  padding: 12px 0 10px;
  border-bottom: 1px solid var(--separator);
  color: var(--text-secondary);
  font-size: 12px;
}
.glass-dialog-body {
  min-height: 0;
  min-width: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  touch-action: pan-y;
  scrollbar-gutter: stable;
  padding: 10px 2px;
  display: grid;
  align-content: start;
  align-items: stretch;
  gap: 7px;
}
.glass-dialog-body :deep(> p) {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.6;
}
.glass-dialog-footer {
  flex-wrap: wrap;
  padding-top: 12px;
  padding-bottom: env(safe-area-inset-bottom, 0);
  border-top: 1px solid var(--separator);
  color: var(--text-secondary);
  font-size: 12px;
}
.glass-dialog-footer :deep(.start-button),
.glass-dialog-footer :deep(.primary-button),
.glass-dialog-footer :deep(.rename-save) {
  min-height: 40px;
  padding: 8px 16px;
  white-space: normal;
  text-align: center;
}
.glass-dialog-footer:has(> :only-child) :deep(.start-button) {
  width: 100%;
}
:deep(.glass-dialog-item) {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 10px 11px;
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
  background: var(--surface);
}
:deep(.glass-dialog-item input) {
  width: 15px;
  height: 15px;
  margin: 0;
}
:deep(.glass-dialog-item span) {
  display: grid;
  min-width: 0;
  gap: 2px;
}
:deep(.glass-dialog-item strong) {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
:deep(.glass-dialog-item small) {
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
:deep(.glass-dialog-item .text-button) {
  justify-self: end;
  white-space: nowrap;
}
@media (max-height: 640px) {
  .glass-dialog-backdrop {
    padding: 16px;
    align-items: center;
    justify-items: center;
  }
  .glass-dialog-panel {
    max-height: calc(100dvh - 32px);
    height: auto;
    width: min(520px, 100%);
  }
}
@media (prefers-reduced-transparency: reduce) {
  .glass-dialog-backdrop {
    background: rgba(26, 28, 34, 0.32);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}
</style>
