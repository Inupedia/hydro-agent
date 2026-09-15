<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import GlassDialog from './GlassDialog.vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    overline?: string
    title?: string
    hint?: string
    placeholder?: string
    initialName?: string | null
    busy?: boolean
    testId?: string
  }>(),
  {
    overline: '自定义命名',
    title: '重命名',
    hint: '留空则恢复为系统编号。',
    placeholder: '输入显示名称',
    initialName: '',
    busy: false,
    testId: 'rename-dialog',
  },
)

const emit = defineEmits<{
  close: []
  save: [name: string | null]
}>()

const draft = ref('')
const input = ref<HTMLInputElement | null>(null)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    draft.value = props.initialName?.trim() || ''
    await nextTick()
    input.value?.focus()
    input.value?.select()
  },
)

function close() {
  if (props.busy) return
  emit('close')
}

function save() {
  if (props.busy) return
  const next = draft.value.trim()
  emit('save', next || null)
}

function onSubmit(event: Event) {
  event.preventDefault()
  save()
}
</script>

<template>
  <GlassDialog
    :open="open"
    :overline="overline"
    :title="title"
    :test-id="testId"
    labelled-by="rename-dialog-title"
    :close-on-backdrop="!busy"
    @close="close"
  >
    <form class="rename-form" @submit="onSubmit">
      <label class="rename-field">
        <span>显示名称</span>
        <input
          ref="input"
          v-model="draft"
          data-autofocus
          type="text"
          maxlength="80"
          :placeholder="placeholder"
          :disabled="busy"
          autocomplete="off"
        />
      </label>
      <p class="rename-hint">{{ hint }}</p>
    </form>
    <template #footer>
      <button type="button" class="text-button" :disabled="busy" @click="close">取消</button>
      <button type="button" class="primary-button rename-save" :disabled="busy" @click="save">
        {{ busy ? '保存中…' : '保存' }}
      </button>
    </template>
  </GlassDialog>
</template>

<style scoped>
.rename-form {
  display: grid;
  gap: 10px;
}
.rename-field {
  display: grid;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
.rename-field input {
  min-height: 42px;
  width: 100%;
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-primary);
  padding: 0 12px;
  font: inherit;
  font-size: 14px;
  font-weight: 400;
}
.rename-field input:disabled {
  opacity: 0.6;
}
.rename-hint {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}
.rename-save {
  min-height: 40px;
  padding: 8px 16px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--primary-button);
  color: var(--primary-button-text);
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
}
.rename-save:hover:not(:disabled) {
  background: var(--accent-hover);
}
.rename-save:disabled {
  opacity: 0.45;
  cursor: default;
}
.text-button {
  border: 0;
  background: none;
  color: var(--accent-text);
  padding: 0;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}
.text-button:disabled {
  opacity: 0.45;
  cursor: default;
}
</style>
