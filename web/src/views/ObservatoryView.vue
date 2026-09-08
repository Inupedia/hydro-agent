<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import ForecastChart from '../components/ForecastChart.vue'
import { useDemoStore } from '../stores/demo'
import { api } from '../api/client'
import { AUDIENCE_STAGES, actionTitle, actionExplain, basinLabel, gateDecisionZh, stageForAction, stageStatuses } from '../demo/stages'

const demo = useDemoStore()
const route = useRoute()
const busy = ref(false)
const serviceMode = ref<string | null>(null)
const connected = ref(false)
const now = ref(Date.now())
const advanced = ref(false)
let timer: number | undefined
const locked = computed(() => busy.value || !!demo.taskId)
const action = computed(() => demo.run?.llm_decision_action || demo.run?.last_action || demo.timeline.at(-1)?.action)
const stage = computed(() => stageForAction(action.value))
const progress = computed(() => stageStatuses(demo.timeline.filter(t => !['failed', 'error', 'skipped'].includes(t.status)).map(t => t.action || ''), action.value || null, demo.isCompleted ? 'completed' : demo.run?.status || null))
const progressLabel = (status: string) => ({ pending: '待开始', active: '进行中', done: '已完成', skipped: '未执行', blocked: '已受阻' }[status] || '')
const gate = computed(() => gateDecisionZh(typeof demo.results?.gate?.status === 'string' ? demo.results.gate.status : null))
const mode = computed(() => demo.mode === 'replay' ? '历史记录' : serviceMode.value === 'real' ? '真实计算' : serviceMode.value ? '模拟演示' : '连接待确认')
const title = computed(() => demo.isFailed ? '本次计算暂时受阻' : demo.isCompleted ? '一次预测，有据可循。' : demo.isRunning ? actionTitle(action.value) : demo.run?.paused ? '计算已暂停' : '看见水流的下一程。')
const description = computed(() => demo.isFailed ? '查看右侧记录，了解计算停在哪一步。' : demo.isCompleted ? '计算与判断留在同一画面，每个结果都有来处。' : demo.isRunning ? actionExplain(action.value) : '从资料检查到流量预测，让复杂的计算过程清晰可见。')
const elapsed = computed(() => {
  if (!demo.startedAt || demo.isCompleted || demo.isFailed) return demo.isCompleted ? '已结束' : '等待开始'
  const seconds = Math.max(0, Math.floor((now.value - demo.startedAt) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
})
const eventStatus = (status: string) => ({ succeeded: '已完成', completed: '已完成', success: '已完成', running: '进行中', failed: '失败', error: '失败', skipped: '已跳过' }[status] || '执行记录')
const events = computed(() => [...demo.timeline].reverse())
const reports = computed(() => demo.results?.report_artifacts || [])
const error = computed(() => demo.error || demo.run?.llm_error)

async function begin() {
  busy.value = true
  try {
    if (!demo.taskId) await demo.createTaskFromDraft()
    await demo.startRun()
  } catch (err) { demo.error = String((err as Error).message || err) }
  finally { busy.value = false }
}
async function resume() {
  busy.value = true
  try { await demo.resumeCompute() }
  catch (err) { demo.error = String((err as Error).message || err) }
  finally { busy.value = false }
}
async function openCase(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  const task = demo.caseLibrary.find(t => t.task_id === id)
  if (task) await demo.openCaseReplay(task)
}
function newTask() {
  demo.resetSession()
  history.replaceState(null, '', '/')
}
onMounted(async () => {
  timer = window.setInterval(() => { now.value = Date.now() }, 1000)
  void demo.loadCaseLibrary()
  try { const health = await api.health(); connected.value = health.status === 'ok'; serviceMode.value = health.mode || null }
  catch { connected.value = false }
  const id = String(route.params.taskId || demo.taskId || '')
  if (id) {
    try {
      const task = await api.getTask(id)
      demo.draft.basin_id = task.basin_id
      if (task.start_date) demo.draft.start_date = task.start_date
      if (task.end_date) demo.draft.end_date = task.end_date
      if (task.forcing_mode) demo.draft.forcing_mode = task.forcing_mode
      demo.draft.model_id = task.model_id === 'openhydronet' ? 'openhydronet' : 'xaj'
      demo.restoreTask(id)
    } catch (err) { demo.error = String((err as Error).message || err) }
  }
})
onUnmounted(() => { clearInterval(timer); demo.stopPolling() })
</script>

<template>
  <div class="observatory">
    <header class="observatory-header">
      <a href="/" class="observatory-brand"><span class="brand-symbol" aria-hidden="true">≈</span><span>Hydro<span class="brand-light">Agent</span><small>水文智能体 · 演示空间</small></span></a>
      <div class="header-caption">理解过程，看见结果</div>
      <div class="connection"><i :class="{ online: connected }" />{{ mode }}</div>
    </header>

    <main class="observatory-grid">
      <aside class="task-pane glass-pane">
        <div class="section-heading"><span class="overline">01 / 预报任务</span><span class="mini-icon" aria-hidden="true">↗</span></div>
        <h2>从一个流域开始</h2>
        <p class="muted">设定目标，剩下的交给系统。</p>
        <form @submit.prevent="begin">
          <fieldset :disabled="locked">
            <label>研究流域<input v-model="demo.draft.basin_id" required aria-label="研究流域" /></label>
            <p class="basin-caption">{{ basinLabel(demo.draft.basin_id) }}</p>
            <div class="date-fields"><label>开始日期<input v-model="demo.draft.start_date" type="date" required /></label><label>结束日期<input v-model="demo.draft.end_date" type="date" :min="demo.draft.start_date" required /></label></div>
            <label>计算模型<select v-model="demo.draft.model_id"><option value="xaj">新安江 · XAJ</option><option value="openhydronet" disabled>OpenHydroNet · 尚未启用</option></select></label>
            <label>气象资料<select v-model="demo.draft.forcing_mode"><option value="R">实测资料 · 历史检验</option><option value="F">预报资料 · 预测计算</option></select></label>
            <label class="toggle-row"><span>允许尝试改进方案</span><input v-model="demo.draft.allow_optimization" type="checkbox" role="switch" /></label>
            <button class="text-button" type="button" :aria-expanded="advanced" @click="advanced = !advanced">{{ advanced ? '收起运行设置 −' : '运行设置 +' }}</button>
            <div v-if="advanced" class="advanced-fields"><label>基础方案<input v-model="demo.draft.base_scheme_id" required /></label><label>最多决策轮次<input v-model.number="demo.draft.max_agent_decision_rounds" type="number" min="1" max="100" required /></label><label>最多改进次数<input v-model.number="demo.draft.max_optimization_cycles" type="number" min="0" max="20" required /></label></div>
          </fieldset>
          <button v-if="!demo.run || demo.run.status === 'created'" class="start-button" :disabled="busy || !connected" type="submit">{{ busy ? '正在启动…' : '开始运行' }}<span aria-hidden="true">↗</span></button>
          <button v-else-if="demo.run.paused && demo.mode !== 'replay'" type="button" class="start-button" :disabled="busy" @click="resume">继续计算 <span>↗</span></button>
          <button v-else-if="demo.isRunning" type="button" class="start-button" disabled>正在计算<span class="activity-dot" /></button>
          <button v-else type="button" class="start-button" @click="newTask">新建任务 <span>＋</span></button>
        </form>
        <p class="source-note">{{ demo.draft.forcing_mode === 'R' ? '使用历史实测资料检验，不代表当前业务预报。' : '预报资料可用性将在运行时检查。' }}</p>
        <label class="case-picker">已有案例<select aria-label="已有案例" :disabled="demo.isRunning || busy" :value="demo.mode === 'replay' ? demo.taskId : ''" @change="openCase"><option value="">{{ demo.caseLibrary.length ? '选择一份已完成记录' : '暂无已完成记录' }}</option><option v-for="task in demo.caseLibrary" :key="task.task_id" :value="task.task_id">{{ task.start_date || task.task_id }} · {{ basinLabel(task.basin_id) }}</option></select></label>
      </aside>

      <section class="main-stage">
        <div class="hero-copy"><div class="overline"><span class="blue-dot" /> {{ demo.isCompleted ? '计算已完成' : demo.isRunning ? '智能体正在工作' : 'HYDROLOGY, MADE VISIBLE' }}</div><h1>{{ title }}</h1><p>{{ description }}</p></div>
        <div class="water-scene" v-if="!demo.results?.forecasts.length" aria-label="抽象水流地形示意，非预测数据">
          <svg viewBox="0 0 800 360" preserveAspectRatio="xMidYMid meet" aria-hidden="true"><defs><linearGradient id="terrain" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#dceefa"/><stop offset="1" stop-color="#a9c9dd"/></linearGradient><linearGradient id="river" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#75e0ee"/><stop offset=".5" stop-color="#238ef5"/><stop offset="1" stop-color="#1b57bc"/></linearGradient><filter id="shadow"><feGaussianBlur stdDeviation="14"/></filter></defs>
          <ellipse cx="416" cy="289" rx="255" ry="27" fill="#6e9cb4" opacity=".18" filter="url(#shadow)"/>
          <path d="M100 220 365 62 709 172 438 329Z" fill="#a9c4d7"/><path d="M100 203 365 45 709 155 438 312Z" fill="url(#terrain)"/>
          <g fill="none" stroke="#f4fbff" stroke-width="1.3" opacity=".7"><path v-for="n in 13" :key="n" :d="`M ${108+n*12} ${201+n*4} Q ${245+n*7} ${85+n*7}, ${358+n*12} ${111+n*5} T ${691-n*9} ${157+n*7}`" /></g>
          <path d="M363 70C277 117 504 119 424 165S284 202 436 281" fill="none" stroke="#efffff" stroke-width="25" opacity=".8"/>
          <path d="M363 70C277 117 504 119 424 165S284 202 436 281" fill="none" stroke="url(#river)" stroke-width="17"/>
          <path d="M271 121Q297 154 407 166M565 171Q513 206 380 219" fill="none" stroke="#5ebce6" stroke-width="5"/>
          <circle cx="427" cy="275" r="8" fill="white"/><circle cx="427" cy="275" r="4" fill="#007aff"/>
          </svg>
          <div class="scene-caption"><span>资料 → 计算 → 判断</span><small>水流地形示意 · 非实测地图</small></div>
        </div>
        <div v-else class="forecast-surface"><div class="chart-title"><h2>流量预测</h2><span>{{ mode }} · m³/s</span></div><ForecastChart :forecasts="demo.results.forecasts" /><p class="chart-note">横轴为起报日期，各曲线代表提前 1、2、3 天的预测。</p></div>
        <div class="stage-track" aria-label="执行阶段"><div v-for="(item, index) in AUDIENCE_STAGES" :key="item.id" :class="{ current: stage === item.id && demo.isRunning }"><span class="stage-number">0{{ index + 1 }}</span><strong>{{ item.label }}</strong><small class="stage-state">{{ progressLabel(progress[item.id]) }}</small><span class="stage-marker" /></div></div>
        <div class="decision-strip"><span class="decision-icon" aria-hidden="true">{{ demo.results?.gate ? '✓' : '◎' }}</span><div><span class="overline">{{ demo.results ? '本次方案判断' : '让每一步，都有依据' }}</span><h3>{{ demo.results ? gate.title : '系统执行，过程可见' }}</h3><p>{{ demo.results ? gate.reason : '检查资料、计算流量、比较方案，并保留执行记录。' }}</p></div><button v-if="demo.taskId" class="refresh-button" aria-label="刷新结果" @click="demo.refresh()">↻</button></div>
      </section>

      <aside class="journal-pane glass-pane"><div class="section-heading"><span class="overline">02 / 执行记录</span><span class="record-count">{{ demo.timeline.length }}</span></div><h2>每一步，都看得见</h2><div class="journal-status"><span :class="{ 'blue-dot': demo.isRunning }">{{ demo.isRunning ? '运行中' : demo.isCompleted ? '已完成' : demo.isFailed ? '已受阻' : '等待执行' }}</span><span>{{ elapsed }}</span></div>
        <div v-if="error" class="inline-error" role="alert"><strong>暂时无法继续</strong><p>{{ error }}</p><button v-if="demo.taskId" class="text-button" @click="demo.refresh()">重新读取状态</button></div>
        <div class="journal-list"><div v-if="!events.length" class="journal-empty"><span aria-hidden="true">⌁</span><h3>等待第一条记录</h3><p>开始后，这里会记录系统做了什么，以及得到了什么。</p></div><details v-for="(event, index) in events" :key="event.id" class="journal-event"><summary><span class="event-dot" :class="{ failed: ['failed', 'error'].includes(event.status) }" /><span><small>{{ String(events.length - index).padStart(2, '0') }} · {{ eventStatus(event.status) }}</small><strong>{{ event.label || actionTitle(event.action) }}</strong></span><span class="expand-icon">＋</span></summary><pre>{{ JSON.stringify(event.details, null, 2) }}</pre></details></div>
        <div class="report-area"><span class="overline">结果与报告</span><template v-if="reports.length"><a v-for="name in reports" :key="name" :href="`/api/tasks/${encodeURIComponent(demo.taskId || '')}/report/${encodeURIComponent(name)}`" target="_blank" rel="noreferrer">{{ name }} <span>↗</span></a></template><p v-else>{{ demo.isCompleted ? '尚未取得报告，可刷新结果重试。' : '运行完成后，可在这里打开报告。' }}</p></div>
      </aside>
    </main>
    <footer class="observatory-footer"><span>HYDRO-AGENT <span class="footer-divider">/</span> 从资料到结果</span><span>新安江模型 · 可追溯执行</span></footer>
  </div>
</template>

<style src="../observatory.css"></style>
