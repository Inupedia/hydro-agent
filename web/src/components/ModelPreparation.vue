<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, type BasinInfo, type ModelPlan } from '../api/client'
import GlassSelect from './GlassSelect.vue'
import GlassDialog from './GlassDialog.vue'

const props = defineProps<{
  basinId?: string | null
  selectedId?: string | null
  locked?: boolean
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
const selectedPlanIds = ref<string[]>([])
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

const canBuild = computed(() => !!basin.value?.ready_for_build)
const materials = computed(() => basin.value?.materials || { hydro: false, dem: false, gis: false })
const reusePlanOptions = computed(() => [
  { value: '', label: '新建一份模型方案' },
  ...reusablePlans.value.map((plan) => ({
    value: plan.plan_id,
    label: `${plan.plan_id} · ${plan.model_mode === 'distributed' ? '分布式' : '集总式'} · ${labels[plan.status] || plan.status}`,
  })),
])
const selectedReusePlanId = computed({
  get: () => current.value?.plan_id || '',
  set: (id: string) => choosePlan(id),
})
const structureOptions = [
  { value: 'lumped', label: '集总式 · 先切割再合并为 1 套新安江参数' },
  { value: 'distributed', label: '分布式 · 按面积阈值保留全部子流域，每单元一套参数' },
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
        current.value = await api.getModelPlan(activeId)
        emit('selected', current.value.status === 'ready' ? current.value : null)
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
  try {
    current.value = await api.createModelPlan({
      basin_id: props.basinId,
      model_mode: modelMode.value,
      resolution_m: resolution.value,
      stream_area_km2: streamArea.value,
      unit_area_km2: unitArea.value,
      warmup_days: warmup.value,
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

watch(
  () => props.basinId,
  async () => {
    current.value = null
    mapBroken.value = false
    selectedPlanIds.value = []
    manageOpen.value = false
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
  timer = setInterval(() => {
    if (current.value && ['queued', 'running'].includes(current.value.status)) void refreshPlans()
  }, 1500)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <section class="model-preparation" data-test="model-preparation">
    <header>
      <span class="overline">01 / 数据准备</span>
      <h2>用本地流域资料建立计算单元</h2>
      <p>
        系统使用所选流域的日水文、GIS 与 DEM 资料建立模型方案。集总式使用全流域 1 套 XAJ；分布式方案会保留多个计算单元，具体划分说明以边界复核结果为准。
      </p>
    </header>

    <p v-if="!basinId" class="basin-caption">请先选择研究流域。</p>
    <div v-else class="prep-body">
      <div class="materials">
        <strong>{{ basin?.label || basinId }}</strong>
        <ul>
          <li :data-ok="materials.hydro">水文：日降水 / 蒸散发 / 流量</li>
          <li :data-ok="materials.gis">GIS：站点与流域图层</li>
          <li :data-ok="materials.dem">DEM：本地高程栅格与来源记录</li>
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
          <span><strong>{{ plan.plan_id }}</strong><small>{{ plan.model_mode || 'lumped' }} · {{ labels[plan.status] || plan.status }}</small></span>
        </label>
        <p v-if="!deletablePlans.length">当前没有可批量删除的模型方案。</p>
        <template #footer>
          <span>已选 {{ selectedPlanIds.length }} 个</span>
          <button type="button" class="danger-button" data-test="delete-selected-plans" :disabled="!selectedPlanIds.length || busy || locked" @click="removeSelectedPlans">
            删除选中
          </button>
        </template>
      </GlassDialog>

      <fieldset :disabled="locked || busy || loadingBasin || !canBuild">
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
              ? '集总：仍按 DEM 划分子流域，再合并成全流域 1 套参数；手工调参走这条路径。'
              : '分布式：UNIT_AREA_KM2 控制 PyFlwDir subbasins_area；河网阈值只画河网，不决定出口。单元数由阈值算出。'
          }}
        </p>
        <details open>
          <summary>划分与预热参数（与建模笔记第 2、3 节相同）</summary>
          <div class="model-settings">
            <label>DEM 分辨率 RESOLUTION（m）<input v-model.number="resolution" type="number" min="30" max="1000" /></label>
            <label>河网阈值 STREAM_AREA_KM2（km²）<input v-model.number="streamArea" type="number" min="1" /></label>
            <label>单元面积阈值 UNIT_AREA_KM2（km²）<input v-model.number="unitArea" type="number" min="1" /></label>
            <label>预热天数 WARMUP_DAYS<input v-model.number="warmup" type="number" min="1" max="1000" /></label>
          </div>
        </details>
      </fieldset>

      <p v-if="error || current?.error" role="alert" class="model-error">{{ error || current?.error }}</p>
      <template v-if="current">
        <div class="plan-status"><strong>{{ labels[current.status] }}</strong><span>{{ current.plan_id }} · {{ current.model_mode }}</span></div>
        <ol class="model-steps">
          <li v-for="step in current.stages" :key="step.code" :data-status="step.status">
            <span>{{ step.label }}</span><b>{{ labels[step.status] || step.status }}</b>
            <small v-if="step.detail">{{ step.detail }}</small>
          </li>
        </ol>

        <figure v-if="showMap && !mapBroken" class="gis-map" data-test="gis-map">
          <img :src="mapSrc" alt="流域边界、计算单元与河网" @error="mapBroken = true" />
          <figcaption>流域划分结果：色块为计算单元，红点为流域出口。请核对面积与边界后再确认。</figcaption>
        </figure>
        <p v-else-if="showMap && mapBroken" class="basin-caption">边界图暂不可用，请重新新建方案后再复核。</p>

        <div v-if="current.boundary" class="boundary-review">
          <p>
            面积 {{ Number(current.boundary.dem_area_km2 || current.boundary.usgs_area_km2 || current.area_km2 || 0).toFixed(2) }} km² ·
            {{ current.unit_count || 1 }} 套 XAJ · {{ current.model_mode }}
          </p>
          <p v-if="current.boundary.note" class="basin-caption">{{ current.boundary.note }}</p>
          <template v-if="current.status === 'awaiting_review'">
            <label class="review-check"><input v-model="reviewed" type="checkbox" />我已确认出口位置、面积与单元划分</label>
            <button type="button" class="primary-button" :disabled="!reviewed || busy || locked" @click="confirm">确认边界，构建模型输入</button>
          </template>
        </div>
        <p v-if="current.status === 'ready'" class="model-ready">方案已就绪，可在右侧设定时段并开始运行。</p>
      </template>
    </div>
    <div v-if="basinId" class="prep-actions">
      <button
        type="button"
        class="primary-button"
        data-test="build-plan"
        :disabled="loadingBasin || !canBuild || busy || ['running','queued'].includes(current?.status || '')"
        @click="create"
      >
        {{ buildLabel }}
      </button>
    </div>
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
.model-preparation header { flex: 0 0 auto; }
.prep-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-right: 4px;
}
.prep-actions {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 0 calc(8px + env(safe-area-inset-bottom, 0px));
  border-top: 1px solid var(--separator);
  background: transparent;
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
.model-preparation fieldset {
  border: 0;
  padding: 0;
  display: grid;
  gap: 16px;
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
}
.reuse-actions { display: flex; gap: 8px; align-items: center; }
.model-settings {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}
.model-preparation summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
}
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
}
.primary-button {
  background: var(--primary-button);
  color: var(--primary-button-text);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
}
.primary-button:hover:not(:disabled) { background: var(--accent-hover); }
.primary-button:active:not(:disabled) { background: var(--accent-pressed); }
.manage-button { background: var(--neutral-soft); color: var(--text-primary); white-space: nowrap; }
.manage-button:hover:not(:disabled) { background: #e7e8ec; }
.danger-button {
  background: var(--danger-soft);
  color: var(--danger);
  white-space: nowrap;
}
.danger-button:hover:not(:disabled) { background: #ffe3e5; }
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
  gap: 10px;
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: var(--radius-md);
}
.materials ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 6px;
  font-size: 13px;
}
.materials li::before { content: '○ '; color: var(--text-tertiary); }
.materials li[data-ok='true']::before { content: '● '; color: var(--success); }
.plan-status {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  color: var(--text-primary);
}
.model-steps {
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}
.model-steps li {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  padding: 14px 16px;
  border-left: 3px solid var(--separator);
  background: var(--surface);
  border-radius: 0 var(--radius-xs) var(--radius-xs) 0;
  font-size: 13px;
}
.model-steps li[data-status='completed'] { border-color: var(--success); }
.model-steps li[data-status='running'],
.model-steps li[data-status='awaiting_review'] { border-color: var(--accent); }
.model-steps li[data-status='failed'] { border-color: var(--danger); }
.model-steps small {
  width: 100%;
  overflow-wrap: anywhere;
  color: var(--text-secondary);
}
.gis-map {
  margin: 0;
  padding: 16px;
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: var(--radius-md);
}
.gis-map img {
  display: block;
  width: 100%;
  max-height: min(420px, 42vh);
  object-fit: contain;
  background: var(--background);
  border-radius: 10px;
}
.gis-map figcaption {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.boundary-review .review-check {
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
.overline {
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 1.6px;
  color: var(--text-secondary);
}
</style>
