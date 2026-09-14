<script setup lang="ts">
import { computed, ref } from 'vue'
import GlassSelect from './GlassSelect.vue'
import ModelPreparation from './ModelPreparation.vue'
import RippleButton from './ui/RippleButton.vue'
import type { BasinInfo, ModelPlan } from '../types/api'
import { DEMO_PRESET } from '../demo/preset'
import { prefersReducedMotion } from '../motion/gsap'

const props = defineProps<{
  basinId: string
  basinOptions: { value: string; label: string; disabled?: boolean }[]
  selectedBasin?: BasinInfo | null
  modelPlanId?: string | null
  planReady: boolean
  serviceMode: string | null
  locked: boolean
  busy: boolean
  connected: boolean
  modelingAvailable: boolean
  startDate: string
  endDate: string
  planDateMin?: string
  planDateMax?: string
  modelId: string
  forcingMode: string
  allowOptimization: boolean
  baseSchemeId: string
  validationDays: number
  finalTestDays: number
  maxAgentDecisionRounds: number
  maxOptimizationCycles: number
  campaignMode: string
  campaignBudget: number
  modelSelectOptions: { value: string; label: string; disabled?: boolean }[]
  forcingSelectOptions: { value: string; label: string; disabled?: boolean }[]
  campaignSelectOptions: { value: string; label: string; disabled?: boolean }[]
  caseSelectOptions: { value: string; label: string; disabled?: boolean }[]
  selectedCaseId: string
  demoPresetLoaded: boolean
  caseLibraryEmpty: boolean
  caseBusy: boolean
}>()

const emit = defineEmits<{
  'update:basinId': [string]
  'update:startDate': [string]
  'update:endDate': [string]
  'update:modelId': [string]
  'update:forcingMode': [string]
  'update:allowOptimization': [boolean]
  'update:baseSchemeId': [string]
  'update:validationDays': [number]
  'update:finalTestDays': [number]
  'update:maxAgentDecisionRounds': [number]
  'update:maxOptimizationCycles': [number]
  'update:campaignMode': [string]
  'update:campaignBudget': [number]
  'update:selectedCaseId': [string]
  selected: [ModelPlan | null]
  start: []
  applyDemoPreset: []
  openCaseManager: []
}>()

const STEPS = [
  { id: 'basin', overline: '研究流域', title: '选择研究流域', blurb: '先选定本地资料完整的流域，再进入建模。' },
  { id: 'model', overline: '模型方案', title: '建立并复核计算单元', blurb: '核对资料、划分单元，复核边界后绑定方案。' },
  { id: 'runtime', overline: '计算设定', title: '设定时段与模型', blurb: '选定计算窗口、模型与气象资料。' },
  { id: 'confirm', overline: '确认启动', title: '核对参数并开始', blurb: '确认全部设定后启动一次完整运行。' },
] as const

const step = ref(0)
const advanced = ref(false)
const touchStartX = ref<number | null>(null)

const current = computed(() => STEPS[step.value])
const canPrev = computed(() => step.value > 0)
const canNext = computed(() => step.value < STEPS.length - 1)

const nextBlockedReason = computed(() => {
  if (step.value === 0 && !props.basinId) return '请先选择研究流域'
  if (step.value === 1 && props.serviceMode === 'real' && !props.planReady) return '请先完成建模并复核边界'
  if (step.value === 2) {
    if (!props.startDate || !props.endDate) return '请填写起止日期'
    if (props.serviceMode === 'real' && !props.planReady) return '请先完成建模'
  }
  return ''
})

const canAdvance = computed(() => !nextBlockedReason.value)
const startDisabled = computed(
  () => props.busy || !props.connected || (props.serviceMode === 'real' && !props.modelPlanId),
)
const startLabel = computed(() => {
  if (props.busy) return '正在启动…'
  if (props.planReady) return '开始运行'
  return '请先完成建模'
})

const summaryRows = computed(() => [
  { label: '研究流域', value: props.selectedBasin?.label || props.basinId || '—' },
  { label: '模型方案', value: props.modelPlanId || (props.serviceMode === 'real' ? '尚未绑定' : '演示模式可直接启动') },
  { label: '计算时段', value: props.startDate && props.endDate ? `${props.startDate} → ${props.endDate}` : '—' },
  { label: '计算模型', value: props.modelSelectOptions.find((o) => o.value === props.modelId)?.label || props.modelId },
  { label: '气象资料', value: props.forcingSelectOptions.find((o) => o.value === props.forcingMode)?.label || props.forcingMode },
  { label: '改进方案', value: props.allowOptimization ? '允许尝试' : '不自动改进' },
])

function go(index: number) {
  if (index < 0 || index >= STEPS.length) return
  if (index > step.value) {
    for (let i = step.value; i < index; i += 1) {
      const blocked = blockReasonFor(i)
      if (blocked) return
    }
  }
  step.value = index
}

function blockReasonFor(at: number) {
  if (at === 0 && !props.basinId) return '请先选择研究流域'
  if (at === 1 && props.serviceMode === 'real' && !props.planReady) return '请先完成建模并复核边界'
  if (at === 2) {
    if (!props.startDate || !props.endDate) return '请填写起止日期'
    if (props.serviceMode === 'real' && !props.planReady) return '请先完成建模'
  }
  return ''
}

function prev() {
  if (canPrev.value) step.value -= 1
}

function next() {
  if (!canAdvance.value || !canNext.value) return
  step.value += 1
}

function onTouchStart(event: TouchEvent) {
  touchStartX.value = event.changedTouches[0]?.clientX ?? null
}

function onTouchEnd(event: TouchEvent) {
  const start = touchStartX.value
  touchStartX.value = null
  if (start == null || prefersReducedMotion()) return
  const end = event.changedTouches[0]?.clientX ?? start
  const delta = end - start
  if (Math.abs(delta) < 56) return
  if (delta < 0) next()
  else prev()
}

function onSubmit() {
  if (step.value !== STEPS.length - 1) {
    next()
    return
  }
  if (!startDisabled.value) emit('start')
}
</script>

<template>
  <form class="setup-wizard" data-test="setup-wizard" @submit.prevent="onSubmit">
    <header class="setup-head">
      <span class="overline">{{ current.overline }}</span>
      <h2>{{ current.title }}</h2>
      <p class="muted">{{ current.blurb }}</p>
    </header>

    <div
      class="setup-viewport"
      data-test="setup-viewport"
      @touchstart.passive="onTouchStart"
      @touchend.passive="onTouchEnd"
    >
      <div
        class="setup-track"
        :class="{ 'is-instant': prefersReducedMotion() }"
        :style="{ transform: `translateX(-${step * 100}%)` }"
      >
        <!-- 01 研究流域 -->
        <section class="setup-page" data-test="setup-page-basin" :aria-hidden="step !== 0">
          <label class="field">
            <span class="field-label">研究流域</span>
            <GlassSelect
              :model-value="basinId"
              data-test="basin-selector"
              aria-label="研究流域"
              :disabled="busy || locked"
              :options="basinOptions"
              @update:model-value="emit('update:basinId', $event)"
            />
          </label>
          <div v-if="selectedBasin" class="basin-card" data-test="basin-card">
            <strong>{{ selectedBasin.label }}</strong>
            <span class="basin-id">{{ selectedBasin.basin_id }}</span>
            <p class="basin-caption">
              {{ selectedBasin.ready_for_build === false ? '本地资料尚不完整，暂不可建模。' : '本地资料可用于建模。下一步将建立计算单元并复核边界。' }}
            </p>
          </div>
          <p v-else class="basin-caption">从列表中选择一个研究流域以继续。</p>
        </section>

        <!-- 02 模型方案 -->
        <section class="setup-page" data-test="setup-page-model" :aria-hidden="step !== 1">
          <ModelPreparation
            v-if="modelingAvailable"
            embedded
            :basin-id="basinId"
            :selected-id="modelPlanId"
            :locked="locked || busy"
            @selected="emit('selected', $event)"
          />
          <div v-else class="prep-placeholder">
            <span class="overline">数据准备</span>
            <h3>等待建模服务</h3>
            <p>建模服务就绪后，将在此完成资料检查、单元划分与边界复核。</p>
          </div>
        </section>

        <!-- 03 计算设定 -->
        <section class="setup-page" data-test="setup-page-runtime" :aria-hidden="step !== 2">
          <fieldset :disabled="locked || (serviceMode === 'real' && !planReady)" :class="{ 'is-locked': serviceMode === 'real' && !planReady }">
            <p v-if="serviceMode === 'real' && !planReady" class="basin-caption">请先在上一步完成建模并绑定方案。</p>
            <div class="date-fields">
              <label class="field">开始日期
                <input
                  :value="startDate"
                  data-test="start-date"
                  type="date"
                  :min="planDateMin"
                  :max="planDateMax"
                  required
                  @input="emit('update:startDate', ($event.target as HTMLInputElement).value)"
                />
              </label>
              <label class="field">结束日期
                <input
                  :value="endDate"
                  data-test="end-date"
                  type="date"
                  :min="startDate"
                  :max="planDateMax"
                  required
                  @input="emit('update:endDate', ($event.target as HTMLInputElement).value)"
                />
              </label>
            </div>
            <label class="field">计算模型
              <GlassSelect
                :model-value="modelId"
                aria-label="计算模型"
                :options="modelSelectOptions"
                @update:model-value="emit('update:modelId', $event)"
              />
            </label>
            <label class="field">气象资料
              <GlassSelect
                :model-value="forcingMode"
                aria-label="气象资料"
                :options="forcingSelectOptions"
                @update:model-value="emit('update:forcingMode', $event)"
              />
            </label>
            <label class="toggle-row">
              <span>允许尝试改进方案</span>
              <input
                :checked="allowOptimization"
                type="checkbox"
                role="switch"
                @change="emit('update:allowOptimization', ($event.target as HTMLInputElement).checked)"
              />
            </label>
            <button class="text-button" data-test="runtime-settings" type="button" :aria-expanded="advanced" @click="advanced = !advanced">
              {{ advanced ? '收起运行设置 −' : '运行设置 +' }}
            </button>
            <div v-if="advanced" class="advanced-fields">
              <label class="field">基础方案
                <input :value="baseSchemeId" required @input="emit('update:baseSchemeId', ($event.target as HTMLInputElement).value)" />
              </label>
              <label class="field">开发验证窗（天）
                <input
                  :value="validationDays"
                  data-test="development-days"
                  type="number"
                  min="3"
                  max="90"
                  required
                  @input="emit('update:validationDays', Number(($event.target as HTMLInputElement).value))"
                />
                <small>候选方案在此做 Gate；最终测试不会参与选择。</small>
              </label>
              <label class="field">最终测试窗（天）
                <input
                  :value="finalTestDays"
                  data-test="final-test-days"
                  type="number"
                  min="3"
                  max="90"
                  required
                  @input="emit('update:finalTestDays', Number(($event.target as HTMLInputElement).value))"
                />
                <small>方案冻结后只读、单次消费。</small>
              </label>
              <label class="field">最多决策轮次
                <input
                  :value="maxAgentDecisionRounds"
                  type="number"
                  min="1"
                  max="100"
                  required
                  @input="emit('update:maxAgentDecisionRounds', Number(($event.target as HTMLInputElement).value))"
                />
              </label>
              <label class="field">最多改进次数
                <input
                  :value="maxOptimizationCycles"
                  type="number"
                  min="0"
                  max="4"
                  required
                  @input="emit('update:maxOptimizationCycles', Number(($event.target as HTMLInputElement).value))"
                />
              </label>
              <label class="field">停止策略
                <GlassSelect
                  :model-value="campaignMode"
                  data-test="campaign-mode"
                  aria-label="停止策略"
                  :options="campaignSelectOptions"
                  @update:model-value="emit('update:campaignMode', $event)"
                />
                <small>连通验证只按模型评估预算停止，不宣称收敛或发布合格。</small>
              </label>
              <label class="field">模型评估预算
                <input
                  :value="campaignBudget"
                  data-test="campaign-budget"
                  type="number"
                  min="1"
                  required
                  @input="emit('update:campaignBudget', Number(($event.target as HTMLInputElement).value))"
                />
                <small>实验之间的停止阈值，不会中途截断单次优化器。</small>
              </label>
            </div>
          </fieldset>
        </section>

        <!-- 04 确认启动 -->
        <section class="setup-page" data-test="setup-page-confirm" :aria-hidden="step !== 3">
          <div class="confirm-card">
            <div class="section-heading">
              <span class="overline">参数摘要</span>
              <button
                v-if="basinId === 'yaogu'"
                class="text-button"
                data-test="demo-preset"
                type="button"
                @click="emit('applyDemoPreset')"
              >
                {{ demoPresetLoaded ? '重新载入演示默认值' : '载入演示默认值' }}
              </button>
            </div>
            <p v-if="basinId === 'yaogu'" class="basin-caption">
              演示窗口 {{ DEMO_PRESET.start_date }} 至 {{ DEMO_PRESET.end_date }}，按开发期筛选，不代表正式研究结论。复现请使用 365 天预热、单元集总方案。
            </p>
            <dl class="summary-list">
              <div v-for="row in summaryRows" :key="row.label" class="summary-row">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>
            <p class="source-note">
              {{
                forcingMode === 'R'
                  ? `使用 ${selectedBasin?.label || basinId} 本地日资料做历史率定与检验，不代表业务预报。`
                  : '预报资料可用性将在运行时检查。'
              }}
            </p>
          </div>
          <div class="case-picker-row">
            <label class="case-picker">已有案例
              <GlassSelect
                :model-value="selectedCaseId"
                aria-label="已有案例"
                :disabled="caseBusy"
                :options="caseSelectOptions"
                @update:model-value="emit('update:selectedCaseId', $event)"
              />
            </label>
            <button
              data-test="delete-case"
              type="button"
              class="manage-button"
              :disabled="caseBusy || caseLibraryEmpty"
              @click="emit('openCaseManager')"
            >
              管理
            </button>
          </div>
        </section>
      </div>
    </div>

    <footer class="setup-footer">
      <div class="setup-dots" role="tablist" aria-label="准备步骤">
        <button
          v-for="(item, index) in STEPS"
          :key="item.id"
          type="button"
          class="setup-dot"
          :class="{ active: index === step, done: index < step }"
          :aria-label="item.title"
          :aria-current="index === step ? 'step' : undefined"
          data-test="setup-dot"
          @click="go(index)"
        />
      </div>
      <div class="setup-nav">
        <button type="button" class="ghost-button" data-test="setup-prev" :disabled="!canPrev" @click="prev">上一步</button>
        <p v-if="step < STEPS.length - 1 && nextBlockedReason" class="nav-hint">{{ nextBlockedReason }}</p>
        <RippleButton
          v-if="step < STEPS.length - 1"
          type="button"
          class="start-button"
          data-test="setup-next"
          :disabled="!canAdvance"
          @click="next"
        >
          下一步
        </RippleButton>
        <RippleButton
          v-else
          class="start-button"
          data-test="setup-start"
          :disabled="startDisabled"
          type="submit"
        >
          {{ startLabel }}
        </RippleButton>
      </div>
    </footer>
  </form>
</template>

<style scoped>
.setup-wizard {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 0;
}

.setup-head {
  flex: 0 0 auto;
  margin-bottom: 16px;
}

.setup-head h2 {
  margin: 6px 0 8px;
  font-size: clamp(22px, 2.2vw, 28px);
  font-weight: 600;
  line-height: 1.25;
  letter-spacing: -0.02em;
}

.setup-head .muted {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.55;
  max-width: 52ch;
}

.setup-viewport {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

.setup-track {
  display: flex;
  height: 100%;
  width: 100%;
  transition: transform 280ms cubic-bezier(0.2, 0.8, 0.2, 1);
  will-change: transform;
}

.setup-track.is-instant {
  transition: none;
}

.setup-page {
  flex: 0 0 100%;
  width: 100%;
  min-width: 0;
  height: 100%;
  overflow: auto;
  padding-right: 4px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  scrollbar-width: thin;
  scrollbar-color: rgba(90, 105, 125, 0.28) transparent;
}

.setup-page::-webkit-scrollbar {
  width: 10px;
}
.setup-page::-webkit-scrollbar-track {
  background: transparent;
}
.setup-page::-webkit-scrollbar-thumb {
  background: rgba(90, 105, 125, 0.28);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: content-box;
}

.field,
.field-label {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.basin-card,
.confirm-card {
  background: var(--surface, #fff);
  border: 1px solid var(--separator);
  border-radius: 16px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.basin-card strong {
  font-size: 17px;
  font-weight: 600;
}

.basin-id {
  color: var(--text-tertiary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.summary-list {
  margin: 8px 0 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.summary-row {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 12px;
  align-items: baseline;
}

.summary-row dt {
  color: var(--text-tertiary);
  font-size: 12px;
}

.summary-row dd {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
  overflow-wrap: anywhere;
}

.setup-footer {
  flex: 0 0 auto;
  margin-top: 16px;
  padding: 14px 0 calc(10px + env(safe-area-inset-bottom, 0));
  border-top: 1px solid var(--separator);
  display: flex;
  flex-direction: column;
  gap: 14px;
  background:
    linear-gradient(180deg, rgba(250, 251, 253, 0.42), rgba(250, 251, 253, 0.82));
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
}

.setup-page[data-test='setup-page-model'] {
  overflow: hidden;
  padding-right: 0;
}

.setup-page[data-test='setup-page-model'] :deep(.model-preparation) {
  min-height: 0;
}

.setup-dots {
  display: flex;
  justify-content: center;
  gap: 10px;
}

.setup-dot {
  width: 8px;
  height: 8px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: rgba(98, 98, 106, 0.28);
  cursor: pointer;
  transition: width 180ms cubic-bezier(0.2, 0.8, 0.2, 1), background 180ms ease;
}

.setup-dot.done {
  background: rgba(0, 122, 255, 0.45);
}

.setup-dot.active {
  width: 22px;
  background: var(--accent, #007aff);
}

.setup-nav {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 48px;
}

.setup-nav .start-button {
  margin-left: auto;
  min-width: 128px;
}

.nav-hint {
  margin: 0;
  margin-left: auto;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.4;
  max-width: 28ch;
  text-align: right;
}

.nav-hint + .start-button {
  margin-left: 0;
}

.ghost-button {
  appearance: none;
  border: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.55);
  color: var(--text-primary);
  border-radius: 12px;
  min-height: 40px;
  padding: 0 16px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.ghost-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.is-locked {
  opacity: 0.72;
}

.advanced-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 4px;
}

.advanced-fields small {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
}

.prep-placeholder {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  min-height: 180px;
  color: var(--text-secondary);
}

.prep-placeholder h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
  font-weight: 600;
}

.prep-placeholder p {
  margin: 0;
  font-size: 14px;
  line-height: 1.55;
  max-width: 42ch;
}

@media (max-width: 720px) {
  .summary-row {
    grid-template-columns: 1fr;
    gap: 2px;
  }

  .setup-nav {
    flex-wrap: wrap;
  }

  .setup-nav .start-button,
  .nav-hint {
    margin-left: 0;
    width: 100%;
    text-align: left;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .setup-footer {
    background: var(--surface);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .setup-dot {
    transition: none;
  }
}
</style>
