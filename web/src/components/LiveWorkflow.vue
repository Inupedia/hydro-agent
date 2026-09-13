<script setup lang="ts">
import { computed } from 'vue'
import { WORKFLOW, displayNodeFor } from '../generated/workflow'

const props = defineProps<{
  action?: string | null
  status?: string | null
  completedActions: string[]
  gateStatus?: string | null
  expanded?: boolean
  workflowVersion?: string | null
}>()

type NodeState = 'current' | 'visited' | 'paused' | 'blocked' | 'pending'
type StageId = 'prepare' | 'forecast' | 'diagnose' | 'optimize' | 'gate' | 'report'
type RuntimeNode = {
  id: string
  action: string
  label: string
  detail: string
}
type PresentationStage = {
  id: StageId
  label: string
  eyebrow: string
  description: string
  actions: readonly string[]
}

const PRESENTATION_STAGES: readonly PresentationStage[] = [
  {
    id: 'prepare',
    label: '任务准备',
    eyebrow: 'DATA & SCHEME',
    description: '检查本轮资料，并确认基础方案可运行。',
    actions: ['A01_CHECK_DATA', 'A03_VALIDATE_SCHEME'],
  },
  {
    id: 'forecast',
    label: '执行计算',
    eyebrow: 'FORECAST',
    description: '使用当前方案执行一次流量预测。',
    actions: ['A05_FORECAST'],
  },
  {
    id: 'diagnose',
    label: '结果诊断',
    eyebrow: 'DIAGNOSE',
    description: '对照观测判断：已经够用，还是需要进入率定。',
    actions: ['A06_DIAGNOSE'],
  },
  {
    id: 'optimize',
    label: '参数调整',
    eyebrow: 'CALIBRATION',
    description: '仅在诊断需要时执行；Gate 退回后可能再次进入本阶段。',
    actions: ['A07_OPTIMIZE'],
  },
  {
    id: 'gate',
    label: '质量把关',
    eyebrow: 'GATE',
    description: '候选方案只走一条结论路径；KEEP / ROLLBACK 在预算允许时可回到参数调整。',
    actions: ['A08_GATE', 'A09_RESOLVE'],
  },
  {
    id: 'report',
    label: '结果确认',
    eyebrow: 'LOCK & REPORT',
    description: '锁定采用方案，完成历史回放并形成评估报告。',
    actions: ['A10_FREEZE', 'A11_REPLAY', 'A12_EVALUATE_REPORT'],
  },
]

const ACTION_STAGE: Record<string, StageId> = Object.fromEntries(
  PRESENTATION_STAGES.flatMap((stage) => stage.actions.map((action) => [action, stage.id])),
) as Record<string, StageId>

const doneActions = computed(() => new Set(props.completedActions))
const currentNode = computed(() => displayNodeFor(props.action, props.gateStatus || props.status))
const workflowVersionLabel = computed(() => props.workflowVersion || WORKFLOW.version)

function runtimeNode(actionId: string): RuntimeNode | null {
  const item = WORKFLOW.actions[actionId as keyof typeof WORKFLOW.actions]
  if (!item) return null
  const id = displayNodeFor(actionId)
  if (!id) return null
  return {
    id,
    action: actionId,
    label: item.label_zh,
    detail: item.explain_zh,
  }
}

const stages = computed(() =>
  PRESENTATION_STAGES.map((stage, index) => ({
    ...stage,
    index: index + 1,
    nodes: stage.actions.map(runtimeNode).filter((node): node is RuntimeNode => Boolean(node)),
  })),
)

const activeStageId = computed<StageId>(() => {
  if (props.action && ACTION_STAGE[props.action]) return ACTION_STAGE[props.action]
  for (let index = props.completedActions.length - 1; index >= 0; index -= 1) {
    const stage = ACTION_STAGE[props.completedActions[index]]
    if (stage) return stage
  }
  return 'prepare'
})

const activeStage = computed(() => stages.value.find((stage) => stage.id === activeStageId.value) || stages.value[0])

const currentLabel = computed(() => {
  if (props.status === 'failed' || props.status === 'error') return '执行受阻'
  if (props.status === 'paused') return '计算已暂停'
  const item = props.action ? WORKFLOW.actions[props.action as keyof typeof WORKFLOW.actions] : undefined
  return item?.title_running_zh || '等待执行'
})

function actionState(actionId: string): NodeState {
  if (props.action === actionId) {
    if (props.status === 'failed' || props.status === 'error') return 'blocked'
    if (props.status === 'paused') return 'paused'
    return 'current'
  }
  if (doneActions.value.has(actionId)) return 'visited'
  return 'pending'
}

function stageState(stage: (typeof stages.value)[number]): 'current' | 'visited' | 'pending' {
  if (stage.id === activeStageId.value) return 'current'
  if (stage.actions.some((action) => doneActions.value.has(action))) return 'visited'
  return 'pending'
}

function branchState(id: string): NodeState {
  const branchNode = displayNodeFor('A09_RESOLVE', props.gateStatus || props.status)
  if (props.action === 'A09_RESOLVE' && branchNode === id) {
    if (props.status === 'failed' || props.status === 'error') return 'blocked'
    if (props.status === 'paused') return 'paused'
    return 'current'
  }
  if (doneActions.value.has('A09_RESOLVE') && branchNode === id) return 'visited'
  return 'pending'
}
</script>

<template>
  <section
    class="live-workflow workflow-canvas"
    :class="{ 'is-expanded': expanded }"
    data-test="live-workflow"
    :data-current-node="currentNode || undefined"
    :data-active-stage="activeStage.id"
  >
    <header class="workflow-head">
      <div class="workflow-title-group">
        <div class="eyebrow">HYDRO AGENT · RUNTIME MAP</div>
        <div class="title-row">
          <h3>实时执行地图</h3>
          <span class="version-pill">v{{ workflowVersionLabel }}</span>
        </div>
        <p>顶部只说明当前所处阶段；中央只放大当前阶段的真实路径，分支与回退不再伪装成线性“完成进度”。</p>
      </div>
      <div class="current-chip" :class="`is-${status || 'idle'}`" aria-live="polite">
        <i aria-hidden="true" />
        <span>{{ currentLabel }}</span>
      </div>
    </header>

    <div class="stage-summary" data-test="stage-summary">
      <div
        v-for="stage in stages"
        :key="stage.id"
        class="stage-summary-item"
        :class="`is-${stageState(stage)}`"
        :data-stage="stage.id"
        :data-state="stageState(stage)"
      >
        <span class="stage-summary-index">{{ String(stage.index).padStart(2, '0') }}</span>
        <span class="stage-summary-copy">
          <strong>{{ stage.label }}</strong>
          <small>{{ stageState(stage) === 'current' ? '当前阶段' : stageState(stage) === 'visited' ? '已经过' : '待进入' }}</small>
        </span>
      </div>
    </div>

    <div class="workflow-focus">
      <Transition name="stage-shift" mode="out-in">
        <section :key="activeStage.id" class="focus-stage" :data-focus-stage="activeStage.id">
          <header class="focus-head">
            <div>
              <span>{{ activeStage.eyebrow }}</span>
              <h4>{{ activeStage.label }}</h4>
            </div>
            <p>{{ activeStage.description }}</p>
          </header>

          <div v-if="activeStage.id === 'prepare' || activeStage.id === 'report'" class="linear-flow">
            <template v-for="(node, index) in activeStage.nodes" :key="node.action">
              <article
                class="workflow-node large"
                :class="`is-${actionState(node.action)}`"
                :data-node-id="node.id"
                :data-state="actionState(node.action)"
                data-test="workflow-node"
                :aria-current="actionState(node.action) === 'current' || actionState(node.action) === 'paused' || actionState(node.action) === 'blocked' ? 'step' : undefined"
              >
                <div class="node-status" aria-hidden="true"><span /></div>
                <div class="node-copy">
                  <strong>{{ node.label }}</strong>
                  <span>{{ node.detail }}</span>
                </div>
                <span class="action-code">{{ node.action.replace('_', '·') }}</span>
              </article>
              <svg v-if="index < activeStage.nodes.length - 1" class="flow-arrow horizontal" viewBox="0 0 72 24" aria-hidden="true">
                <path d="M2 12 H61" />
                <path d="M54 5 L62 12 L54 19" />
              </svg>
            </template>
          </div>

          <div v-else-if="activeStage.id === 'forecast'" class="single-stage-flow">
            <div class="context-anchor">
              <span>来自 01</span>
              <strong>任务准备完成</strong>
            </div>
            <svg class="flow-arrow horizontal wide" viewBox="0 0 96 24" aria-hidden="true">
              <path d="M2 12 H84" />
              <path d="M77 5 L85 12 L77 19" />
            </svg>
            <article
              v-if="activeStage.nodes[0]"
              class="workflow-node hero-node"
              :class="`is-${actionState(activeStage.nodes[0].action)}`"
              :data-node-id="activeStage.nodes[0].id"
              :data-state="actionState(activeStage.nodes[0].action)"
              data-test="workflow-node"
              :aria-current="actionState(activeStage.nodes[0].action) === 'current' ? 'step' : undefined"
            >
              <div class="node-status" aria-hidden="true"><span /></div>
              <div class="node-copy">
                <strong>{{ activeStage.nodes[0].label }}</strong>
                <span>{{ activeStage.nodes[0].detail }}</span>
              </div>
              <span class="action-code">{{ activeStage.nodes[0].action.replace('_', '·') }}</span>
            </article>
            <svg class="flow-arrow horizontal wide" viewBox="0 0 96 24" aria-hidden="true">
              <path d="M2 12 H84" />
              <path d="M77 5 L85 12 L77 19" />
            </svg>
            <div class="context-anchor">
              <span>进入 03</span>
              <strong>结果诊断</strong>
            </div>
          </div>

          <div v-else-if="activeStage.id === 'diagnose'" class="decision-stage-flow">
            <article
              v-if="activeStage.nodes[0]"
              class="workflow-node hero-node decision-node"
              :class="`is-${actionState(activeStage.nodes[0].action)}`"
              :data-node-id="activeStage.nodes[0].id"
              :data-state="actionState(activeStage.nodes[0].action)"
              data-test="workflow-node"
              :aria-current="actionState(activeStage.nodes[0].action) === 'current' ? 'step' : undefined"
            >
              <div class="node-status" aria-hidden="true"><span /></div>
              <div class="node-copy">
                <strong>{{ activeStage.nodes[0].label }}</strong>
                <span>{{ activeStage.nodes[0].detail }}</span>
              </div>
              <span class="action-code">{{ activeStage.nodes[0].action.replace('_', '·') }}</span>
            </article>

            <div class="decision-fan" aria-hidden="true">
              <svg viewBox="0 0 140 180" preserveAspectRatio="none">
                <path d="M0 90 H42 V45 H126" />
                <path d="M42 90 V135 H126" />
                <path d="M118 37 L128 45 L118 53" />
                <path d="M118 127 L128 135 L118 143" />
              </svg>
            </div>

            <div class="decision-targets">
              <div class="route-card">
                <span>需要率定</span>
                <strong>04 参数调整</strong>
                <small>进入有限调参</small>
              </div>
              <div class="route-card">
                <span>已经够用</span>
                <strong>06 结果确认</strong>
                <small>跳过调参和 Gate，直接冻结</small>
              </div>
            </div>
          </div>

          <div v-else-if="activeStage.id === 'optimize'" class="single-stage-flow loop-aware">
            <div class="context-anchor">
              <span>来自 03</span>
              <strong>诊断需要率定</strong>
            </div>
            <svg class="flow-arrow horizontal wide" viewBox="0 0 96 24" aria-hidden="true">
              <path d="M2 12 H84" />
              <path d="M77 5 L85 12 L77 19" />
            </svg>
            <article
              v-if="activeStage.nodes[0]"
              class="workflow-node hero-node"
              :class="`is-${actionState(activeStage.nodes[0].action)}`"
              :data-node-id="activeStage.nodes[0].id"
              :data-state="actionState(activeStage.nodes[0].action)"
              data-test="workflow-node"
              :aria-current="actionState(activeStage.nodes[0].action) === 'current' ? 'step' : undefined"
            >
              <div class="node-status" aria-hidden="true"><span /></div>
              <div class="node-copy">
                <strong>{{ activeStage.nodes[0].label }}</strong>
                <span>{{ activeStage.nodes[0].detail }}</span>
              </div>
              <span class="action-code">{{ activeStage.nodes[0].action.replace('_', '·') }}</span>
            </article>
            <svg class="flow-arrow horizontal wide" viewBox="0 0 96 24" aria-hidden="true">
              <path d="M2 12 H84" />
              <path d="M77 5 L85 12 L77 19" />
            </svg>
            <div class="context-anchor">
              <span>提交候选</span>
              <strong>05 质量把关</strong>
            </div>
            <div class="loop-hint">Gate 为 KEEP / ROLLBACK 且仍有预算时，会回到这里换策略再试。</div>
          </div>

          <div v-else-if="activeStage.id === 'gate'" class="gate-flow">
            <div class="gate-source context-anchor">
              <span>来自 04</span>
              <strong>参数调整</strong>
              <small>候选方案已生成</small>
            </div>

            <div class="gate-entry" aria-hidden="true">
              <svg viewBox="0 0 100 100" preserveAspectRatio="none">
                <path d="M2 50 H88" />
                <path d="M80 40 L90 50 L80 60" />
              </svg>
            </div>

            <article
              v-if="activeStage.nodes[0]"
              class="workflow-node hero-node gate-node"
              :class="`is-${actionState('A08_GATE')}`"
              :data-node-id="activeStage.nodes[0].id"
              :data-state="actionState('A08_GATE')"
              data-test="workflow-node"
              :aria-current="actionState('A08_GATE') === 'current' ? 'step' : undefined"
            >
              <div class="node-status" aria-hidden="true"><span /></div>
              <div class="node-copy">
                <strong>{{ activeStage.nodes[0].label }}</strong>
                <span>{{ activeStage.nodes[0].detail }}</span>
              </div>
              <span class="action-code">A08·GATE</span>
            </article>

            <div class="branch-fan" aria-hidden="true">
              <svg viewBox="0 0 120 400" preserveAspectRatio="none">
                <path d="M0 200 H34 V50 H106" />
                <path d="M34 200 V150 H106" />
                <path d="M34 200 V250 H106" />
                <path d="M34 200 V350 H106" />
                <path d="M98 42 L108 50 L98 58" />
                <path d="M98 142 L108 150 L98 158" />
                <path d="M98 242 L108 250 L98 258" />
                <path d="M98 342 L108 350 L98 358" />
              </svg>
            </div>

            <div class="gate-branches">
              <article class="route-card branch-card" :class="`is-${branchState('accept')}`" data-node-id="accept" :data-state="branchState('accept')" data-test="workflow-node" :aria-current="branchState('accept') === 'current' ? 'step' : undefined">
                <span>ACCEPT</span>
                <strong>采用候选方案</strong>
                <small>→ 06 结果确认</small>
              </article>
              <article class="route-card branch-card" :class="`is-${branchState('keep')}`" data-node-id="keep" :data-state="branchState('keep')" data-test="workflow-node" :aria-current="branchState('keep') === 'current' ? 'step' : undefined">
                <span>KEEP</span>
                <strong>保留原方案</strong>
                <small>可重试，或停止搜索后进入 06</small>
              </article>
              <article class="route-card branch-card" :class="`is-${branchState('rollback')}`" data-node-id="rollback" :data-state="branchState('rollback')" data-test="workflow-node" :aria-current="branchState('rollback') === 'current' || branchState('rollback') === 'blocked' ? 'step' : undefined">
                <span>ROLLBACK</span>
                <strong>回到安全方案</strong>
                <small>可重试，或停止搜索后进入 06</small>
              </article>
              <article class="route-card branch-card" :class="`is-${branchState('blocked')}`" data-node-id="blocked" :data-state="branchState('blocked')" data-test="workflow-node" :aria-current="branchState('blocked') === 'current' || branchState('blocked') === 'blocked' ? 'step' : undefined">
                <span>BLOCKED</span>
                <strong>暂停 / 终止</strong>
                <small>等待人工处理</small>
              </article>
            </div>

            <div class="gate-loop" aria-label="KEEP 或 ROLLBACK 且预算允许时回到参数调整">
              <svg viewBox="0 0 1000 84" preserveAspectRatio="none" aria-hidden="true">
                <path d="M930 12 V56 H84" />
                <path d="M96 46 L82 56 L96 66" />
              </svg>
              <span>KEEP / ROLLBACK 且预算允许 → 回到 04 参数调整</span>
            </div>
          </div>
        </section>
      </Transition>
    </div>

    <footer class="workflow-legend">
      <span><i class="legend-dot current" />当前动作</span>
      <span><i class="legend-dot visited" />已经过，不代表不会再次进入</span>
      <span><i class="legend-dot paused" />暂停</span>
      <span><i class="legend-dot blocked" />受阻</span>
    </footer>
  </section>
</template>

<style scoped>
.workflow-canvas {
  --wf-bg: rgba(248, 249, 251, 0.92);
  --wf-surface: rgba(255, 255, 255, 0.94);
  --wf-surface-soft: rgba(255, 255, 255, 0.72);
  --wf-text: #1d1d1f;
  --wf-secondary: #62626a;
  --wf-tertiary: #8a8a93;
  --wf-border: rgba(255, 255, 255, 0.98);
  --wf-separator: rgba(210, 212, 219, 0.86);
  --wf-line: rgba(93, 96, 105, 0.34);
  --wf-blue: #007aff;
  --wf-amber: #9a6200;
  --wf-red: #c80018;
  position: relative;
  display: flex;
  min-height: 520px;
  flex-direction: column;
  margin: 20px 0 10px;
  overflow: hidden;
  border: 1px solid var(--wf-border);
  border-radius: 24px;
  background: var(--wf-bg);
  box-shadow: 0 10px 34px rgba(16, 24, 40, 0.08), inset 0 1px 0 #fff;
  backdrop-filter: blur(24px) saturate(1.08);
  -webkit-backdrop-filter: blur(24px) saturate(1.08);
  color: var(--wf-text);
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'PingFang SC', 'Helvetica Neue', 'Segoe UI', sans-serif;
}
.workflow-canvas.is-expanded { min-height: min(70vh, 640px); margin-top: 8px; }
.workflow-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid rgba(225, 226, 231, 0.72);
  background: rgba(255, 255, 255, 0.54);
}
.workflow-title-group { min-width: 0; }
.eyebrow { margin-bottom: 5px; color: var(--wf-tertiary); font-size: 9px; font-weight: 700; letter-spacing: 0.14em; }
.title-row { display: flex; align-items: center; gap: 8px; }
.title-row h3 { margin: 0; font-size: 18px; line-height: 1.2; letter-spacing: -0.02em; }
.version-pill {
  padding: 3px 7px;
  border: 1px solid rgba(0, 122, 255, 0.18);
  border-radius: 999px;
  background: #fff;
  color: #005fcc;
  font-size: 9px;
  font-weight: 700;
}
.workflow-title-group p { margin: 6px 0 0; max-width: 760px; color: var(--wf-secondary); font-size: 11px; line-height: 1.5; }
.current-chip {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 260px;
  padding: 8px 11px;
  border: 1px solid rgba(0, 122, 255, 0.22);
  border-radius: 999px;
  background: #fff;
  color: #005fcc;
  font-size: 10px;
  font-weight: 650;
  box-shadow: 0 3px 14px rgba(16, 24, 40, 0.05), inset 0 1px 0 #fff;
}
.current-chip i { width: 7px; height: 7px; border-radius: 50%; background: var(--wf-blue); box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.1); }
.current-chip.is-paused { border-color: rgba(154, 98, 0, 0.28); color: var(--wf-amber); }
.current-chip.is-paused i { background: var(--wf-amber); box-shadow: 0 0 0 4px rgba(154, 98, 0, 0.1); }
.current-chip.is-failed, .current-chip.is-error { border-color: rgba(200, 0, 24, 0.24); color: var(--wf-red); }
.current-chip.is-failed i, .current-chip.is-error i { background: var(--wf-red); box-shadow: 0 0 0 4px rgba(200, 0, 24, 0.09); }
.stage-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(225, 226, 231, 0.72);
  background: rgba(255, 255, 255, 0.36);
}
.stage-summary-item {
  min-width: 0;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 48px;
  padding: 8px 9px;
  border: 1px solid rgba(211, 213, 220, 0.78);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 2px 9px rgba(16, 24, 40, 0.035), inset 0 1px 0 #fff;
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease, opacity 180ms ease;
}
.stage-summary-item.is-current {
  border-color: rgba(0, 122, 255, 0.48);
  box-shadow: 0 7px 20px rgba(0, 122, 255, 0.1), inset 0 1px 0 #fff;
  transform: translateY(-1px);
}
.stage-summary-item.is-pending { opacity: 0.54; }
.stage-summary-index {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 1px solid rgba(193, 195, 202, 0.82);
  border-radius: 9px;
  background: #fff;
  color: var(--wf-secondary);
  font-size: 9px;
  font-weight: 760;
}
.stage-summary-item.is-current .stage-summary-index { border-color: var(--wf-blue); color: var(--wf-blue); }
.stage-summary-copy { min-width: 0; }
.stage-summary-copy strong { display: block; overflow: hidden; font-size: 10px; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.stage-summary-copy small { display: block; margin-top: 3px; color: var(--wf-tertiary); font-size: 8px; white-space: nowrap; }
.stage-summary-item.is-current small { color: #006ee6; }
.workflow-focus {
  flex: 1;
  min-height: 340px;
  padding: 14px 18px 10px;
  overflow: hidden;
}
.focus-stage {
  height: 100%;
  min-height: 320px;
  padding: 14px 16px 16px;
  border: 1px solid rgba(255, 255, 255, 0.98);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.7);
  box-shadow: 0 4px 18px rgba(16, 24, 40, 0.045), inset 0 1px 0 #fff;
}
.focus-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 0 2px 12px;
  border-bottom: 1px solid rgba(222, 224, 230, 0.72);
}
.focus-head > div { flex: 0 0 auto; }
.focus-head span { display: block; color: var(--wf-tertiary); font-size: 8px; font-weight: 740; letter-spacing: 0.14em; }
.focus-head h4 { margin: 3px 0 0; font-size: 20px; letter-spacing: -0.025em; }
.focus-head p { max-width: 620px; margin: 3px 0 0; color: var(--wf-secondary); font-size: 11px; line-height: 1.5; text-align: right; }
.linear-flow,
.single-stage-flow,
.decision-stage-flow {
  display: flex;
  min-height: 236px;
  align-items: center;
  justify-content: center;
  padding: 20px 10px 4px;
}
.linear-flow { gap: 10px; }
.single-stage-flow { gap: 14px; position: relative; }
.decision-stage-flow { gap: 18px; }
.workflow-node,
.route-card,
.context-anchor {
  box-sizing: border-box;
  border: 1px solid rgba(204, 206, 214, 0.88);
  background: var(--wf-surface);
  box-shadow: 0 5px 16px rgba(16, 24, 40, 0.055), inset 0 1px 0 #fff;
}
.workflow-node {
  position: relative;
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 210px;
  max-width: 280px;
  min-height: 82px;
  padding: 14px 14px;
  border-radius: 17px;
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease, opacity 180ms ease;
}
.workflow-node.large { flex: 1 1 0; max-width: 300px; }
.workflow-node.hero-node { width: min(320px, 32vw); max-width: 340px; min-height: 104px; }
.workflow-node.is-pending { opacity: 0.48; }
.workflow-node.is-current {
  border-color: rgba(0, 122, 255, 0.52);
  box-shadow: 0 12px 30px rgba(0, 122, 255, 0.11), inset 0 1px 0 #fff;
  transform: translateY(-2px);
}
.workflow-node.is-visited { border-color: rgba(175, 178, 186, 0.92); }
.workflow-node.is-paused { border-color: rgba(154, 98, 0, 0.42); }
.workflow-node.is-blocked { border-color: rgba(200, 0, 24, 0.38); }
.node-status { display: grid; place-items: center; }
.node-status span {
  width: 9px;
  height: 9px;
  border: 2px solid #b6b9c1;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 0 0 4px rgba(133, 133, 142, 0.06);
}
.is-current .node-status span { border-color: var(--wf-blue); box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.1); animation: node-pulse 1.8s ease-in-out infinite; }
.is-visited .node-status span { border-color: #7f828a; }
.is-paused .node-status span { border-color: var(--wf-amber); }
.is-blocked .node-status span { border-color: var(--wf-red); }
.node-copy { min-width: 0; }
.node-copy strong { display: block; color: var(--wf-text); font-size: 14px; font-weight: 690; line-height: 1.22; }
.node-copy span { display: block; margin-top: 5px; color: var(--wf-secondary); font-size: 10px; line-height: 1.42; }
.action-code { align-self: start; color: var(--wf-tertiary); font-size: 8px; font-weight: 680; letter-spacing: 0.02em; }
.flow-arrow { flex: 0 0 58px; width: 58px; height: 24px; overflow: visible; }
.flow-arrow.wide { flex-basis: 76px; width: 76px; }
.flow-arrow path,
.decision-fan path,
.gate-entry path,
.branch-fan path,
.gate-loop path {
  fill: none;
  stroke: var(--wf-line);
  stroke-width: 1.8;
  vector-effect: non-scaling-stroke;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.context-anchor {
  min-width: 145px;
  padding: 12px 13px;
  border-radius: 14px;
  text-align: center;
}
.context-anchor span,
.route-card span { display: block; color: var(--wf-tertiary); font-size: 8px; font-weight: 720; letter-spacing: 0.05em; }
.context-anchor strong,
.route-card strong { display: block; margin-top: 4px; font-size: 11px; line-height: 1.25; }
.context-anchor small,
.route-card small { display: block; margin-top: 4px; color: var(--wf-secondary); font-size: 8px; line-height: 1.35; }
.decision-node { flex: 0 0 auto; }
.decision-fan { flex: 0 0 120px; width: 120px; height: 180px; }
.decision-fan svg { width: 100%; height: 100%; overflow: visible; }
.decision-targets { display: grid; gap: 16px; width: min(280px, 28vw); }
.route-card { min-height: 74px; padding: 12px 14px; border-radius: 15px; }
.loop-aware { padding-bottom: 40px; }
.loop-hint {
  position: absolute;
  left: 50%;
  bottom: 6px;
  transform: translateX(-50%);
  padding: 7px 11px;
  border: 1px dashed rgba(0, 122, 255, 0.3);
  border-radius: 999px;
  background: #fff;
  color: #366181;
  font-size: 9px;
  white-space: nowrap;
}
.gate-flow {
  position: relative;
  display: grid;
  grid-template-columns: minmax(130px, 0.8fr) 70px minmax(190px, 1fr) 92px minmax(240px, 1.25fr);
  grid-template-rows: repeat(4, 62px) 62px;
  align-items: center;
  min-height: 284px;
  column-gap: 8px;
  row-gap: 8px;
  padding: 10px 6px 0;
}
.gate-source { grid-column: 1; grid-row: 2 / span 2; justify-self: stretch; }
.gate-entry { grid-column: 2; grid-row: 2 / span 2; width: 100%; height: 100%; }
.gate-entry svg { width: 100%; height: 100%; }
.gate-node { grid-column: 3; grid-row: 2 / span 2; width: 100%; max-width: none; justify-self: stretch; }
.branch-fan { grid-column: 4; grid-row: 1 / span 4; width: 100%; height: 100%; }
.branch-fan svg { width: 100%; height: 100%; overflow: visible; }
.gate-branches { grid-column: 5; grid-row: 1 / span 4; display: grid; grid-template-rows: repeat(4, 62px); gap: 8px; }
.branch-card { min-height: 62px; padding: 9px 12px; transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease, opacity 180ms ease; }
.branch-card.is-pending { opacity: 0.48; }
.branch-card.is-current { border-color: rgba(0, 122, 255, 0.52); box-shadow: 0 10px 26px rgba(0, 122, 255, 0.1), inset 0 1px 0 #fff; transform: translateX(2px); }
.branch-card.is-visited { border-color: rgba(175, 178, 186, 0.92); }
.branch-card.is-paused { border-color: rgba(154, 98, 0, 0.42); }
.branch-card.is-blocked { border-color: rgba(200, 0, 24, 0.38); }
.gate-loop { position: relative; grid-column: 1 / -1; grid-row: 5; height: 62px; }
.gate-loop svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.gate-loop path:first-child { stroke-dasharray: 6 5; }
.gate-loop span {
  position: absolute;
  left: 50%;
  top: 34px;
  transform: translate(-50%, -50%);
  padding: 4px 9px;
  border-radius: 999px;
  background: #fff;
  color: #4f6070;
  font-size: 8px;
  font-weight: 650;
  white-space: nowrap;
}
.workflow-legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 14px; padding: 6px 14px 12px; color: var(--wf-secondary); font-size: 9px; }
.workflow-legend span { display: inline-flex; align-items: center; gap: 5px; }
.legend-dot { width: 7px; height: 7px; border: 2px solid #b6b9c1; border-radius: 50%; background: #fff; }
.legend-dot.current { border-color: var(--wf-blue); }
.legend-dot.visited { border-color: #7f828a; }
.legend-dot.paused { border-color: var(--wf-amber); }
.legend-dot.blocked { border-color: var(--wf-red); }
.stage-shift-enter-active,
.stage-shift-leave-active { transition: opacity 180ms ease, transform 180ms ease; }
.stage-shift-enter-from { opacity: 0; transform: translateX(12px); }
.stage-shift-leave-to { opacity: 0; transform: translateX(-12px); }
@keyframes node-pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.18); } }
@media (prefers-reduced-motion: reduce) {
  .workflow-node,
  .stage-summary-item,
  .branch-card,
  .node-status span,
  .stage-shift-enter-active,
  .stage-shift-leave-active { transition: none !important; animation: none !important; }
}
@media (max-width: 980px) {
  .stage-summary { gap: 6px; padding-inline: 10px; }
  .stage-summary-item { grid-template-columns: 24px minmax(0, 1fr); gap: 6px; padding: 7px; }
  .stage-summary-index { width: 24px; height: 24px; }
  .stage-summary-copy small { display: none; }
  .workflow-focus { padding-inline: 12px; }
  .workflow-node.hero-node { width: min(300px, 34vw); }
  .gate-flow { grid-template-columns: minmax(110px, 0.75fr) 54px minmax(170px, 1fr) 68px minmax(220px, 1.2fr); }
}
@media (max-width: 760px) {
  .workflow-canvas { min-height: 0; }
  .workflow-head { flex-direction: column; padding: 15px; }
  .current-chip { max-width: 100%; }
  .stage-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .workflow-focus { min-height: 0; overflow: visible; }
  .focus-stage { min-height: 0; }
  .focus-head { flex-direction: column; gap: 5px; }
  .focus-head p { text-align: left; }
  .linear-flow,
  .single-stage-flow,
  .decision-stage-flow { flex-direction: column; min-height: 0; padding-top: 16px; }
  .workflow-node,
  .workflow-node.large,
  .workflow-node.hero-node,
  .decision-targets { width: 100%; max-width: none; }
  .flow-arrow.horizontal { transform: rotate(90deg); margin: 6px 0; }
  .decision-fan { width: 80px; height: 74px; transform: rotate(90deg); }
  .decision-targets { grid-template-columns: 1fr 1fr; }
  .loop-hint { position: static; transform: none; white-space: normal; text-align: center; }
  .gate-flow { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
  .gate-entry { width: 70px; height: 24px; transform: rotate(90deg); }
  .gate-node { width: 100%; }
  .branch-fan { width: 80px; height: 60px; transform: rotate(90deg); }
  .gate-branches { width: 100%; grid-template-columns: 1fr 1fr; grid-template-rows: auto; }
  .gate-loop { width: 100%; height: 60px; }
  .workflow-canvas.is-expanded { min-height: 0; }
}
</style>