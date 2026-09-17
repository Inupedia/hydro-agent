<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { PhArrowLeft } from '@phosphor-icons/vue'
import GlassDialog from './GlassDialog.vue'
import GlassSelect from './GlassSelect.vue'
import ThemeSelect from './ThemeSelect.vue'
import { api } from '../api/client'
import type { LLMConfigPayload } from '../api/client'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const busy = ref(false)
const error = ref<string | null>(null)
const section = ref<'root' | 'theme' | 'provider'>('root')

const form = reactive({
  providerId: 'custom',
  baseUrl: '',
  model: '',
  apiKey: '',
  timeoutSeconds: 60,
  maxRetries: 4,
})

const providerOptions = [
  { value: 'siliconflow', label: '硅基流动 SiliconFlow' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'qwen', label: '通义千问 DashScope' },
  { value: 'moonshot', label: 'Moonshot Kimi' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'custom', label: '自定义 OpenAI 兼容' },
]

const PRESETS: Record<string, { baseUrl: string; model: string }> = {
  siliconflow: { baseUrl: 'https://api.siliconflow.cn/v1', model: 'zai-org/GLM-5.3' },
  openai: { baseUrl: 'https://api.openai.com/v1', model: 'gpt-4.1-mini' },
  deepseek: { baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat' },
  qwen: { baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  moonshot: { baseUrl: 'https://api.moonshot.cn/v1', model: 'kimi-k2-0905-preview' },
  openrouter: { baseUrl: 'https://openrouter.ai/api/v1', model: 'openai/gpt-4o-mini' },
  custom: { baseUrl: '', model: '' },
}

function applyPreset(providerId: string) {
  const preset = PRESETS[providerId]
  if (!preset) return
  form.baseUrl = preset.baseUrl
  form.model = preset.model
}

function onProviderChange(value: string) {
  form.providerId = value
  applyPreset(value)
}

async function load() {
  error.value = null
  try {
    const data = await api.getLLMSettings()
    form.providerId = data.provider_id
    form.baseUrl = data.base_url
    form.model = data.model
    form.timeoutSeconds = data.timeout_seconds
    form.maxRetries = data.max_retries
    form.apiKey = ''
  } catch (err) {
    error.value = String((err as Error).message || err)
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) void load()
  },
  { immediate: true },
)

function close() {
  section.value = 'root'
  emit('close')
}

async function save() {
  error.value = null
  busy.value = true
  try {
    const payload: LLMConfigPayload = {
      provider_id: form.providerId,
      base_url: form.baseUrl.trim(),
      model: form.model.trim(),
      api_key: form.apiKey,
      timeout_seconds: form.timeoutSeconds,
      max_retries: form.maxRetries,
    }
    await api.saveLLMSettings(payload)
    close()
  } catch (err) {
    error.value = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <GlassDialog
    :open="open"
    :overline="section === 'root' ? '工作台' : undefined"
    :title="section === 'root' ? '配置' : section === 'theme' ? '主题配色' : '服务商配置'"
    labelled-by="llm-config-title"
    test-id="llm-settings"
    @close="close"
  >
    <div v-if="section === 'root'" class="settings-menu">
      <button type="button" class="glass-dialog-item settings-choice" @click="section = 'theme'">
        <span><strong>主题配色</strong><small>自动、浅色或深色</small></span><span aria-hidden="true">›</span>
      </button>
      <button type="button" class="glass-dialog-item settings-choice" @click="section = 'provider'">
        <span><strong>服务商配置</strong><small>模型、接口地址与密钥</small></span><span aria-hidden="true">›</span>
      </button>
    </div>

    <form v-else class="llm-config" @submit.prevent="save">
      <ThemeSelect v-if="section === 'theme'" />

      <label v-if="section === 'provider'" class="llm-field">
        <span>服务商</span>
        <GlassSelect
          :model-value="form.providerId"
          :options="providerOptions"
          aria-label="服务商"
          @update:model-value="onProviderChange"
        />
      </label>

      <label v-if="section === 'provider'" class="llm-field">
        <span>Base URL</span>
        <input
          v-model="form.baseUrl"
          type="url"
          placeholder="https://api.example.com/v1"
          required
          autocomplete="off"
        />
        <small>服务端只接受 HTTPS，本地调试允许 localhost HTTP。</small>
      </label>

      <label v-if="section === 'provider'" class="llm-field">
        <span>模型</span>
        <input
          v-model="form.model"
          type="text"
          placeholder="model-id"
          required
          autocomplete="off"
        />
      </label>

      <label v-if="section === 'provider'" class="llm-field">
        <span>API Key</span>
        <input
          v-model="form.apiKey"
          type="password"
          autocomplete="new-password"
          placeholder="留空则沿用当前密钥"
        />
        <small>密钥不会通过 GET 接口回显。</small>
      </label>

      <div v-if="section === 'provider'" class="llm-grid">
        <label class="llm-field">
          <span>超时（秒）</span>
          <input v-model.number="form.timeoutSeconds" type="number" min="5" max="300" required />
        </label>
        <label class="llm-field">
          <span>重试次数</span>
          <input v-model.number="form.maxRetries" type="number" min="0" max="8" required />
        </label>
      </div>

      <p v-if="section === 'provider' && error" class="llm-error" role="alert">{{ error }}</p>
    </form>

    <template v-if="section === 'provider'" #footer>
      <button v-if="section === 'provider'" type="submit" class="llm-save" :disabled="busy" @click="save">
        {{ busy ? '正在保存…' : '保存配置' }}
      </button>
    </template>
    <template v-if="section !== 'root'" #leading>
      <button type="button" class="glass-dialog-back" aria-label="返回配置" @click="section = 'root'"><PhArrowLeft :size="17" weight="bold" /></button>
    </template>
  </GlassDialog>
</template>

<style scoped>
.llm-config {
  display: grid;
  gap: 12px;
}
.settings-menu {
  display: grid;
  gap: 10px;
}
.settings-choice {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  justify-content: space-between;
  width: 100%;
  min-height: 60px;
  text-decoration: none;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}
.settings-choice strong, .settings-choice small { display: block; }
.settings-choice small { margin-top: 4px; color: var(--text-secondary); font-size: 12px; }
.settings-choice > span:last-child { color: var(--text-secondary); font-size: 24px; }
.llm-config-intro {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.llm-field {
  display: grid;
  gap: 6px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 550;
}
.llm-field small {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
}
.llm-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.llm-error {
  margin: 0;
  color: var(--danger);
  font-size: 12px;
  line-height: 1.5;
}
.llm-cancel,
.llm-save {
  min-height: 40px;
  padding: 0 18px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.llm-cancel {
  border: 1px solid transparent;
  background: var(--button-secondary);
  color: var(--text-primary);
}
.llm-cancel:hover {
  background: var(--button-secondary-hover);
}
.llm-save {
  margin-left: auto;
  border: 0;
  background: var(--primary-button);
  color: var(--primary-button-text);
  box-shadow: var(--glass-inset-soft), var(--shadow);
}
.llm-save:hover:not(:disabled) {
  background: var(--accent-hover);
}
.llm-save:disabled {
  opacity: 0.45;
  cursor: default;
}
@media (max-width: 520px) {
  .llm-grid {
    grid-template-columns: 1fr;
  }
}
</style>
