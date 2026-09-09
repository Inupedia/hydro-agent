<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, type BasinInfo, type DownloadJob, type ModelPlan } from '../api/client'

const props = defineProps<{
  basinId?: string | null
  selectedId?: string | null
  locked?: boolean
}>()
const emit = defineEmits<{ selected: [plan: ModelPlan | null] }>()

const plans = ref<ModelPlan[]>([])
const current = ref<ModelPlan | null>(null)
const busy = ref(false)
const error = ref('')
const reviewed = ref(false)
const modelMode = ref<'lumped' | 'distributed'>('lumped')
const resolution = ref(90)
const streamArea = ref(50)
const unitArea = ref(50)
const warmup = ref(30)
const unitCount = ref(4)
const downloadJob = ref<DownloadJob | null>(null)
const basin = ref<BasinInfo | null>(null)
const mapBroken = ref(false)
let timer: ReturnType<typeof setInterval> | undefined
let dlTimer: ReturnType<typeof setInterval> | undefined

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
const needsDownload = computed(() => !!basin.value && !basin.value.ready_for_build)
const materials = computed(() => basin.value?.materials || { hydro: false, dem: false, gis: false })
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
    return
  }
  basin.value = await api.getBasin(props.basinId)
}

async function refreshPlans() {
  try {
    plans.value = await api.listModelPlans()
    if (current.value) {
      current.value = await api.getModelPlan(current.value.plan_id)
      emit('selected', current.value.status === 'ready' ? current.value : null)
    }
  } catch (e) {
    error.value = String((e as Error).message || e)
  }
}

async function choose(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  reviewed.value = false
  mapBroken.value = false
  current.value = plans.value.find((p) => p.plan_id === id) || null
  emit('selected', current.value?.status === 'ready' ? current.value : null)
}

async function startDownload(components?: string[]) {
  if (!props.basinId) return
  busy.value = true
  error.value = ''
  try {
    downloadJob.value = await api.startBasinDownload(props.basinId, { components })
    pollDownload()
  } catch (e) {
    error.value = String((e as Error).message || e)
  } finally {
    busy.value = false
  }
}

function pollDownload() {
  if (dlTimer) clearInterval(dlTimer)
  dlTimer = setInterval(async () => {
    if (!downloadJob.value) return
    try {
      downloadJob.value = await api.getDownloadJob(downloadJob.value.job_id)
      if (['succeeded', 'failed'].includes(downloadJob.value.status)) {
        clearInterval(dlTimer)
        dlTimer = undefined
        await refreshBasin()
      }
    } catch (e) {
      error.value = String((e as Error).message || e)
    }
  }, 1200)
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
      unit_count: unitCount.value,
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

watch(
  () => props.basinId,
  async () => {
    current.value = null
    mapBroken.value = false
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
  if (dlTimer) clearInterval(dlTimer)
})
</script>

<template>
  <section class="model-preparation" data-test="model-preparation">
    <header>
      <span class="overline">数据准备</span>
      <h2>下载公开资料，建立计算单元</h2>
      <p>
        默认 Leaf River（USGS 02472000）。资料下载与边界划分属于建模前的数据准备，不属于后续智能体执行流程。
        集总式 = 1 套 XAJ；分布式切成 N 个单元 = N 套彼此独立的 XAJ。
      </p>
    </header>

    <p v-if="!basinId" class="basin-caption">请在左侧选择一个美国流域。</p>
    <template v-else>
      <div class="materials">
        <strong>{{ basin?.label || basinId }}</strong>
        <ul>
          <li :data-ok="materials.hydro">水文：gridMET / MultiMet + USGS Q</li>
          <li :data-ok="materials.gis">GIS：出口与流域边界</li>
          <li :data-ok="materials.dem">DEM：高程瓦片（分布式需要）</li>
        </ul>
        <div class="actions">
          <button type="button" :disabled="locked || busy" @click="startDownload()">下载 / 补齐全部资料</button>
          <button type="button" :disabled="locked || busy || materials.hydro" @click="startDownload(['hydro'])">仅水文</button>
          <button type="button" :disabled="locked || busy || !materials.hydro" @click="startDownload(['gis','dem'])">仅地形</button>
        </div>
        <div v-if="downloadJob" class="download-progress" data-test="download-progress">
          <div class="bar"><i :style="{ width: `${Math.round((downloadJob.fraction || 0) * 100)}%` }" /></div>
          <p>
            <strong>{{ downloadJob.status }}</strong> · {{ downloadJob.stage }}
            <span v-if="downloadJob.current_file"> · 正在下载 {{ downloadJob.current_file }}</span>
          </p>
          <pre v-if="downloadJob.log_tail">{{ downloadJob.log_tail }}</pre>
          <p v-if="downloadJob.error" class="model-error">{{ downloadJob.error }}</p>
        </div>
      </div>

      <fieldset :disabled="locked || busy || !canBuild">
        <label>复用模型方案
          <select aria-label="复用模型方案" :value="current?.plan_id || ''" @change="choose">
            <option value="">新建一份模型方案</option>
            <option v-for="p in plans.filter(x => x.basin_id === basinId)" :key="p.plan_id" :value="p.plan_id">
              {{ p.plan_id }} · {{ p.model_mode || 'lumped' }} · {{ labels[p.status] }}
            </option>
          </select>
        </label>
        <label>结构模式
          <select v-model="modelMode" aria-label="结构模式">
            <option value="lumped">集总式 · 全流域 1 套 XAJ</option>
            <option value="distributed">分布式 · N 个独立 XAJ（每单元一套）</option>
          </select>
        </label>
        <p class="mode-hint">
          {{
            modelMode === 'lumped'
              ? '集总：整个流域共用一套新安江状态与参数。'
              : `分布式：将切成 ${unitCount} 个计算单元，每个单元各自运行一套独立 XAJ；当前 V1 对面雨量仍用同一格点强迫场。`
          }}
        </p>
        <details open>
          <summary>划分与预热参数（可改）</summary>
          <div class="model-settings">
            <label>DEM 分辨率（m）<input v-model.number="resolution" type="number" min="30" max="1000" /></label>
            <label>河网阈值（km²）<input v-model.number="streamArea" type="number" min="1" /></label>
            <label>单元面积阈值（km²）<input v-model.number="unitArea" type="number" min="1" /></label>
            <label>预热天数<input v-model.number="warmup" type="number" min="1" max="1000" /></label>
            <label v-if="modelMode === 'distributed'">单元数（= XAJ 套数）<input v-model.number="unitCount" type="number" min="2" max="32" /></label>
          </div>
        </details>
        <button type="button" class="start-button" :disabled="!canBuild || busy || ['running','queued'].includes(current?.status || '')" @click="create">
          {{ needsDownload ? '请先下载资料' : '新建流域模型' }}
        </button>
      </fieldset>
    </template>

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
        <figcaption>蓝线为 NLDI 上游河网；色块为计算单元示意；红点为出口。</figcaption>
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
          <button type="button" :disabled="!reviewed || busy || locked" @click="confirm">确认边界，构建模型输入</button>
        </template>
      </div>
      <p v-if="current.status === 'ready'" class="model-ready">方案已就绪，可在左侧设定时段并开始运行。</p>
    </template>
  </section>
</template>

<style scoped>
.model-preparation{
  padding:24px;
  background:var(--surface);
  border:1px solid var(--separator);
  border-radius:var(--radius-lg);
  max-height:70vh;
  overflow:auto;
  box-shadow:var(--shadow);
}
.model-preparation h2{font-size:24px;margin:10px 0;color:var(--label)}
.model-preparation p,.basin-caption,.mode-hint{color:var(--secondary);line-height:1.6;font-size:13px}
.mode-hint{margin:-4px 0 0}
.model-preparation fieldset{border:0;padding:0;display:grid;gap:15px;margin-top:16px}
.model-preparation label{display:grid;gap:7px;font-size:13px;color:var(--label)}
.model-preparation select,.model-preparation input[type=number]{
  padding:10px;border:1px solid var(--separator);border-radius:var(--radius-sm);background:var(--surface);width:100%;color:var(--label)
}
.model-settings{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
.model-preparation summary{cursor:pointer;font-size:13px;color:var(--secondary)}
.model-preparation button,.actions button{
  padding:10px 12px;border-radius:var(--radius-sm);border:0;background:var(--blue);color:white;cursor:pointer;font-size:12px
}
.model-preparation button:disabled,.actions button:disabled{opacity:.45;cursor:default}
.materials{display:grid;gap:10px;padding:14px;background:#fafafa;border:1px solid var(--separator);border-radius:var(--radius-md)}
.materials ul{list-style:none;padding:0;margin:0;display:grid;gap:6px;font-size:13px}
.materials li::before{content:'○ ';color:var(--tertiary)}
.materials li[data-ok=true]::before{content:'● ';color:var(--success)}
.actions{display:flex;flex-wrap:wrap;gap:8px}
.download-progress .bar{height:8px;background:var(--separator);border-radius:99px;overflow:hidden}
.download-progress .bar i{display:block;height:100%;background:var(--blue)}
.download-progress pre{font-size:11px;white-space:pre-wrap;max-height:120px;overflow:auto;background:var(--surface);padding:8px;border-radius:8px;border:1px solid var(--separator)}
.plan-status{display:flex;justify-content:space-between;margin-top:20px;font-size:13px;color:var(--label)}
.model-steps{padding:0;list-style:none;display:grid;gap:8px}
.model-steps li{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;padding:12px;border-left:3px solid var(--separator);background:#fafafa;font-size:13px}
.model-steps li[data-status=completed]{border-color:var(--success)}
.model-steps li[data-status=running],.model-steps li[data-status=awaiting_review]{border-color:var(--blue)}
.model-steps li[data-status=failed]{border-color:var(--danger)}
.model-steps small{width:100%;overflow-wrap:anywhere;color:var(--secondary)}
.gis-map{
  margin:16px 0 0;
  padding:12px;
  background:var(--surface);
  border:1px solid var(--separator);
  border-radius:var(--radius-md);
}
.gis-map img{
  display:block;
  width:100%;
  max-height:min(420px,48vh);
  object-fit:contain;
  background:#F5F5F7;
  border-radius:10px;
}
.gis-map figcaption{margin-top:8px;font-size:12px;color:var(--secondary)}
.boundary-review .review-check{display:flex;align-items:center;margin:12px 0;color:var(--label)}
.model-error{color:var(--danger)!important;white-space:pre-wrap;overflow-wrap:anywhere}
.model-ready{color:var(--success)!important}
.overline{font-size:10px;font-weight:650;letter-spacing:1.8px;color:var(--secondary)}
.start-button{width:100%}
</style>
