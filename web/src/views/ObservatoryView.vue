<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ForecastChart from '../components/ForecastChart.vue'
import LiveWorkflow from '../components/LiveWorkflow.vue'
import ModelPreparation from '../components/ModelPreparation.vue'
import type { ModelPlan } from '../types/api'
import HydrologistTune from '../components/HydrologistTune.vue'
import ParamTuningPanel from '../components/ParamTuningPanel.vue'
import { useDemoStore } from '../stores/demo'
import { api } from '../api/client'
import { gsap, motionDuration, prefersReducedMotion } from '../motion/gsap'
import { AUDIENCE_STAGES, actionTitle, actionExplain, basinLabel, gateDecisionZh, stageForAction, stageStatuses } from '../demo/stages'

const demo = useDemoStore()
const route = useRoute()
const busy = ref(false)
const serviceMode = ref<string | null>(null)
const connected = ref(false)
const modelingAvailable = ref(false)
const hydrologistAvailable = ref(false)
const basins = ref<import('../types/api').BasinInfo[]>([])
const planReady = computed(() => !!demo.draft.model_plan_id)
/** When true, basin changes come from plan binding — do not clear model_plan_id. */
let syncingPlanBasin = false
function selectPlan(plan: ModelPlan | null) {
  if (demo.taskId) return
  if (!plan) {
    demo.draft.model_plan_id = null
    return
  }
  const previous = demo.draft.model_plan_id
  syncingPlanBasin = true
  if (demo.draft.basin_id !== plan.basin_id) {
    demo.draft.basin_id = plan.basin_id
  }
  demo.draft.model_plan_id = plan.plan_id
  if (previous !== plan.plan_id) {
    demo.draft.forcing_mode = 'R'
    if (plan.suggested_start) demo.draft.start_date = plan.suggested_start
    if (plan.suggested_end) demo.draft.end_date = plan.suggested_end
  }
  // Watchers flush after this tick; keep the guard until then.
  void nextTick(() => {
    syncingPlanBasin = false
  })
}
const now = ref(Date.now())
const advanced = ref(false)
const taskPane = ref<HTMLElement | null>(null)
const mainStage = ref<HTMLElement | null>(null)
const journalPane = ref<HTMLElement | null>(null)
const stageTrack = ref<HTMLElement | null>(null)
const decisionStrip = ref<HTMLElement | null>(null)
const forecastSurface = ref<HTMLElement | null>(null)
const tuningMount = ref<HTMLElement | null>(null)
let timer: number | undefined
let layoutTween: ReturnType<typeof gsap.timeline> | null = null

const locked = computed(() => busy.value || !!demo.taskId)
const action = computed(() => demo.run?.llm_decision_action || demo.run?.last_action || demo.timeline.at(-1)?.action)
const showWorkflow = computed(
  () =>
    busy.value ||
    demo.isRunning ||
    !!demo.run?.paused ||
    demo.isFailed ||
    (!!demo.taskId &&
      !demo.results?.forecasts?.length &&
      !!demo.run &&
      demo.run.status !== 'created'),
)
/** Focus stage: live workflow + journal only. */
const focusStage = computed(() => showWorkflow.value && !demo.isCompleted)
const completedActions = computed(() =>
  demo.timeline
    .filter((t) => t.action && !['failed', 'error', 'skipped', 'running'].includes(t.status))
    .map((t) => t.action as string),
)
const gateStatus = computed(() => {
  const fromResults = demo.results?.gate?.status
  if (typeof fromResults === 'string') return fromResults
  const gate = [...demo.timeline].reverse().find((t) => t.action === 'A08_GATE' || t.action === 'A09_RESOLVE')
  return typeof gate?.status === 'string' ? gate.status : null
})
const stage = computed(() => stageForAction(action.value))
const progress = computed(() =>
  stageStatuses(
    demo.timeline.filter((t) => !['failed', 'error', 'skipped'].includes(t.status)).map((t) => t.action || ''),
    action.value || null,
    demo.isCompleted ? 'completed' : demo.run?.status || null,
  ),
)
const progressLabel = (status: string) =>
  ({ pending: '待开始', active: '进行中', done: '已完成', skipped: '未执行', blocked: '已受阻' })[status] || ''
const gate = computed(() =>
  gateDecisionZh(typeof demo.results?.gate?.status === 'string' ? demo.results.gate.status : null, {
    reasons: demo.results?.gate?.reason_codes || demo.results?.gate?.reasons,
    metrics: (demo.results?.gate?.metrics as Record<string, unknown> | undefined) || null,
  }),
)
const showTuning = computed(
  () =>
    !focusStage.value &&
    !!demo.results &&
    (!!demo.results.diagnosis ||
      !!demo.results.optimize ||
      !!(demo.results.scheme?.parameter_delta && Object.keys(demo.results.scheme.parameter_delta).length) ||
      !!(demo.results.scheme?.parameters && Object.keys(demo.results.scheme.parameters).length)),
)
const showHydrologist = computed(
  () =>
    hydrologistAvailable.value &&
    !focusStage.value &&
    !!demo.taskId &&
    !!demo.draft.model_plan_id &&
    (showTuning.value ||
      demo.run?.paused ||
      demo.run?.status === 'idle' ||
      !!demo.results?.optimize ||
      completedActions.value.includes('A06_DIAGNOSE') ||
      completedActions.value.includes('A07_OPTIMIZE')),
)
const mode = computed(() =>
  demo.mode === 'replay' ? '历史记录' : serviceMode.value === 'real' ? '真实计算' : serviceMode.value ? '模拟演示' : '连接待确认',
)
const title = computed(() =>
  demo.isFailed
    ? '本次计算暂时受阻'
    : demo.isCompleted
      ? '计算已完成'
      : demo.isRunning
        ? actionTitle(action.value)
        : demo.run?.paused
          ? '计算已暂停'
          : demo.mode === 'replay'
            ? '案例结果'
            : '待开始',
)
const description = computed(() =>
  demo.isFailed
    ? '右侧记录标明停在哪一步。'
    : demo.isCompleted
      ? '下图为当前方案预报序列，右侧为执行记录与报告。'
      : demo.isRunning
        ? actionExplain(action.value)
        : '先完成建模与任务设定，再启动运行。',
)
/** Chart series: prefer frozen/current scheme, one point per issue day. */
const chartForecasts = computed(() => {
  const rows = demo.results?.forecasts || []
  if (!rows.length) return []
  const preferred =
    demo.results?.scheme?.scheme_id ||
    demo.run?.current_scheme_id ||
    null
  const scoped = preferred ? rows.filter((f) => f.scheme_id === preferred) : rows
  const pool = scoped.length ? scoped : rows
  const byIssue = new Map<string, (typeof rows)[number]>()
  for (const row of pool) {
    const key = String(row.issue_time).slice(0, 10)
    // Keep the latest forecast id for that issue day.
    byIssue.set(key, row)
  }
  return [...byIssue.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, row]) => row)
})
const elapsed = computed(() => {
  if (!demo.startedAt || demo.isCompleted || demo.isFailed) return demo.isCompleted ? '已结束' : '等待开始'
  const seconds = Math.max(0, Math.floor((now.value - demo.startedAt) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
})
const eventStatus = (status: string) =>
  ({ succeeded: '已完成', completed: '已完成', success: '已完成', running: '进行中', failed: '失败', error: '失败', skipped: '已跳过' })[
    status
  ] || '执行记录'
const events = computed(() => [...demo.timeline].reverse())
const reports = computed(() => demo.results?.report_artifacts || [])
const error = computed(() => demo.error || demo.run?.llm_error)

async function begin() {
  busy.value = true
  try {
    if (!demo.taskId) await demo.createTaskFromDraft()
    await demo.startRun()
  } catch (err) {
    demo.error = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}
async function resume() {
  busy.value = true
  try {
    await demo.resumeCompute()
  } catch (err) {
    demo.error = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}
async function openCase(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  const task = demo.caseLibrary.find((t) => t.task_id === id)
  if (task) await demo.openCaseReplay(task)
}
function newTask() {
  demo.resetSession()
  history.replaceState(null, '', '/')
}

function animateFocus(enter: boolean) {
  layoutTween?.kill()
  const reduced = prefersReducedMotion()
  const dur = motionDuration(0.55)
  const task = taskPane.value
  const main = mainStage.value
  const track = stageTrack.value
  const decision = decisionStrip.value
  if (!main) return

  layoutTween = gsap.timeline({ defaults: { ease: 'power3.out' } })
  if (enter) {
    if (task) {
      layoutTween.to(task, { autoAlpha: 0, duration: dur * 0.45, pointerEvents: 'none' }, 0)
    }
    layoutTween.fromTo(
      main,
      { scale: reduced ? 1 : 0.97, transformOrigin: '50% 40%' },
      { scale: 1, duration: dur, clearProps: 'transform' },
      0,
    )
    const workflow = main.querySelector('.live-workflow')
    if (workflow) {
      layoutTween.fromTo(
        workflow,
        { scale: reduced ? 1 : 0.9, autoAlpha: 0.4, y: 18 },
        { scale: 1, autoAlpha: 1, y: 0, duration: dur, ease: 'power3.out', clearProps: 'transform' },
        0.06,
      )
    }
  } else {
    if (task) {
      gsap.set(task, { pointerEvents: 'auto' })
      layoutTween.to(task, { autoAlpha: 1, duration: dur }, 0)
    }
    layoutTween
      .to([track, decision].filter(Boolean), { autoAlpha: 1, y: 0, duration: dur * 0.55 }, 0)
      .fromTo(main, { scale: reduced ? 1 : 1.02 }, { scale: 1, duration: dur, clearProps: 'transform' }, 0)
  }
}

function animateResultsSurfaces() {
  const chart = forecastSurface.value
  const tuning = tuningMount.value
  const dur = motionDuration(0.6)
  if (chart) {
    // Always clear opacity/visibility so interrupted tweens cannot hide the chart.
    gsap.fromTo(
      chart,
      { autoAlpha: prefersReducedMotion() ? 1 : 0.2, y: prefersReducedMotion() ? 0 : 16 },
      {
        autoAlpha: 1,
        y: 0,
        duration: dur,
        ease: 'power3.out',
        clearProps: 'transform,opacity,visibility',
        onInterrupt: () => gsap.set(chart, { clearProps: 'transform,opacity,visibility' }),
      },
    )
  }
  if (tuning) {
    gsap.fromTo(
      tuning,
      { autoAlpha: prefersReducedMotion() ? 1 : 0.2, y: prefersReducedMotion() ? 0 : 20 },
      {
        autoAlpha: 1,
        y: 0,
        duration: dur,
        delay: 0.08,
        ease: 'power3.out',
        clearProps: 'transform,opacity,visibility',
      },
    )
  }
}

watch(focusStage, async (enter, was) => {
  await nextTick()
  if (was === undefined && !enter) return
  animateFocus(enter)
})

watch(
  () => demo.draft.basin_id,
  (id, prev) => {
    if (syncingPlanBasin) return
    if (prev && id !== prev && !demo.taskId) {
      demo.draft.model_plan_id = null
    }
  },
)

watch(
  () => [showWorkflow.value, chartForecasts.value.length, showTuning.value] as const,
  async ([workflow, forecastCount, tuning]) => {
    if (workflow) return
    await nextTick()
    if (forecastCount || tuning) animateResultsSurfaces()
  },
)

onMounted(async () => {
  timer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
  void demo.loadCaseLibrary()
  try {
    const health = await api.health()
    connected.value = health.status === 'ok'
    modelingAvailable.value = !!health.model_preparation
    hydrologistAvailable.value = !!health.hydrologist_tune
    serviceMode.value = health.mode || null
    if (health.basin_catalog) {
      try {
        basins.value = await api.listBasins()
      } catch {
        basins.value = []
      }
    }
    if (!demo.taskId) {
      demo.draft.basin_id = 'yaogu'
    }
  } catch {
    connected.value = false
  }
  const id = String(route.params.taskId || demo.taskId || '')
  if (id) {
    try {
      const task = await api.getTask(id)
      demo.draft.basin_id = task.basin_id
      demo.draft.model_plan_id = task.model_plan_id ?? null
      if (task.start_date) demo.draft.start_date = task.start_date
      if (task.end_date) demo.draft.end_date = task.end_date
      if (task.forcing_mode) demo.draft.forcing_mode = task.forcing_mode
      demo.draft.model_id = task.model_id === 'openhydronet' ? 'openhydronet' : 'xaj'
      demo.restoreTask(id)
    } catch (err) {
      demo.error = String((err as Error).message || err)
    }
  }
  await nextTick()
  if (focusStage.value) animateFocus(true)
  else if (chartForecasts.value.length || showTuning.value) animateResultsSurfaces()
})
onUnmounted(() => {
  clearInterval(timer)
  demo.stopPolling()
  layoutTween?.kill()
})
</script>

<template>
  <div class="observatory" :class="{ 'is-focus': focusStage, 'is-results': !focusStage && !!demo.results }">
    <header class="observatory-header">
      <a href="/" class="observatory-brand"><span class="brand-symbol" aria-hidden="true">≈</span><span>Hydro<span class="brand-light">Agent</span><small>水文智能体 · 课题工作台</small></span></a>
      <div class="header-caption">{{ focusStage ? '执行中' : demo.mode === 'replay' ? '案例回放' : '工作台' }}</div>
      <div class="connection"><i :class="{ online: connected }" />{{ mode }}</div>
    </header>

    <main class="observatory-grid">
      <aside ref="taskPane" class="task-pane glass-pane">
        <div class="section-heading"><span class="overline">01 / 流域与任务</span><span class="mini-icon" aria-hidden="true">↗</span></div>
        <h2>研究流域</h2>
        <p class="muted">当前固定为内置腰古资料，不能改选其它流域。</p>
        <form @submit.prevent="begin">
          <fieldset :disabled="locked">
            <label>研究流域
              <span class="locked-basin">腰古<small>yaogu · 本地日资料</small></span>
            </label>
            <p v-if="demo.draft.model_plan_id" class="basin-caption">已绑定方案：{{ demo.draft.model_plan_id }}</p>
            <p v-else-if="serviceMode === 'real'" class="basin-caption">请在右侧用本地腰古资料建立模型方案</p>
            <div class="section-heading" style="margin-top:18px"><span class="overline">02 / 预报任务</span></div>
            <div :class="{ 'is-locked': serviceMode === 'real' && !planReady }">
              <fieldset :disabled="locked || (serviceMode === 'real' && !planReady)">
              <div class="date-fields"><label>开始日期<input v-model="demo.draft.start_date" type="date" required /></label><label>结束日期<input v-model="demo.draft.end_date" type="date" :min="demo.draft.start_date" required /></label></div>
              <label>计算模型<select v-model="demo.draft.model_id"><option value="xaj">新安江 · XAJ</option><option value="openhydronet" disabled>OpenHydroNet · 尚未启用</option></select></label>
              <label>气象资料<select v-model="demo.draft.forcing_mode"><option value="R">实测日资料 · 历史率定</option><option value="F" disabled>预报资料 · 腰古暂不开放</option></select></label>
              <label class="toggle-row"><span>允许尝试改进方案</span><input v-model="demo.draft.allow_optimization" type="checkbox" role="switch" /></label>
              <button class="text-button" type="button" :aria-expanded="advanced" @click="advanced = !advanced">{{ advanced ? '收起运行设置 −' : '运行设置 +' }}</button>
              <div v-if="advanced" class="advanced-fields"><label>基础方案<input v-model="demo.draft.base_scheme_id" required /></label><label>最多决策轮次<input v-model.number="demo.draft.max_agent_decision_rounds" type="number" min="1" max="100" required /></label><label>最多改进次数<input v-model.number="demo.draft.max_optimization_cycles" type="number" min="0" max="20" required /></label></div>
              </fieldset>
            </div>
          </fieldset>
          <button v-if="!demo.run || demo.run.status === 'created'" class="start-button" :disabled="busy || !connected || (serviceMode === 'real' && !demo.draft.model_plan_id)" type="submit">{{ busy ? '正在启动…' : planReady ? '开始运行' : '请先完成建模' }}<span aria-hidden="true">↗</span></button>
          <button v-else-if="demo.run.paused && demo.mode !== 'replay'" type="button" class="start-button" :disabled="busy" @click="resume">继续计算 <span>↗</span></button>
          <button v-else-if="demo.isRunning" type="button" class="start-button" disabled>正在计算<span class="activity-dot" /></button>
          <button v-else type="button" class="start-button" @click="newTask">新建任务 <span>＋</span></button>
        </form>
        <p class="source-note">{{ demo.draft.forcing_mode === 'R' ? '使用内置腰古日资料做历史率定与检验，不代表业务预报。' : '预报资料可用性将在运行时检查。' }}</p>
        <label class="case-picker">已有案例<select aria-label="已有案例" :disabled="demo.isRunning || busy" :value="demo.mode === 'replay' ? demo.taskId : ''" @change="openCase"><option value="">{{ demo.caseLibrary.length ? '选择一份已完成记录' : '暂无已完成记录' }}</option><option v-for="task in demo.caseLibrary" :key="task.task_id" :value="task.task_id">{{ task.start_date || task.task_id }} · {{ basinLabel(task.basin_id) }}</option></select></label>
      </aside>

      <section ref="mainStage" class="main-stage" :class="{ 'main-stage--focus': focusStage, 'main-stage--results': !focusStage && !!demo.results }">
        <div class="hero-copy"><div class="overline"><span class="blue-dot" /> {{ demo.isCompleted ? '任务完成' : demo.isRunning ? '运行中' : demo.mode === 'replay' ? '案例回放' : '待命' }}</div><h1>{{ title }}</h1><p>{{ description }}</p></div>
        <LiveWorkflow
          v-if="showWorkflow"
          :action="action"
          :status="demo.run?.paused ? 'paused' : demo.run?.status"
          :completed-actions="completedActions"
          :gate-status="gateStatus"
          :expanded="focusStage"
          :workflow-version="demo.taskMeta?.workflow_version"
        />
        <ModelPreparation
          v-else-if="modelingAvailable && !demo.taskId"
          :basin-id="demo.draft.basin_id"
          :selected-id="demo.draft.model_plan_id"
          :locked="busy"
          @selected="selectPlan"
        />
        <div v-else-if="!chartForecasts.length" class="water-scene" aria-label="抽象水流地形示意，非预测数据">
          <svg viewBox="0 0 800 360" preserveAspectRatio="xMidYMid meet" aria-hidden="true"><defs><linearGradient id="terrain" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#dceefa"/><stop offset="1" stop-color="#a9c9dd"/></linearGradient><linearGradient id="river" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#75e0ee"/><stop offset=".5" stop-color="#238ef5"/><stop offset="1" stop-color="#1b57bc"/></linearGradient><filter id="shadow"><feGaussianBlur stdDeviation="14"/></filter></defs>
          <ellipse cx="416" cy="289" rx="255" ry="27" fill="#6e9cb4" opacity=".18" filter="url(#shadow)"/>
          <path d="M100 220 365 62 709 172 438 329Z" fill="#a9c4d7"/><path d="M100 203 365 45 709 155 438 312Z" fill="url(#terrain)"/>
          <g fill="none" stroke="#f4fbff" stroke-width="1.3" opacity=".7"><path v-for="n in 13" :key="n" :d="`M ${108+n*12} ${201+n*4} Q ${245+n*7} ${85+n*7}, ${358+n*12} ${111+n*5} T ${691-n*9} ${157+n*7}`" /></g>
          <path d="M363 70C277 117 504 119 424 165S284 202 436 281" fill="none" stroke="#efffff" stroke-width="25" opacity=".8"/>
          <path d="M363 70C277 117 504 119 424 165S284 202 436 281" fill="none" stroke="url(#river)" stroke-width="17"/>
          <path d="M271 121Q297 154 407 166M565 171Q513 206 380 219" fill="none" stroke="#5ebce6" stroke-width="5"/>
          <circle cx="427" cy="275" r="8" fill="white"/><circle cx="427" cy="275" r="4" fill="#007aff"/>
          </svg>
          <div class="scene-caption"><span>资料 → 计算 → 评价</span><small>示意 · 非实测地图</small></div>
        </div>
        <div v-else ref="forecastSurface" class="forecast-surface">
          <div class="chart-title"><h2>流量预报</h2><span>{{ mode }} · m³/s · {{ chartForecasts.length }} 个起报日</span></div>
          <ForecastChart :forecasts="chartForecasts" />
          <p class="chart-note">横轴为起报日期；曲线为提前 1 / 2 / 3 天预报（当前方案）。</p>
        </div>
        <div v-if="showHydrologist" class="hydrologist-mount">
          <HydrologistTune
            :plan-id="demo.draft.model_plan_id"
            :task-id="demo.taskId"
            :locked="busy || demo.isRunning"
          />
        </div>
        <div v-if="showTuning" ref="tuningMount" class="tuning-mount">
          <ParamTuningPanel
            :diagnosis="demo.results?.diagnosis"
            :optimize="demo.results?.optimize"
            :scheme="demo.results?.scheme"
          />
        </div>
        <div ref="stageTrack" class="stage-track" aria-label="执行阶段"><div v-for="(item, index) in AUDIENCE_STAGES" :key="item.id" :class="{ current: stage === item.id && demo.isRunning }"><span class="stage-number">0{{ index + 1 }}</span><strong>{{ item.label }}</strong><small class="stage-state">{{ progressLabel(progress[item.id]) }}</small><span class="stage-marker" /></div></div>
        <div ref="decisionStrip" class="decision-strip"><span class="decision-icon" aria-hidden="true">{{ demo.results?.gate ? '✓' : '◎' }}</span><div><span class="overline">{{ demo.results ? '方案判断' : '状态' }}</span><h3>{{ demo.results ? gate.title : '尚未运行' }}</h3><p>{{ demo.results ? gate.reason : '运行后，这里显示 Gate 结论与依据。' }}</p></div><button v-if="demo.taskId" class="refresh-button" aria-label="刷新结果" @click="demo.refresh()">↻</button></div>
      </section>

      <aside ref="journalPane" class="journal-pane glass-pane"><div class="section-heading"><span class="overline">02 / 执行记录</span><span class="record-count">{{ demo.timeline.length }}</span></div><h2>执行记录</h2><div class="journal-status"><span :class="{ 'blue-dot': demo.isRunning }">{{ demo.isRunning ? '运行中' : demo.isCompleted ? '已完成' : demo.isFailed ? '已受阻' : '等待执行' }}</span><span>{{ elapsed }}</span></div>
        <div v-if="error" class="inline-error" role="alert"><strong>暂时无法继续</strong><p>{{ error }}</p><button v-if="demo.taskId" class="text-button" @click="demo.refresh()">重新读取状态</button></div>
        <div class="journal-list"><div v-if="!events.length" class="journal-empty"><span aria-hidden="true">⌁</span><h3>等待第一条记录</h3><p>开始后，这里会记录系统做了什么，以及得到了什么。</p></div><details v-for="(event, index) in events" :key="event.id" class="journal-event"><summary><span class="event-dot" :class="{ failed: ['failed', 'error'].includes(event.status) }" /><span><small>{{ String(events.length - index).padStart(2, '0') }} · {{ eventStatus(event.status) }}</small><strong>{{ event.label || actionTitle(event.action) }}</strong></span><span class="expand-icon">＋</span></summary><pre>{{ JSON.stringify(event.details, null, 2) }}</pre></details></div>
        <div class="report-area"><span class="overline">结果与报告</span><template v-if="reports.length"><a v-for="name in reports" :key="name" :href="`/api/tasks/${encodeURIComponent(demo.taskId || '')}/report/${encodeURIComponent(name)}`" target="_blank" rel="noreferrer">{{ name }} <span>↗</span></a></template><p v-else>{{ demo.isCompleted ? '尚未取得报告，可刷新结果重试。' : '运行完成后，可在这里打开报告。' }}</p></div>
      </aside>
    </main>
    <footer class="observatory-footer"><span>HYDRO-AGENT <span class="footer-divider">/</span> 课题工作台</span><span>新安江模型 · 可追溯执行</span></footer>
  </div>
</template>

<style src="../observatory.css"></style>
