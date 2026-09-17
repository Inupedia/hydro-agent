<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useAttrs, watch } from 'vue'
import { PhCaretDown, PhCheck } from '@phosphor-icons/vue'

defineOptions({ inheritAttrs: false })

export type GlassSelectOption = {
  value: string
  label: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    options: GlassSelectOption[]
    disabled?: boolean
    ariaLabel?: string
    placeholder?: string
    compact?: boolean
  }>(),
  { disabled: false, compact: false },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const attrs = useAttrs()
const instanceId = `glass-select-${Math.random().toString(36).slice(2, 8)}`

const open = ref(false)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLUListElement | null>(null)
const activeIndex = ref(-1)
const menuStyle = ref<Record<string, string>>({})

const selected = computed(
  () => props.options.find((option) => option.value === props.modelValue) || null,
)
const label = computed(() => selected.value?.label || props.placeholder || '请选择')
const enabledIndexes = computed(() =>
  props.options.map((option, index) => (option.disabled ? -1 : index)).filter((index) => index >= 0),
)

function optionId(index: number) {
  return `${instanceId}-option-${index}`
}

function close() {
  open.value = false
  activeIndex.value = -1
}

function placeMenu() {
  const el = trigger.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const viewportPad = 12
  const maxHeight = Math.min(280, window.innerHeight - viewportPad * 2)
  const spaceBelow = window.innerHeight - rect.bottom - viewportPad
  const spaceAbove = rect.top - viewportPad
  const openUp = spaceBelow < 160 && spaceAbove > spaceBelow
  const height = Math.max(96, openUp ? Math.min(maxHeight, spaceAbove - 6) : Math.min(maxHeight, spaceBelow - 6))
  const width = Math.max(rect.width, 168)
  let left = rect.left
  if (left + width > window.innerWidth - viewportPad) {
    left = Math.max(viewportPad, window.innerWidth - width - viewportPad)
  }
  menuStyle.value = {
    position: 'fixed',
    left: `${left}px`,
    width: `${width}px`,
    maxHeight: `${height}px`,
    zIndex: '1000',
    ...(openUp
      ? { bottom: `${window.innerHeight - rect.top + 6}px`, top: 'auto' }
      : { top: `${rect.bottom + 6}px`, bottom: 'auto' }),
  }
}

async function toggle() {
  if (props.disabled) return
  if (open.value) {
    close()
    return
  }
  open.value = true
  const current = props.options.findIndex((option) => option.value === props.modelValue && !option.disabled)
  activeIndex.value = current >= 0 ? current : enabledIndexes.value[0] ?? -1
  await nextTick()
  placeMenu()
  menu.value?.focus()
}

function choose(option: GlassSelectOption) {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  close()
  trigger.value?.focus()
}

function move(delta: number) {
  const indexes = enabledIndexes.value
  if (!indexes.length) return
  const position = indexes.indexOf(activeIndex.value)
  const next = indexes[(position + delta + indexes.length * 8) % indexes.length]
  activeIndex.value = next
  document.getElementById(optionId(next))?.scrollIntoView({ block: 'nearest' })
}

function onTriggerKey(event: KeyboardEvent) {
  if (props.disabled) return
  if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (!open.value) void toggle()
    else if (event.key === 'Enter' || event.key === ' ') {
      const option = props.options[activeIndex.value]
      if (option) choose(option)
    } else move(1)
  }
}

function onMenuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    trigger.value?.focus()
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    move(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    move(-1)
  } else if (event.key === 'Home') {
    event.preventDefault()
    activeIndex.value = enabledIndexes.value[0] ?? -1
  } else if (event.key === 'End') {
    event.preventDefault()
    activeIndex.value = enabledIndexes.value.at(-1) ?? -1
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    const option = props.options[activeIndex.value]
    if (option) choose(option)
  }
}

function onPointerDown(event: PointerEvent) {
  const target = event.target as Node | null
  if (trigger.value?.contains(target) || menu.value?.contains(target)) return
  close()
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  window.addEventListener('resize', placeMenu)
  window.addEventListener('scroll', placeMenu, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  window.removeEventListener('resize', placeMenu)
  window.removeEventListener('scroll', placeMenu, true)
})
watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) close()
  },
)
</script>

<template>
  <div class="glass-select" :class="{ 'is-open': open, 'is-compact': compact, 'is-disabled': disabled }">
    <button
      ref="trigger"
      type="button"
      class="glass-select-trigger"
      v-bind="attrs"
      :disabled="disabled"
      :aria-label="ariaLabel || undefined"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-controls="open ? `${instanceId}-menu` : undefined"
      @click="toggle"
      @keydown="onTriggerKey"
    >
      <span class="glass-select-label">{{ label }}</span>
      <PhCaretDown :size="14" weight="bold" class="glass-select-caret" aria-hidden="true" />
    </button>
    <Teleport to="body">
      <ul
        v-if="open"
        :id="`${instanceId}-menu`"
        ref="menu"
        class="glass-select-menu"
        role="listbox"
        tabindex="-1"
        :aria-label="ariaLabel"
        :aria-activedescendant="activeIndex >= 0 ? optionId(activeIndex) : undefined"
        :style="menuStyle"
        @keydown="onMenuKey"
      >
        <li
          v-for="(option, index) in options"
          :id="optionId(index)"
          :key="`${option.value}-${index}`"
          role="option"
          class="glass-select-option"
          :class="{
            'is-selected': option.value === modelValue,
            'is-active': index === activeIndex,
            'is-disabled': option.disabled,
          }"
          :aria-selected="option.value === modelValue"
          :aria-disabled="option.disabled || undefined"
          :data-value="option.value"
          @pointerenter="option.disabled ? undefined : (activeIndex = index)"
          @click="choose(option)"
        >
          <span class="glass-select-option-copy">{{ option.label }}</span>
          <PhCheck
            v-if="option.value === modelValue"
            :size="15"
            weight="bold"
            class="glass-select-option-check"
            aria-hidden="true"
          />
        </li>
      </ul>
    </Teleport>
  </div>
</template>

<style scoped>
.glass-select {
  display: block;
  position: relative;
  width: 100%;
  min-width: 0;
}
.glass-select-trigger {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
  min-height: var(--control-h);
  padding: 0 36px 0 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--glass-strong);
  color: var(--text-primary);
  box-shadow: var(--glass-inset);
  backdrop-filter: blur(32px) saturate(140%);
  -webkit-backdrop-filter: blur(32px) saturate(140%);
  font: inherit;
  font-size: 14px;
  text-align: left;
  cursor: pointer;
}
.is-compact .glass-select-trigger {
  min-height: 36px;
  padding: 0 32px 0 12px;
  font-size: 13px;
}
.glass-select-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.glass-select-caret {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
  flex-shrink: 0;
  pointer-events: none;
}
.glass-select-trigger:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}
.is-open .glass-select-trigger,
.glass-select-trigger:focus-visible {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 2px var(--focus-ring), var(--glass-inset);
}
.glass-select-trigger:disabled {
  opacity: 0.45;
  cursor: default;
}
.glass-select-menu {
  margin: 0;
  padding: 6px;
  overflow: auto;
  list-style: none;
  background: var(--glass-strong);
  border: 1px solid var(--glass-edge);
  border-radius: var(--radius-md);
  box-shadow: var(--glass-inset), var(--shadow-modal);
  backdrop-filter: blur(32px) saturate(140%);
  -webkit-backdrop-filter: blur(32px) saturate(140%);
  outline: none;
}
.glass-select-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 40px;
  padding: 8px 12px;
  border-radius: var(--radius-xs);
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.4;
  cursor: pointer;
}
.glass-select-option-copy {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.glass-select-option-check {
  flex-shrink: 0;
  color: var(--accent-text);
}
.glass-select-option.is-active,
.glass-select-option:hover:not(.is-disabled) {
  background: var(--accent-soft);
}
.glass-select-option.is-selected {
  color: var(--accent-text);
  font-weight: 600;
}
.glass-select-option.is-disabled {
  color: var(--text-tertiary);
  cursor: default;
}
@media (prefers-reduced-transparency: reduce) {
  .glass-select-trigger,
  .glass-select-menu {
    background: var(--surface);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}
</style>
