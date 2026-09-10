<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client'
import CalibrationComparisonChart from '../components/CalibrationComparisonChart.vue'
import LiveWorkflow from '../components/LiveWorkflow.vue'
import ModelPreparation from '../components/ModelPreparation.vue'
import ReportLinks from '../components/ReportLinks.vue'
import { useDemoStore } from '../stores/demo'
import type { BasinInfo, ModelPlan } from '../types/api'

const demo = useDemoStore()
const route = useRoute()
const basins = ref<BasinInfo[]>([])
const connected = ref(false)
const serviceMode = ref<string | null>(null)
const busy = ref(false)
const selectedPlan = ref<ModelPlan | null>(null)
const now = ref(Date.now())
let timer: number | undefined

const action = computed(() => demo.run?.llm_decision_action || demo.run?.last_action || demo.timeline.at(-1)?.action || null)
const completedActions = computed(() =>
  demo.timeline
    .filter((item) => item.action && !['failed', 'error', 'running'].includes(item.status))
    .map((item) => item.action as string),
)
const planReady = computed(() => !!demo.draft.model_plan_id)
const result = computed(() => demo.results)
const comparison = computed(() => result.value?.comparison || [])
const metrics = computed(() => result.value?.metrics || {})
const elapsed = computed(() => {
  if (!demo.startedAt) return '—'
  if (demo.isCompleted) return '已完成'
  const seconds = Math.max(0, Math.floor((now.value - demo.startedAt) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
})
const stateTitle = computed(() => {
  if (demo.isFailed) return '本次率定受阻'
  if (demo.isCompleted) return '率定与独立测试完成'
  if (demo.isRunning) return '水文智能体正在率定'
  if (planReady.value) return '模型已就绪，可以开始自动率定'
  return '先建立流域模型'
})
const stateDescription = computed(() => {
  if (demo.isCompleted) return '主结果只展示冻结方案在最终独立测试集上的表现；率定过程保留在右侧审计记录。'
  if (demo.isRunning) return 'Agent 按“先水量、后过程；先分解、后整体；先模块、后系统”自动诊断、试验、Gate 与回退。'
  if (planReady.value) return '系统会自动分配率定集、开发验证集和封存测试集，不需要手工挑年份或手工调参。'
  return '选择流域与集总/分布式结构，准备长期历史资料并复核边界。'
})

function selectPlan(plan: ModelPlan | null) {
  if (demo.taskId) return
  selectedPlan.value = plan
  demo.draft.model_plan_id = plan?.plan_id || null
  if (!plan) return
  demo.draft.basin_id = plan.basin_id
  demo.draft.model_mode = plan.model_mode || 'lumped'
  demo.draft.model_id = 'xaj'
  demo.draft.forcing_mode = 'R'
  demo.draft.allow_optimization = true
  demo.draft.max_agent_decision_rounds = 100
  demo.draft.max_optimization_cycles = 20
  if (plan.suggested_start) demo.draft.start_date = plan.suggested_start
  if (plan.suggested_end) demo.draft.end_date = plan.suggested_end
}

async function begin() {
  if (!planReady.value) return
  busy.value = true
  demo.error = null
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
  } finally {
    busy.value = false
  }
}

function newTask() {
  demo.resetSession()
  selectedPlan.value = null
  history.replaceState(null, '', '/')
}

function formatMetric(value: number | null | undefined, digits = 3) {
  return value == null || !Number.isFinite(value) ? '—' : Number(value).toFixed(digits)
}

onMounted(async () => {
  timer = window.setInterval(() => (now.value = Date.now()), 1000)
  try {
    const health = await api.health()
    connected.value = health.status === 'ok'
    serviceMode.value = health.mode || null
    if (health.basin_catalog) basins.value = await api.listBasins()
  } catch {
    connected.value = false
  }
  void demo.loadCaseLibrary()

  const taskId = String(route.params.taskId || demo.taskId || '')
  if (taskId) {
    try {
      const task = await api.getTask(taskId)
      demo.draft.basin_id = task.basin_id
      demo.draft.model_id = task.model_id === 'openhydronet' ? 'openhydronet' : 'xaj'
      demo.draft.model_mode = task.model_mode || 'lumped'
      demo.draft.model_plan_id = task.model_plan_id || null
      if (task.start_date) demo.draft.start_date = task.start_date
      if (task.end_date) demo.draft.end_date = task.end_date
      demo.restoreTask(taskId)
    } catch (err) {
      demo.error = String((err as Error).message || err)
    }
  }
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  demo.stopPolling()
})
</script>

<template>
  <div class="workspace">
    <header class="topbar">
      <a class="brand" href="/">Hydro<span>Agent</span><small>水文预报方案构建与参数优化</small></a>
      <div class="connection"><i :class="{ online: connected }" />{{ connected ? (serviceMode === 'real' ? '真实计算' : '演示模式') : '未连接' }}</div>
    </header>

    <main class="layout">
      <aside class="left panel">
        <div class="section-title"><span>01</span><strong>流域</strong></div>
        <label v-if="!demo.taskId">研究流域
          <select v-model="demo.draft.basin_id" :disabled="!!demo.draft.model_plan_id">
            <option v-for="basin in basins" :key="basin.basin_id" :value="basin.basin_id">
              {{ basin.label }}{{ basin.ready_for_build ? '' : ' · 待下载' }}
            </option>
            <option v-if="!basins.length" value="usgs_02472000">Leaf River near Collins (MS)</option>
          </select>
        </label>
        <div v-else class="locked-value">
          <strong>{{ demo.draft.basin_id }}</strong>
          <span>{{ demo.draft.model_mode === 'distributed' ? '分布式 XAJ' : '集总式 XAJ' }}</span>
        </div>

        <div class="rule-card">
          <span>数据协议</span>
          <strong>长期历史 → 自动分割</strong>
          <p>Calibration / Development / Final Holdout 由系统按水文年和洪水事件自动规划。</p>
        </div>

        <div class="rule-card">
          <span>率定原则</span>
          <strong>先水量，后过程</strong>
          <p>水量平衡 → 退水与水源分解 → 洪水演算 → 联合收口 → 独立验证。</p>
        </div>

        <button v-if="!demo.taskId" class="primary" :disabled="busy || !connected || !planReady" @click="begin">
          {{ planReady ? '开始自动率定' : '请先完成模型准备' }}
        </button>
        <button v-else-if="demo.run?.paused && demo.mode !== 'replay'" class="primary" :disabled="busy" @click="resume">继续率定</button>
        <button v-else-if="demo.isRunning" class="primary" disabled>Agent 正在工作…</button>
        <button v-else class="secondary" @click="newTask">新建任务</button>

        <p v-if="demo.error" class="error">{{ demo.error }}</p>
      </aside>

      <section class="main panel">
        <div class="hero">
          <span class="eyebrow">{{ demo.isCompleted ? 'FINAL HOLDOUT' : demo.isRunning ? 'AUTOMATIC CALIBRATION' : 'MODEL PREPARATION' }}</span>
          <h1>{{ stateTitle }}</h1>
          <p>{{ stateDescription }}</p>
        </div>

        <ModelPreparation
          v-if="!demo.taskId"
          :basin-id="demo.draft.basin_id"
          :selected-id="demo.draft.model_plan_id"
          :locked="busy"
          @selected="selectPlan"
        />

        <template v-else-if="demo.isCompleted && result">
          <div class="result-head">
            <div>
              <span class="eyebrow">独立测试结果</span>
              <h2>Observed vs Calibrated</h2>
            </div>
            <span class="scope">{{ result.comparison_scope === 'final_holdout' ? 'Final Holdout · 未参与率定' : result.comparison_scope }}</span>
          </div>
          <div class="kpis">
            <div><span>NSE</span><strong>{{ formatMetric(metrics.NSE) }}</strong></div>
            <div><span>KGE</span><strong>{{ formatMetric(metrics.KGE) }}</strong></div>
            <div><span>Bias</span><strong>{{ formatMetric(metrics.Bias) }}</strong></div>
            <div><span>MAE</span><strong>{{ formatMetric(metrics.MAE) }}</strong></div>
          </div>
          <CalibrationComparisonChart :points="comparison" :show-initial="true" />
          <p class="result-note">黑线为实测，蓝线为率定后冻结方案；灰色虚线仅用于观察相对初始方案的改进。最终测试集不参与 Agent 的参数选择。</p>
          <ReportLinks :task-id="demo.taskId" :artifacts="result.report_artifacts" />
        </template>

        <template v-else>
          <LiveWorkflow
            :action="action"
            :status="demo.run?.paused ? 'paused' : demo.run?.status"
            :completed-actions="completedActions"
            :gate-status="typeof demo.results?.gate?.status === 'string' ? demo.results.gate.status : null"
            :expanded="true"
          />
          <div class="protocol">
            <div><b>P2</b><span>水量平衡</span></div>
            <div><b>P3</b><span>退水 / 水源</span></div>
            <div><b>P4</b><span>洪水演算</span></div>
            <div><b>P5</b><span>联合优化</span></div>
            <div><b>P6</b><span>开发验证</span></div>
            <div><b>P7</b><span>最终封存测试</span></div>
          </div>
        </template>
      </section>

      <aside class="right panel">
        <div class="section-title"><span>02</span><strong>Agent 审计</strong><small>{{ elapsed }}</small></div>
        <p class="audit-intro">这里记录 Agent 为什么继续、回滚、换阶段或停止；不是给用户手工改参数的第二套入口。</p>
        <div class="events">
          <article v-for="item in [...demo.timeline].reverse()" :key="item.id">
            <i :data-status="item.status" />
            <div><strong>{{ item.label }}</strong><span>{{ item.action || item.status }}</span></div>
          </article>
          <p v-if="!demo.timeline.length" class="empty">尚无执行记录。</p>
        </div>
        <details v-if="demo.run?.llm_text">
          <summary>查看当前智能体推理摘要输出</summary>
          <pre>{{ demo.run.llm_text }}</pre>
        </details>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.workspace{min-height:100vh;background:#f5f7f9;color:var(--label)}.topbar{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;background:rgba(255,255,255,.86);border-bottom:1px solid var(--separator);backdrop-filter:blur(18px)}.brand{font-weight:700;text-decoration:none;color:var(--label);font-size:18px}.brand>span{font-weight:400}.brand small{display:block;font-weight:400;font-size:10px;color:var(--tertiary)}.connection{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--secondary)}.connection i{width:7px;height:7px;border-radius:50%;background:#aaa}.connection i.online{background:var(--success)}
.layout{display:grid;grid-template-columns:250px minmax(0,1fr) 280px;gap:14px;padding:14px;max-width:1680px;margin:auto}.panel{background:var(--surface);border:1px solid var(--separator);border-radius:16px;box-shadow:var(--shadow)}.left,.right{padding:18px;height:calc(100vh - 94px);overflow:auto}.main{padding:20px;min-height:calc(100vh - 94px);overflow:hidden}.section-title{display:flex;align-items:center;gap:8px;margin-bottom:18px}.section-title>span{font-size:10px;color:var(--blue)}.section-title strong{font-size:12px}.section-title small{margin-left:auto;color:var(--tertiary)}label{display:grid;gap:7px;font-size:12px}select{padding:10px;border:1px solid var(--separator);border-radius:8px;background:white}.locked-value{display:grid;gap:4px;padding:10px;background:#fafafa;border-radius:9px}.locked-value span{font-size:11px;color:var(--secondary)}
.rule-card{margin-top:12px;padding:12px;border:1px solid var(--separator);border-radius:10px}.rule-card>span,.eyebrow{font-size:10px;letter-spacing:.08em;color:var(--blue);text-transform:uppercase}.rule-card strong{display:block;margin:5px 0;font-size:13px}.rule-card p,.audit-intro,.result-note{font-size:11px;line-height:1.55;color:var(--secondary);margin:0}.primary,.secondary{width:100%;margin-top:14px;border:0;border-radius:9px;padding:11px;font-weight:650;cursor:pointer}.primary{background:var(--blue);color:white}.secondary{background:#eef1f4;color:var(--label)}button:disabled{opacity:.45;cursor:default}.error{font-size:12px;color:var(--danger)}
.hero{padding:8px 4px 20px}.hero h1{font-size:30px;margin:8px 0;letter-spacing:-.03em}.hero p{margin:0;max-width:760px;color:var(--secondary);line-height:1.55}.result-head{display:flex;justify-content:space-between;align-items:end;margin:12px 0}.result-head h2{margin:5px 0 0;font-size:22px}.scope{font-size:11px;padding:6px 9px;background:var(--success-soft);border-radius:99px}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0 20px}.kpis div{padding:12px;border:1px solid var(--separator);border-radius:10px}.kpis span{font-size:10px;color:var(--secondary)}.kpis strong{display:block;font-size:23px;margin-top:4px}.result-note{margin:10px 0 18px}.protocol{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-top:16px}.protocol div{display:grid;gap:3px;padding:10px;border:1px solid var(--separator);border-radius:8px}.protocol b{font-size:10px;color:var(--blue)}.protocol span{font-size:11px}
.events{display:grid;gap:2px}.events article{display:grid;grid-template-columns:12px 1fr;gap:7px;padding:8px 0;border-bottom:1px solid var(--separator)}.events i{width:7px;height:7px;border-radius:50%;margin-top:4px;background:#bbb}.events i[data-status='succeeded'],.events i[data-status='completed']{background:var(--success)}.events i[data-status='running']{background:var(--blue)}.events div{display:grid;gap:2px}.events strong{font-size:11px}.events span{font-size:10px;color:var(--tertiary)}.empty{font-size:11px;color:var(--tertiary)}details{margin-top:16px}summary{font-size:11px;cursor:pointer;color:var(--secondary)}pre{font-size:10px;white-space:pre-wrap;background:#111;color:#d7e0e8;padding:10px;border-radius:8px;max-height:260px;overflow:auto}
@media(max-width:1100px){.layout{grid-template-columns:220px 1fr}.right{grid-column:1/-1;height:auto}.protocol{grid-template-columns:repeat(3,1fr)}}@media(max-width:760px){.layout{grid-template-columns:1fr}.left,.right{height:auto}.kpis{grid-template-columns:repeat(2,1fr)}.protocol{grid-template-columns:repeat(2,1fr)}}
</style>
