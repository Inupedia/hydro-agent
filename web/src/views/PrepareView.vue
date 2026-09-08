<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import DemoShell from '../layouts/DemoShell.vue'
import { useDemoStore } from '../stores/demo'
import { basinLabel } from '../demo/stages'
import type { TaskSummary } from '../types/api'

const demo = useDemoStore()
const router = useRouter()
const showAdvanced = ref(false)
const busy = ref(false)
const localError = ref<string | null>(null)

onMounted(() => {
  void demo.checkConditions()
  void demo.loadCaseLibrary()
})

async function enterDemo() {
  localError.value = null
  if (demo.draft.end_date < demo.draft.start_date) {
    localError.value = '结束日期不能早于开始日期'
    return
  }
  if (demo.conditions.service === 'fail') {
    localError.value = '服务不可用，请先恢复连接后再进入演示'
    return
  }
  busy.value = true
  try {
    await demo.createTaskFromDraft()
    await router.push({ name: 'briefing', params: { taskId: demo.taskId! } })
  } catch (err) {
    localError.value = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}

async function enterCase(task: TaskSummary) {
  localError.value = null
  busy.value = true
  try {
    await demo.openCaseReplay(task)
    await router.push({ name: 'briefing', params: { taskId: task.task_id } })
  } catch (err) {
    localError.value = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}

function statusZh(status: string) {
  if (status === 'completed') return '已完成'
  if (status === 'failed' || status === 'error') return '失败'
  if (status === 'paused') return '已暂停'
  if (status === 'running') return '运行中'
  return status
}
</script>

<template>
  <DemoShell task-summary="任务准备">
    <section class="prepare">
      <header class="hero-copy">
        <h1>设置本次演示任务</h1>
        <p class="lede">确认流域与日期后进入演示；计算由开场页「开始运行」触发。</p>
      </header>

      <div class="grid">
        <form class="panel" @submit.prevent="enterDemo">
          <h2>基础设置</h2>

          <div class="field">
            <span class="key">流域</span>
            <div class="val">
              <select v-model="demo.draft.basin_id" required>
                <option value="camels_13235000">Lowman（Snake River 支流）</option>
              </select>
              <small>{{ demo.draft.basin_id }}</small>
            </div>
          </div>

          <div class="field">
            <span class="key">模型</span>
            <div class="val">
              <select v-model="demo.draft.model_id">
                <option value="xaj">新安江（XAJ）</option>
                <option value="openhydronet" disabled>OpenHydroNet（未启用）</option>
              </select>
            </div>
          </div>

          <div class="field">
            <span class="key">日期</span>
            <div class="val dates">
              <input v-model="demo.draft.start_date" type="date" required />
              <span class="sep">至</span>
              <input v-model="demo.draft.end_date" type="date" required />
            </div>
          </div>

          <div class="field">
            <span class="key">资料</span>
            <div class="val">
              <select v-model="demo.draft.forcing_mode">
                <option value="R">实测气象驱动资料</option>
                <option value="F">预报气象驱动资料</option>
              </select>
            </div>
          </div>

          <div class="field">
            <span class="key">改进</span>
            <label class="check val">
              <input v-model="demo.draft.allow_optimization" type="checkbox" />
              允许尝试调整参数
            </label>
          </div>

          <button type="button" class="text-btn" @click="showAdvanced = !showAdvanced">
            {{ showAdvanced ? '收起高级设置' : '高级设置' }}
          </button>

          <template v-if="showAdvanced">
            <div class="field">
              <span class="key">基础方案</span>
              <div class="val">
                <input v-model="demo.draft.base_scheme_id" required />
              </div>
            </div>
            <div class="field">
              <span class="key">限制</span>
              <div class="val dates">
                <input
                  v-model.number="demo.draft.max_agent_decision_rounds"
                  type="number"
                  min="1"
                  max="20"
                  title="最大决策轮次"
                />
                <span class="sep">轮 /</span>
                <input
                  v-model.number="demo.draft.max_optimization_cycles"
                  type="number"
                  min="0"
                  max="4"
                  title="最大改进次数"
                />
                <span class="sep">次</span>
              </div>
            </div>
          </template>

          <p v-if="localError" class="error">{{ localError }}</p>
          <div class="actions">
            <button class="primary" type="submit" :disabled="busy">
              {{ busy ? '正在进入…' : '进入演示' }}
            </button>
          </div>
        </form>

        <aside class="side">
          <div class="panel conditions">
            <div class="cond-head">
              <h2>运行条件</h2>
              <button type="button" class="ghost" @click="demo.checkConditions()">重新检查</button>
            </div>
            <ul>
              <li :data-state="demo.conditions.service">
                <strong>服务</strong>
                <span>{{ demo.conditions.serviceDetail }}</span>
              </li>
              <li :data-state="demo.conditions.source">
                <strong>资料</strong>
                <span>{{ demo.conditions.sourceDetail }}</span>
              </li>
              <li :data-state="demo.conditions.model">
                <strong>模型</strong>
                <span>{{ demo.conditions.modelDetail }}</span>
              </li>
            </ul>
          </div>

          <div class="panel cases">
            <div class="cond-head">
              <h2>历史案例</h2>
              <button type="button" class="ghost" @click="demo.loadCaseLibrary()">刷新</button>
            </div>
            <ul v-if="demo.caseLibrary.length" class="case-list">
              <li v-for="task in demo.caseLibrary" :key="task.task_id">
                <div>
                  <strong>{{ basinLabel(task.basin_id) }}</strong>
                  <span>{{ task.start_date || '—' }} · {{ statusZh(task.status) }}</span>
                </div>
                <button type="button" class="ghost" :disabled="busy" @click="enterCase(task)">
                  回放
                </button>
              </li>
            </ul>
            <p v-else class="note">暂无可用完成案例。</p>
          </div>
        </aside>
      </div>
    </section>
  </DemoShell>
</template>

<style scoped>
.prepare {
  max-width: 860px;
  margin: 0 auto;
}
h1 {
  margin: 0;
  font-size: 22px;
  letter-spacing: -0.02em;
  font-weight: 650;
}
.lede {
  margin: 0.35rem 0 0.85rem;
  color: var(--secondary);
  font-size: 13px;
}
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr);
  gap: 0.75rem;
  align-items: start;
}
.side {
  display: grid;
  gap: 0.75rem;
}
.panel {
  background: var(--surface);
  border: 1px solid var(--separator);
  border-radius: 12px;
  padding: 0.7rem 0.8rem;
  box-shadow: var(--shadow);
  display: grid;
  gap: 0.35rem;
}
h2 {
  margin: 0 0 0.2rem;
  font-size: 13px;
  font-weight: 650;
}
.field {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 0.55rem;
  align-items: center;
  min-height: 32px;
}
.key {
  color: var(--secondary);
  font-size: 12px;
  font-weight: 550;
}
.val {
  display: grid;
  gap: 0.15rem;
  min-width: 0;
}
.val.dates {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.sep {
  color: var(--tertiary);
  font-size: 12px;
  flex: 0 0 auto;
}
input,
select {
  height: 28px;
  min-height: 28px;
  border-radius: 6px;
  border: 1px solid var(--separator);
  padding: 0 0.45rem;
  background: #fff;
  color: var(--label);
  font-size: 12px;
  width: 100%;
  max-width: 260px;
}
.dates input {
  max-width: 118px;
  flex: 1 1 auto;
}
.dates input[type='number'] {
  max-width: 64px;
}
small {
  color: var(--tertiary);
  font-size: 11px;
}
.check {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 12px;
  color: var(--label);
  margin: 0;
}
.check input {
  width: 13px;
  height: 13px;
  min-height: 0;
  max-width: none;
  padding: 0;
}
.actions {
  display: flex;
  margin-top: 0.35rem;
}
.primary {
  appearance: none;
  border: 0;
  height: 30px;
  padding: 0 0.9rem;
  border-radius: 6px;
  background: var(--blue);
  color: #fff;
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
}
.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.text-btn {
  appearance: none;
  border: 0;
  background: transparent;
  color: var(--blue);
  font-size: 12px;
  font-weight: 550;
  cursor: pointer;
  justify-self: start;
  padding: 0.15rem 0;
}
.ghost {
  appearance: none;
  border: 0;
  height: 24px;
  padding: 0 0.5rem;
  border-radius: 5px;
  background: rgba(120, 120, 128, 0.1);
  color: var(--label);
  font-size: 11px;
  font-weight: 550;
  cursor: pointer;
}
.cond-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.3rem;
}
.conditions li {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 0.4rem;
  align-items: baseline;
  padding: 0.35rem 0.45rem;
  border-radius: 6px;
  background: #fafafa;
  border: 1px solid var(--separator);
}
.conditions li strong {
  font-size: 11px;
}
.conditions li span {
  color: var(--secondary);
  font-size: 11px;
  line-height: 1.35;
}
.conditions li[data-state='ok'] {
  background: var(--success-soft);
}
.conditions li[data-state='warn'] {
  background: var(--caution-soft);
}
.conditions li[data-state='fail'] {
  background: var(--danger-soft);
}
.conditions li[data-state='unchecked'] {
  background: #f2f2f7;
}
.case-list {
  max-height: 240px;
  overflow: auto;
}
.case-list li {
  display: flex;
  justify-content: space-between;
  gap: 0.45rem;
  align-items: center;
  padding: 0.35rem 0.45rem;
  border-radius: 6px;
  background: #fafafa;
  border: 1px solid var(--separator);
}
.case-list li > div {
  display: grid;
  min-width: 0;
}
.case-list strong {
  font-size: 12px;
}
.case-list span {
  color: var(--secondary);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.note,
.error {
  margin: 0;
  font-size: 12px;
  color: var(--secondary);
}
.error {
  color: var(--danger);
}
@media (max-width: 820px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .field {
    grid-template-columns: 48px minmax(0, 1fr);
  }
  input,
  select {
    max-width: none;
  }
}
</style>
