<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, type BasinInfo, type ModelPlan } from '../api/client'
import GlassSelect from './GlassSelect.vue'
import GlassDialog from './GlassDialog.vue'
import RenameDialog from './RenameDialog.vue'
import SpatialHeterogeneityPanel from './SpatialHeterogeneityPanel.vue'
import { BorderBeam, NumberTicker, RippleButton } from './ui'

const props = defineProps<{
  basinId?: string | null
  selectedId?: string | null
  locked?: boolean
  /** Hide page chrome when nested inside SetupWizard (wizard owns the step title). */
  embedded?: boolean
}>()
const emit = defineEmits<{ selected: [plan: ModelPlan | null] }>()

const plans = ref<ModelPlan[]>([])
const current = ref<ModelPlan | null>(null)
const busy = ref(false)
const loadingBasin = ref(true)
const error = ref('')
const reviewed = ref(false)
const modelMode = ref<'lumped' | 'distributed'>('lumped')
const resolution = ref(90)
const streamArea = ref(50)
const unitArea = ref(50)
const warmup = ref(365)
const basin = ref<BasinInfo | null>(null)
const mapBroken = ref(false)
const manageOpen = ref(false)
const buildOpen = ref(false)
const selectedPlanIds = ref<string[]>([])
const planName = ref('')
const renameTarget = ref<ModelPlan | null>(null)
const renameBusy = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

const labels: Record<string, string> = {
  queued: '等待建模',
  running: '建模中',
  awaiting_review: '待复核边界',
  ready: '可用于计算',
  failed: '建模受阻',
  pending: '待开始',
  completed: '已完成',
}

function planLabel(plan: ModelPlan) {
  const title = plan.name?.trim()
  return title || plan.plan_id
}

const canBuild = computed(() => !!basin.value?.ready_for_build)
const materials = computed(() => basin.value?.materials || { hydro: false, dem: false, gis: false })
const reusePlanOptions = computed(() => [
  { value: '', label: '新建一份模型方案' },
  ...reusablePlans.value.map((plan) => ({
    value: plan.plan_id,
    label: `${planLabel(plan)} · ${plan.model_mode === 'distributed' ? '分布式' : '集总式'} · ${labels[plan.status] || plan.status}`,
  })),
])
const selectedReusePlanId = computed({
  get: () => current.value?.plan_id || '',
  set: (id: string) => choosePlan(id),
})
const structureOptions = [
  { value: 'lumped', label: '集总式 · 全流域一套新安江参数' },
  { value: 'distributed', label: '分布式 · DEM+PyFlwDir 划分子流域，每单元一套参数' },
]
const buildLabel = computed(() => {
  if (loadingBasin.value) return '正在检查资料…'
  if (!basin.value && error.value) return '无法读取流域资料'
  if (canBuild.value) return busy.value ? '正在创建…' : '新建流域模型'
  return '本地资料不完整'
})
const reusablePlans = computed(() => plans.value.filter((p) => p.basin_id === props.basinId))
const deletablePlans = computed(() =>
  reusablePlans.value.filter((p) => !['queued', 'running'].includes(p.status)),
)
const canDelete = computed(
  () => !!current.value && !['queued', 'running'].includes(current.value.status) && !props.locked && !busy.value,
)
const allDeletableSelected = computed(
  () => deletablePlans.value.length > 0 && deletablePlans.value.every((plan) => selectedPlanIds.value.includes(plan.plan_id)),
)
const showMap = computed(
  () =>
    !!current.value &&
    ['awaiting_review', 'ready', 'running', 'queued'].includes(current.value.status) &&
    !!current.value.boundary_hash,
)
const needsBuildDialog = computed(() =>
  ['queued', 'running', 'awaiting_review', 'failed'].includes(current.value?.status || ''),
)
const buildTitle = computed(() => {
  const status = current.value?.status
  if (status === 'awaiting_review') return '复核流域边界'
  if (status === 'ready') return '方案已就绪'
  if (status === 'failed') return '建模受阻'
  if (status === 'queued' || status === 'running' || busy.value) return '正在建模'
  return '新建流域模型'
})
const buildFooterHint = computed(() => {
  const status = current.value?.status
  if (status === 'awaiting_review') return reviewed.value ? '可以确认边界并继续构建' : '请先勾选确认出口、面积与单元划分'
  if (status === 'ready') return '方案可用于右侧时段设定与计算'
  if (status === 'failed') return '请关闭后检查资料或参数，再重新新建'
  if (status === 'queued') return '方案已进入建模队列'
  if (status === 'running' && !activeStep.value) return '前三步已完成，正在后台完成后处理'
  if (status === 'running' || busy.value) return '正在执行划分与资料检查，请稍候'
  return '正在创建方案'
})
const areaKm2Raw = computed(() => {
  const boundary = current.value?.boundary
  const raw = Number(boundary?.dem_area_km2 || boundary?.usgs_area_km2 || current.value?.area_km2 || 0)
  return Number.isFinite(raw) && raw > 0 ? raw : null
})
const materialsList = computed(() => [
  { key: 'hydro', ok: !!materials.value.hydro, label: '水文', detail: '日降水 / 蒸散发 / 流量' },
  { key: 'gis', ok: !!materials.value.gis, label: 'GIS', detail: '站点与流域图层' },
  { key: 'dem', ok: !!materials.value.dem, label: 'DEM', detail: '本地高程栅格与来源记录' },
])
const materialsReadyCount = computed(() => materialsList.value.filter((item) => item.ok).length)
const HIDDEN_BUILD_STAGES = new Set(['M04_BUILD_INPUTS', 'M05_VALIDATE_PLAN'])
const visibleStages = computed(() =>
  (current.value?.stages || []).filter((step) => !HIDDEN_BUILD_STAGES.has(step.code)).slice(0, 3),
)
const activeStep = computed(() =>
  visibleStages.value.find((step) => ['running', 'awaiting_review'].includes(step.status)),
)
const mapSrc = computed(() =>
  current.value
    ? `/api/model-plans/${encodeURIComponent(current.value.plan_id)}/map?v=${encodeURIComponent(current.value.boundary_hash || current.value.plan_id)}`
    : '',
)

async function refreshBasin() {
  if (!props.basinId) {
    basin.value = null
    loadingBasin.value = false
    return
  }
  loadingBasin.value = true
  error.value = ''
  try {
    basin.value = await api.getBasin(props.basinId)
    error.value = ''
  } catch (e) {
    basin.value = null
    error.value = String((e as Error).message || e)
  } finally {
    loadingBasin.value = false
  }
}

async function refreshPlans() {
  try {
    plans.value = await api.listModelPlans()
    const activeId = current.value?.plan_id
    if (activeId) {
      const exists = plans.value.some((plan) => plan.plan_id === activeId)
      if (!exists) {
        current.value = null
        emit('selected', null)
      } else {
        const latest = await api.getModelPlan(activeId)
        current.value = latest || plans.value.find((plan) => plan.plan_id === activeId) || null
        emit('selected', current.value?.status === 'ready' ? current.value : null)
      }
    }
    selectedPlanIds.value = selectedPlanIds.value.filter((id) =>
      deletablePlans.value.some((plan) => plan.plan_id === id),
    )
  } catch (e) {
    error.value = String((e as Error).message || e)
  }
}

async function choosePlan(id: string) {
  reviewed.value = false
  mapBroken.value = false
  current.value = plans.value.find((p) => p.plan_id === id) || null
  emit('selected', current.value?.status === 'ready' ? current.value : null)
  if (needsBuildDialog.value) openBuild()
  else closeBuild()
}

function openBuild() {
  manageOpen.value = false
  buildOpen.value = true
}

function closeBuild() {
  buildOpen.value = false
}

async function create() {
  if (!props.basinId) {
    error.value = '请先选择流域'
    return
  }
  busy.value = true
  error.value = ''
  reviewed.value = false
  mapBroken.value = false
  emit('selected', null)
  openBuild()
  try {
    current.value = await api.createModelPlan({
      basin_id: props.basinId,
      model_mode: modelMode.value,
      resolution_m: resolution.value,
      stream_area_km2: streamArea.value,
      unit_area_km2: unitArea.value,
      warmup_days: warmup.value,
      ...(planName.value.trim() ? { name: planName.value.trim() } : {}),
    })
    await refreshPlans()
  } catch (e) {
    error.value = String((e as Error).message || e)
  } finally {
    busy.value = false
  }
}

async function confirm() {
  if (!current.value?.boundary_hash || !reviewed.value) return
  busy.value = true
  error.value = ''
  try {
    current.value = await api.confirmBoundary(current.value.plan_id, current.value.boundary_hash)
  } catch (e) {
    error.value = String((e as Error).message || e)
  } finally {
    busy.value = false
  }
}

async function performDelete(ids: string[]) {
  const uniqueIds = [...new Set(ids)].filter(Boolean)
  if (!uniqueIds.length) return
  busy.value = true
  error.value = ''
  const results = await Promise.allSettled(uniqueIds.map((id) => api.deleteModelPlan(id)))
  const deleted = new Set<string>()
  const failed: string[] = []
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') deleted.add(uniqueIds[index])
    else failed.push(uniqueIds[index])
  })
  if (current.value && deleted.has(current.value.plan_id)) {
    current.value = null
    reviewed.value = false
    mapBroken.value = false
    emit('selected', null)
  }
  selectedPlanIds.value = selectedPlanIds.value.filter((id) => !deleted.has(id))
  await refreshPlans()
  busy.value = false
  if (failed.length) error.value = `有 ${failed.length} 个方案删除失败，请检查是否仍被任务占用。`
}

async function remove() {
  if (!current.value || !canDelete.value) return
  const id = current.value.plan_id
  if (!window.confirm(`删除复用方案 ${id}？此操作不可恢复。`)) return
  await performDelete([id])
}

function openManage() {
  manageOpen.value = true
}

function closeManage() {
  manageOpen.value = false
  selectedPlanIds.value = []
}

function toggleAllPlans() {
  selectedPlanIds.value = allDeletableSelected.value
    ? []
    : deletablePlans.value.map((plan) => plan.plan_id)
}

async function removeSelectedPlans() {
  const ids = [...selectedPlanIds.value]
  if (!ids.length) return
  if (!window.confirm(`删除选中的 ${ids.length} 个模型方案？此操作不可恢复。`)) return
  await performDelete(ids)
  if (!selectedPlanIds.value.length) closeManage()
}

function openRename(plan: ModelPlan) {
  renameTarget.value = plan
}

function closeRename() {
  if (renameBusy.value) return
  renameTarget.value = null
}

async function saveRename(name: string | null) {
  const plan = renameTarget.value
  if (!plan) return
  renameBusy.value = true
  error.value = ''
  try {
    const updated = await api.renameModelPlan(plan.plan_id, name)
    plans.value = plans.value.map((row) => (row.plan_id === updated.plan_id ? { ...row, ...updated } : row))
    if (current.value?.plan_id === updated.plan_id) {
      current.value = updated
      if (updated.status === 'ready') emit('selected', updated)
    }
    renameTarget.value = null
  } catch (e) {
    error.value = String((e as Error).message || e)
  } finally {
    renameBusy.value = false
  }
}

watch(
  () => props.basinId,
  async () => {
    current.value = null
    mapBroken.value = false
    selectedPlanIds.value = []
    manageOpen.value = false
    closeBuild()
    emit('selected', null)
    await refreshBasin()
    await refreshPlans()
  },
)

watch(
  () => current.value?.boundary_hash,
  () => {
    mapBroken.value = false
  },
)

onMounted(async () => {
  await refreshBasin()
  await refreshPlans()
  current.value = plans.value.find((p) => p.plan_id === props.selectedId) || null
  if (current.value) emit('selected', current.value.status === 'ready' ? current.value : null)
  if (needsBuildDialog.value) openBuild()
  timer = setInterval(() => {
    if (current.value && ['queued', 'running'].includes(current.value.status)) void refreshPlans()
  }, 1500)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <section class="model-preparation" :class="{ 'is-embedded': embedded }" data-test="model-preparation">
    <header v-if="!embedded">
      <span class="overline">数据准备</span>
      <h2>用本地流域资料建立计算单元</h2>
      <p>
        系统使用所选流域的日水文、GIS 与 DEM 资料建立模型方案。集总式使用全流域 1 套 XAJ；分布式方案会保留多个计算单元，具体划分说明以边界复核结果为准。
      </p>
    </header>

    <p v-if="!basinId" class="basin-caption">请先选择研究流域。</p>
    <div v-else class="prep-body">
      <div class="materials" :data-ready="canBuild || undefined">
        <div class="materials-head">
          <div class="materials-title">
            <strong>{{ basin?.label || basinId }}</strong>
            <span class="materials-id">{{ basinId }}</span>
          </div>
          <span class="materials-count" :data-ok="canBuild || undefined">
            {{ loadingBasin ? '核对中' : `${materialsReadyCount}/3 齐全` }}
          </span>
        </div>
        <ul>
          <li v-for="item in materialsList" :key="item.key" :data-ok="item.ok">
            <span class="mat-mark" aria-hidden="true" />
            <span class="mat-copy">
              <b>{{ item.label }}</b>
              <small>{{ item.detail }}</small>
            </span>
            <span class="mat-state">{{ item.ok ? '已就绪' : '缺失' }}</span>
          </li>
        </ul>
        <p v-if="loadingBasin" class="basin-caption">正在核对本地流域资料。</p>
        <p v-else-if="canBuild" class="basin-caption">本地资料可用于建模。请建立方案并复核边界。</p>
        <p v-else class="basin-caption">
          尚未确认本地资料齐全。
          <button type="button" class="text-button" @click="refreshBasin">重新检查</button>
        </p>
      </div>

      <div class="reuse-row">
        <label>复用模型方案
          <GlassSelect
            v-model="selectedReusePlanId"
            aria-label="复用模型方案"
            :disabled="locked || busy"
            :options="reusePlanOptions"
          />
        </label>
        <div class="reuse-actions">
          <button type="button" class="manage-button" data-test="manage-plans" :disabled="locked || busy || !reusablePlans.length" @click="openManage">
            批量管理
          </button>
          <button type="button" class="danger-button" data-test="delete-plan" :disabled="!canDelete" @click="remove">
            删除当前
          </button>
        </div>
      </div>

      <GlassDialog
        :open="manageOpen"
        test-id="bulk-plan-manager"
        overline="模型方案"
        title="批量管理"
        labelled-by="plan-manager-title"
        @close="closeManage"
      >
        <template #toolbar>
          <span>仅可删除未在建模中的方案</span>
          <button type="button" class="text-button" :disabled="!deletablePlans.length" @click="toggleAllPlans">
            {{ allDeletableSelected ? '取消全选' : '全选可删除方案' }}
          </button>
        </template>
        <label v-for="plan in deletablePlans" :key="plan.plan_id" class="glass-dialog-item">
          <input v-model="selectedPlanIds" type="checkbox" :value="plan.plan_id" />
          <span>
            <strong>{{ planLabel(plan) }}</strong>
            <small>{{ plan.plan_id }} · {{ plan.model_mode || 'lumped' }} · {{ labels[plan.status] || plan.status }}</small>
          </span>
          <button type="button" class="text-button" :disabled="busy || locked" @click.prevent="openRename(plan)">重命名</button>
        </label>
        <p v-if="!deletablePlans.length">当前没有可批量删除的模型方案。</p>
        <template #footer>
          <span>已选 {{ selectedPlanIds.length }} 个</span>
          <button type="button" class="danger-button" data-test="delete-selected-plans" :disabled="!selectedPlanIds.length || busy || locked" @click="removeSelectedPlans">
            删除选中
          </button>
        </template>
      </GlassDialog>

      <RenameDialog
        :open="!!renameTarget"
        overline="模型方案"
        title="重命名方案"
        hint="留空则恢复为系统编号。"
        placeholder="例如：腰古集总 2020 汛期"
        :initial-name="renameTarget?.name"
        :busy="renameBusy"
        test-id="rename-plan-dialog"
        @close="closeRename"
        @save="saveRename"
      />

      <fieldset class="structure-block" :disabled="locked || busy || loadingBasin || !canBuild">
        <label>方案名称（可选）
          <input
            v-model="planName"
            type="text"
            maxlength="80"
            data-test="plan-name"
            placeholder="例如：腰古集总 2020 汛期"
            :disabled="locked || busy"
          />
        </label>
        <label>结构模式
          <GlassSelect
            :model-value="modelMode"
            aria-label="结构模式"
            :options="structureOptions"
            @update:model-value="(value) => { if (value === 'lumped' || value === 'distributed') modelMode = value }"
          />
        </label>
        <p class="mode-hint">
          {{
            modelMode === 'lumped'
              ? '集总：全流域 1 套参数。腰古会先 DEM 切割再合并；Leaf River 直接用 NLDI 全流域边界。'
              : '分布式：DEM + PyFlwDir subbasins_area 划界（UNIT_AREA_KM2 为面积阈值，单元数由阈值算出）；Leaf / 腰古同一套语义，禁止等面积假分区。'
          }}
        </p>
        <details open class="param-details">
          <summary>划分与预热参数</summary>
          <div class="model-settings">
            <label>DEM 分辨率 RESOLUTION（m）<input v-model.number="resolution" type="number" min="30" max="1000" /></label>
            <label>河网阈值 STREAM_AREA_KM2（km²）<input v-model.number="streamArea" type="number" min="1" /></label>
            <label>单元面积阈值 UNIT_AREA_KM2（km²）<input v-model.number="unitArea" type="number" min="1" /></label>
            <label>预热天数 WARMUP_DAYS<input v-model.number="warmup" type="number" min="1" max="1000" /></label>
          </div>
        </details>
      </fieldset>

      <p v-if="error && !buildOpen" role="alert" class="model-error">{{ error }}</p>
      <div v-if="current" class="plan-summary" :data-status="current.status" data-test="plan-summary">
        <span class="status-pill">{{ labels[current.status] }}</span>
        <span class="plan-meta">
          <strong>{{ planLabel(current) }}</strong>
          <small v-if="current.name">{{ current.plan_id }} · {{ current.model_mode || 'lumped' }}</small>
          <template v-else>{{ current.plan_id }} · {{ current.model_mode || 'lumped' }}</template>
        </span>
        <button type="button" class="text-button" data-test="rename-plan" :disabled="busy || locked" @click="openRename(current)">重命名</button>
        <button type="button" class="text-button" data-test="open-build" @click="openBuild">
          {{ current.status === 'awaiting_review' ? '继续复核' : current.status === 'ready' ? '查看结果' : current.status === 'failed' ? '查看原因' : '查看进度' }}
        </button>
      </div>
    </div>
    <div v-if="basinId" class="prep-actions">
      <RippleButton
        type="button"
        class="primary-button"
        data-test="build-plan"
        :disabled="loadingBasin || !canBuild || busy || ['running','queued'].includes(current?.status || '')"
        @click="create"
      >
        {{ buildLabel }}
      </RippleButton>
    </div>

    <GlassDialog
      :open="buildOpen"
      test-id="build-plan-dialog"
      overline="建模流程"
      :title="buildTitle"
      labelled-by="build-plan-title"
      size="wide"
      :close-on-backdrop="false"
      @close="closeBuild"
    >
      <div class="build-flow">
        <p v-if="error || current?.error" role="alert" class="model-error">{{ error || current?.error }}</p>
        <div v-if="current" class="plan-status">
          <strong>{{ labels[current.status] }}</strong>
          <span>{{ planLabel(current) }} · {{ current.model_mode }}</span>
        </div>
        <ol v-if="visibleStages.length" class="model-steps" data-test="model-steps">
          <li
            v-for="step in visibleStages"
            :key="step.code"
            :data-status="step.status"
            :data-active="activeStep?.code === step.code"
            :data-step="step.code"
          >
            <BorderBeam v-if="activeStep?.code === step.code" :size="56" :radius="12" />
            <div class="step-head">
              <span>{{ step.label }}</span>
              <b>{{ labels[step.status] || step.status }}</b>
              <small v-if="step.detail">{{ step.detail }}</small>
            </div>
            <div
              v-if="step.code === 'M03_REVIEW_BOUNDARY' && (showMap || current?.boundary)"
              class="step-body"
              data-test="boundary-step-body"
            >
              <figure v-if="showMap && !mapBroken" class="gis-map" data-test="gis-map">
                <img :src="mapSrc" alt="流域边界、计算单元与河网" @error="mapBroken = true" />
                <figcaption>流域划分结果：色块为计算单元，红点为流域出口。请核对面积与边界后再确认。</figcaption>
              </figure>
              <p v-else-if="showMap && mapBroken" class="basin-caption">边界图暂不可用，请重新新建方案后再复核。</p>
              <div v-if="current?.boundary" class="boundary-review">
                <p class="boundary-metrics">
                  面积
                  <NumberTicker
                    class="boundary-area"
                    :value="areaKm2Raw"
                    :decimal-places="2"
                    :duration="700"
                    empty="-"
                  />
                  km² ·
                  {{ current.unit_count || 1 }} 套 XAJ · {{ current.model_mode }}
                </p>
                <p v-if="current.boundary.note" class="basin-caption">{{ String(current.boundary.note) }}</p>
              </div>

              <SpatialHeterogeneityPanel
                v-if="current?.spatial_profile || current?.unit_candidates?.length || current?.unit_recommendation"
                :profile="current.spatial_profile"
                :profile-status="current.spatial_profile_status"
                :candidates="current.unit_candidates || []"
                :recommendation="current.unit_recommendation"
              />

              <label v-if="current.status === 'awaiting_review'" class="review-check">
                <input v-model="reviewed" type="checkbox" data-test="review-check" />我已确认出口位置、面积与单元划分
              </label>
            </div>
          </li>
        </ol>
        <p v-else-if="busy" class="basin-caption">正在创建方案并开始划分…</p>
        <p v-if="current?.status === 'ready'" class="model-ready">方案已就绪，可在右侧设定时段并开始运行。</p>
      </div>
      <template #footer>
        <span>{{ buildFooterHint }}</span>
        <RippleButton
          v-if="current?.status === 'awaiting_review'"
          type="button"
          class="primary-button"
          data-test="confirm-boundary"
          :disabled="!reviewed || busy || locked"
          @click="confirm"
        >
          {{ busy ? '正在继续…' : '确认边界，构建模型输入' }}
        </RippleButton>
        <button
          v-else-if="current?.status === 'ready' || current?.status === 'failed'"
          type="button"
          class="primary-button"
          data-test="close-build"
          @click="closeBuild"
        >
          {{ current.status === 'ready' ? '完成' : '关闭' }}
        </button>
      </template>
    </GlassDialog>
  </section>
</template>

<style scoped>
.model-preparation {
  display: flex;
  flex-direction: column;
  gap: 16px;
  flex: 1;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  background: transparent;
  border: 0;
  box-shadow: none;
  padding: 0;
}
.model-preparation.is-embedded {
  gap: 14px;
}
.model-preparation header { flex: 0 0 auto; }
.prep-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding-right: 4px;
  scrollbar-gutter: stable;
}
.prep-actions {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 14px 0 calc(10px + env(safe-area-inset-bottom, 0px));
  border-top: 1px solid var(--separator);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--surface) 42%, transparent), color-mix(in srgb, var(--surface) 92%, transparent));
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
}
.prep-actions .primary-button { min-width: 168px; }
.model-preparation h2 {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: -0.4px;
  margin: 8px 0 8px;
  color: var(--text-primary);
}
.model-preparation p,
.basin-caption,
.mode-hint {
  color: var(--text-secondary);
  line-height: 1.6;
  font-size: 13px;
  margin: 0;
}
.mode-hint { margin-top: -4px; }
.plan-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 12px;
  padding: 12px 14px;
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
  font-size: 13px;
}
.plan-summary .plan-meta {
  color: var(--text-secondary);
  overflow-wrap: anywhere;
  flex: 1 1 auto;
  min-width: 0;
  display: grid;
  gap: 2px;
}
.plan-summary .plan-meta strong {
  color: var(--text-primary);
  font-weight: 600;
}
.plan-summary .plan-meta small {
  font-size: 12px;
  color: var(--text-tertiary);
}
.plan-summary .text-button { margin-left: 0; }
.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  background: var(--neutral-soft);
  color: var(--text-primary);
}
.plan-summary[data-status='ready'] .status-pill {
  background: var(--success-soft);
  color: var(--success);
}
.plan-summary[data-status='awaiting_review'] .status-pill,
.plan-summary[data-status='running'] .status-pill,
.plan-summary[data-status='queued'] .status-pill {
  background: var(--accent-soft);
  color: var(--accent-text);
}
.plan-summary[data-status='failed'] .status-pill {
  background: var(--danger-soft);
  color: var(--danger);
}
.structure-block {
  margin: 0;
  padding: 16px 0 0;
  display: grid;
  gap: 14px;
  background: transparent;
  border: 0;
  border-top: 1px solid var(--separator);
}
.model-preparation label {
  display: grid;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}
.reuse-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: end;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--separator);
}
.reuse-actions { display: flex; gap: 8px; align-items: center; }
.model-settings {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}
.param-details {
  border-top: 1px solid var(--separator);
  padding-top: 12px;
}
.model-preparation summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  list-style: none;
}
.model-preparation summary::-webkit-details-marker { display: none; }
.model-preparation summary::before {
  content: '';
  display: inline-block;
  width: 0;
  height: 0;
  margin-right: 8px;
  border-style: solid;
  border-width: 4px 0 4px 6px;
  border-color: transparent transparent transparent var(--text-tertiary);
  transform: rotate(0deg);
  transition: transform 160ms var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.param-details[open] > summary::before { transform: rotate(90deg); }
.primary-button,
.danger-button,
.manage-button {
  min-height: 40px;
  padding: 0 18px;
  border-radius: var(--radius-sm);
  border: 0;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 140ms var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)), transform 100ms ease;
}
.primary-button {
  background: var(--primary-button);
  color: var(--primary-button-text);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
}
.primary-button:hover:not(:disabled) { background: var(--accent-hover); }
.primary-button:active:not(:disabled) {
  background: var(--accent-pressed);
  transform: scale(0.98);
}
.manage-button { background: var(--neutral-soft); color: var(--text-primary); white-space: nowrap; }
.manage-button:hover:not(:disabled) { background: var(--neutral-hover); }
.danger-button {
  background: var(--danger-soft);
  color: var(--danger);
  white-space: nowrap;
}
.danger-button:hover:not(:disabled) { background: var(--danger-hover); }
.text-button {
  display: inline;
  border: 0;
  background: none;
  color: var(--accent-text);
  padding: 0;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}
.materials {
  display: grid;
  gap: 12px;
  padding: 0 0 16px;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--separator);
}
.materials-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.materials-title {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.materials-title strong {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}
.materials-id {
  font-size: 12px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.materials-count {
  flex: 0 0 auto;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--neutral-soft);
}
.materials-count[data-ok='true'] {
  color: var(--success);
  background: var(--success-soft);
}
.materials ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 8px;
}
.materials li {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-height: 44px;
  padding: 8px 0;
  border-radius: 0;
  background: transparent;
  border-bottom: 1px solid var(--separator);
  font-size: 13px;
}
.mat-mark {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--text-tertiary);
  opacity: 0.45;
}
.materials li[data-ok='true'] .mat-mark {
  background: var(--success);
  opacity: 1;
  box-shadow: 0 0 0 3px rgba(36, 138, 61, 0.14);
}
.mat-copy {
  display: grid;
  gap: 1px;
  min-width: 0;
}
.mat-copy b {
  font-weight: 600;
  color: var(--text-primary);
}
.mat-copy small {
  color: var(--text-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.mat-state {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.materials li[data-ok='true'] .mat-state { color: var(--success); }
.plan-status {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  font-size: 13px;
  color: var(--text-primary);
}
.plan-status span {
  min-width: 0;
  overflow-wrap: anywhere;
  text-align: right;
}
.build-flow {
  display: grid;
  gap: 16px;
  min-width: 0;
  width: 100%;
  overflow-x: hidden;
  align-content: start;
  grid-auto-rows: max-content;
}
.model-steps {
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
  min-width: 0;
}
.model-steps li {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid var(--separator);
  background: var(--surface);
  border-radius: var(--radius-sm);
  font-size: 13px;
  overflow: hidden;
}
.step-head {
  position: relative;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.step-head > span,
.step-head > b {
  min-width: 0;
  overflow-wrap: anywhere;
}
.model-steps li[data-status='completed'] { border-color: #b7e0c2; }
.model-steps li[data-status='running'],
.model-steps li[data-status='awaiting_review'] { border-color: rgba(0, 122, 255, 0.28); }
.model-steps li[data-status='failed'] { border-color: var(--danger); }
.step-head small {
  width: 100%;
  overflow-wrap: anywhere;
  color: var(--text-secondary);
}
.step-body {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 12px;
  min-width: 0;
}
.gis-map {
  margin: 0;
  padding: 16px;
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: var(--radius-md);
  overflow-x: clip;
}
.gis-map img {
  display: block;
  width: 100%;
  max-width: 100%;
  height: auto;
  max-height: min(360px, 38vh);
  object-fit: contain;
  background: var(--background);
  border-radius: 10px;
}
.gis-map figcaption {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.boundary-metrics {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 6px;
  color: var(--text-primary);
  font-size: 14px;
}
.boundary-area {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.boundary-review .review-check,
.step-body > .review-check {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0;
  color: var(--text-primary);
}
.model-error {
  color: var(--danger) !important;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.model-ready { color: var(--success) !important; }
@media (max-width: 720px) {
  .reuse-row {
    grid-template-columns: 1fr;
    align-items: stretch;
  }
  .reuse-actions {
    justify-content: stretch;
  }
  .reuse-actions > * {
    flex: 1 1 auto;
  }
  .model-settings {
    grid-template-columns: 1fr;
  }
  .prep-actions .primary-button {
    width: 100%;
    min-width: 0;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .prep-actions {
    background: var(--surface);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .primary-button,
  .danger-button,
  .manage-button,
  .model-preparation summary::before {
    transition: none;
  }
  .primary-button:active:not(:disabled) {
    transform: none;
  }
}
</style>
