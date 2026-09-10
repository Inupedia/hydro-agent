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
const basin = ref<BasinInfo | null>(null)
const downloadJob = ref<DownloadJob | null>(null)
const busy = ref(false)
const reviewed = ref(false)
const error = ref('')
const modelMode = ref<'lumped' | 'distributed'>('lumped')
const resolution = ref(90)
const streamArea = ref(50)
const unitArea = ref(100)
const warmup = ref(30)
const mapBroken = ref(false)
let planTimer: ReturnType<typeof setInterval> | undefined
let downloadTimer: ReturnType<typeof setInterval> | undefined

const labels: Record<string, string> = {
  queued: '等待建模',
  running: '建模中',
  awaiting_review: '待复核',
  ready: '可开始率定',
  failed: '建模受阻',
  pending: '待开始',
  completed: '已完成',
}
const materials = computed(() => basin.value?.materials || { hydro: false, dem: false, gis: false })
const canBuild = computed(() => {
  if (!basin.value?.ready_for_build) return false
  if (modelMode.value === 'distributed') return !!materials.value.dem && !!materials.value.gis
  return true
})
const showMap = computed(
  () => !!current.value?.boundary_hash && ['awaiting_review', 'ready'].includes(current.value.status),
)
const mapSrc = computed(() =>
  current.value
    ? `/api/model-plans/${encodeURIComponent(current.value.plan_id)}/map?v=${encodeURIComponent(current.value.boundary_hash || current.value.plan_id)}`
    : '',
)

async function refreshBasin() {
  basin.value = props.basinId ? await api.getBasin(props.basinId) : null
}
async function refreshPlans() {
  plans.value = await api.listModelPlans()
  if (current.value) {
    current.value = await api.getModelPlan(current.value.plan_id)
    emit('selected', current.value.status === 'ready' ? current.value : null)
  }
}
async function choose(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  reviewed.value = false
  mapBroken.value = false
  current.value = plans.value.find((item) => item.plan_id === id) || null
  if (current.value?.model_mode) modelMode.value = current.value.model_mode
  emit('selected', current.value?.status === 'ready' ? current.value : null)
}
async function startDownload(components?: string[]) {
  if (!props.basinId) return
  busy.value = true
  error.value = ''
  try {
    downloadJob.value = await api.startBasinDownload(props.basinId, { components })
    if (downloadTimer) clearInterval(downloadTimer)
    downloadTimer = setInterval(async () => {
      if (!downloadJob.value) return
      downloadJob.value = await api.getDownloadJob(downloadJob.value.job_id)
      if (['succeeded', 'failed'].includes(downloadJob.value.status)) {
        if (downloadTimer) clearInterval(downloadTimer)
        downloadTimer = undefined
        await refreshBasin()
      }
    }, 1200)
  } catch (err) {
    error.value = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}
async function create() {
  if (!props.basinId) return
  busy.value = true
  error.value = ''
  reviewed.value = false
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
  } catch (err) {
    error.value = String((err as Error).message || err)
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
  } catch (err) {
    error.value = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}

watch(
  () => props.basinId,
  async () => {
    current.value = null
    emit('selected', null)
    await refreshBasin()
    await refreshPlans()
  },
)
watch(
  () => current.value?.boundary_hash,
  () => (mapBroken.value = false),
)
onMounted(async () => {
  await refreshBasin()
  await refreshPlans()
  current.value = plans.value.find((item) => item.plan_id === props.selectedId) || null
  if (current.value?.model_mode) modelMode.value = current.value.model_mode
  if (current.value) emit('selected', current.value.status === 'ready' ? current.value : null)
  planTimer = setInterval(() => {
    if (current.value && ['queued', 'running'].includes(current.value.status)) void refreshPlans()
  }, 1500)
})
onUnmounted(() => {
  if (planTimer) clearInterval(planTimer)
  if (downloadTimer) clearInterval(downloadTimer)
})
</script>

<template>
  <section class="model-preparation" data-test="model-preparation">
    <header>
      <span class="overline">01 / 建立水文模型</span>
      <h2>选择结构，系统准备长期历史资料</h2>
      <p>
        率定数据默认按完整历史记录自动分成率定集、开发验证集与最终封存测试集。
        不需要手工挑一段“好看的”洪水过程。
      </p>
    </header>

    <p v-if="!basinId" class="muted">请先选择流域。</p>
    <template v-else>
      <div class="materials">
        <div><strong>{{ basin?.label || basinId }}</strong><small>建议历史长度：8–10 年以上</small></div>
        <span :data-ok="materials.hydro">水文长期序列</span>
        <span :data-ok="materials.gis">真实流域边界</span>
        <span :data-ok="materials.dem">DEM 地形</span>
        <div class="actions">
          <button type="button" :disabled="locked || busy" @click="startDownload()">下载 / 补齐资料</button>
          <button v-if="!materials.hydro" type="button" :disabled="locked || busy" @click="startDownload(['hydro'])">仅下载水文</button>
          <button v-if="materials.hydro && (!materials.gis || !materials.dem)" type="button" :disabled="locked || busy" @click="startDownload(['gis','dem'])">补齐地形</button>
        </div>
      </div>

      <div v-if="downloadJob" class="download-progress">
        <div class="bar"><i :style="{ width: `${Math.round((downloadJob.fraction || 0) * 100)}%` }" /></div>
        <p>{{ downloadJob.stage }}<span v-if="downloadJob.current_file"> · {{ downloadJob.current_file }}</span></p>
        <p v-if="downloadJob.error" class="error">{{ downloadJob.error }}</p>
      </div>

      <fieldset :disabled="locked || busy">
        <label>复用已有方案
          <select :value="current?.plan_id || ''" aria-label="复用模型方案" @change="choose">
            <option value="">新建模型方案</option>
            <option v-for="item in plans.filter((plan) => plan.basin_id === basinId)" :key="item.plan_id" :value="item.plan_id">
              {{ item.model_mode === 'distributed' ? '分布式' : '集总式' }} · {{ labels[item.status] || item.status }} · {{ item.plan_id }}
            </option>
          </select>
        </label>

        <div class="mode-grid">
          <button type="button" class="mode-card" :class="{ active: modelMode === 'lumped' }" @click="modelMode = 'lumped'">
            <strong>集总式 XAJ</strong>
            <span>整个流域 1 套 XAJ。最适合先完成课题基线和 Agent 率定验证。</span>
          </button>
          <button type="button" class="mode-card" :class="{ active: modelMode === 'distributed' }" @click="modelMode = 'distributed'">
            <strong>分布式 XAJ</strong>
            <span>DEM → pyflwdir 子流域 → 每单元 gridMET → 多单元 XAJ。单元数由地形自动产生。</span>
          </button>
        </div>

        <details>
          <summary>空间与预热设置</summary>
          <div class="settings">
            <label>DEM 分辨率（m）<input v-model.number="resolution" type="number" min="30" max="1000" /></label>
            <label>河网面积阈值（km²）<input v-model.number="streamArea" type="number" min="1" /></label>
            <label v-if="modelMode === 'distributed'">子流域目标面积（km²）<input v-model.number="unitArea" type="number" min="10" /></label>
            <label>模型预热（天）<input v-model.number="warmup" type="number" min="1" max="365" /></label>
          </div>
        </details>

        <p v-if="modelMode === 'distributed' && !canBuild" class="warning">
          分布式不会回退成等面积切块或复制同一场降雨；必须先具备真实边界和 DEM。
        </p>
        <button class="primary" type="button" :disabled="!canBuild || ['queued','running'].includes(current?.status || '')" @click="create">
          {{ canBuild ? '生成模型方案' : '请先补齐所需资料' }}
        </button>
      </fieldset>

      <p v-if="error || current?.error" role="alert" class="error">{{ error || current?.error }}</p>

      <template v-if="current">
        <div class="plan-status">
          <strong>{{ labels[current.status] || current.status }}</strong>
          <span>{{ current.model_mode === 'distributed' ? `自动 ${current.unit_count || '—'} 个子流域` : '全流域 1 个单元' }}</span>
        </div>
        <ol class="steps">
          <li v-for="step in current.stages" :key="step.code" :data-status="step.status">
            <span>{{ step.label }}</span><b>{{ labels[step.status] || step.status }}</b>
            <small v-if="step.detail">{{ step.detail }}</small>
          </li>
        </ol>
        <figure v-if="showMap && !mapBroken" class="map">
          <img :src="mapSrc" alt="流域边界、真实计算单元与河网" @error="mapBroken = true" />
          <figcaption>复核出口、流域边界和自动形成的计算单元；确认后才会生成率定输入。</figcaption>
        </figure>
        <div v-if="current.status === 'awaiting_review'" class="review">
          <label><input v-model="reviewed" type="checkbox" />我已确认出口、面积与计算单元</label>
          <button type="button" :disabled="!reviewed || busy || locked" @click="confirm">确认并构建长期率定输入</button>
        </div>
        <p v-if="current.status === 'ready'" class="ready">模型方案已就绪。下一步由 Agent 自动执行分阶段率定与独立测试。</p>
      </template>
    </template>
  </section>
</template>

<style scoped>
.model-preparation{padding:24px;background:var(--surface);border:1px solid var(--separator);border-radius:var(--radius-lg);max-height:72vh;overflow:auto;box-shadow:var(--shadow)}
h2{margin:8px 0;font-size:23px}.model-preparation p{font-size:13px;line-height:1.55;color:var(--secondary)}
fieldset{border:0;padding:0;margin-top:16px;display:grid;gap:14px}label{display:grid;gap:6px;font-size:12px}select,input{padding:9px;border:1px solid var(--separator);border-radius:8px;background:var(--surface);color:var(--label)}
.materials{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:12px;border:1px solid var(--separator);border-radius:10px;background:#fafafa}.materials div:first-child{display:grid;margin-right:auto}.materials small{color:var(--tertiary)}.materials span{font-size:11px;padding:5px 8px;border-radius:99px;background:#eee}.materials span[data-ok=true]{background:var(--success-soft)}
.actions{display:flex;gap:6px}.actions button,.review button,.primary{border:0;border-radius:8px;background:var(--blue);color:white;padding:9px 12px;cursor:pointer}.actions button:disabled,.review button:disabled,.primary:disabled{opacity:.45;cursor:default}
.mode-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.mode-card{text-align:left;display:grid;gap:6px;padding:14px;border:1px solid var(--separator);border-radius:12px;background:var(--surface);color:var(--label);cursor:pointer}.mode-card span{font-size:12px;line-height:1.45;color:var(--secondary)}.mode-card.active{border-color:var(--blue);box-shadow:0 0 0 1px var(--blue)}
.settings{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.warning{padding:9px;background:var(--caution-soft);border-radius:8px}.error{color:var(--danger)!important}.ready{padding:10px;background:var(--success-soft);border-radius:8px}.plan-status{display:flex;justify-content:space-between;margin-top:18px;padding:10px 0;border-top:1px solid var(--separator)}
.steps{list-style:none;padding:0;display:grid;gap:6px}.steps li{display:grid;grid-template-columns:1fr auto;gap:4px;padding:8px;border:1px solid var(--separator);border-radius:8px}.steps small{grid-column:1/-1;color:var(--secondary)}.map{margin:12px 0}.map img{width:100%;border-radius:10px;border:1px solid var(--separator)}.map figcaption{font-size:11px;color:var(--secondary);margin-top:5px}.review{display:grid;gap:8px;padding:12px;background:#fafafa;border-radius:10px}.download-progress .bar{height:7px;background:var(--separator);border-radius:99px;overflow:hidden}.download-progress .bar i{display:block;height:100%;background:var(--blue)}
@media(max-width:720px){.mode-grid,.settings{grid-template-columns:1fr}}
</style>
