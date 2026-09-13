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

type NodeState = 'current' | 'done' | 'paused' | 'blocked' | 'pending'
type RuntimeNode = {
  id: string
  action?: string
  label: string
  detail: string
  stage: string
  branch?: boolean
}

const STAGE_ORDER = ['data', 'forecast', 'gate', 'report'] as const
const BRANCH_NODES: RuntimeNode[] = [
  { id: 'accept', label: 'ACCEPT 采用', detail: '候选方案达到门槛', stage: 'gate', branch: true },
  { id: 'keep', label: 'KEEP 原方案', detail: '提升不足，保留当前方案', stage: 'gate', branch: true },
  { id: 'rollback', label: 'ROLLBACK 回退', detail: '触发约束，回到安全方案', stage: 'gate', branch: true },
  { id: 'blocked', label: '暂停 / 终止', detail: '需要人工处理后继续', stage: 'gate', branch: true },
]

const runtimeNodes = computed<RuntimeNode[]>(() => {
  const nodes: RuntimeNode[] = []
  for (const actionId of WORKFLOW.step_order) {
    if (actionId === 'A09_RESOLVE') continue
    const item = WORKFLOW.actions[actionId]
    const id = displayNodeFor(actionId)
    if (!item || !id) continue
    nodes.push({
      id,
      action: actionId,
      label: item.label_zh,
      detail: item.explain_zh,
      stage: item.display_stage,
    })
    if (actionId === 'A08_GATE') nodes.push(...BRANCH_NODES)
  }
  return nodes
})

const stages = computed(() =>
  STAGE_ORDER.map((id, index) => ({
    id,
    index: index + 1,
    label: WORKFLOW.display_stages.find((stage) => stage.id === id)?.label || id,
    nodes: runtimeNodes.value.filter((node) => node.stage === id),
  })),
)

const currentNode = computed(() => displayNodeFor(props.action, props.gateStatus || props.status))
const doneNodes = computed(() => {
  const done = new Set<string>()
  for (const action of props.completedActions) {
    const node = displayNodeFor(action)
    if (node) done.add(node)
  }
  if (props.gateStatus === 'ACCEPT') done.add('accept')
  if (props.gateStatus === 'KEEP') done.add('keep')
  if (props.gateStatus === 'ROLLBACK') done.add('rollback')
  if (props.gateStatus === 'blocked' || props.gateStatus === 'failed') done.add('blocked')
  return done
})

const currentLabel = computed(() => {
  if (props.status === 'failed' || props.status === 'error') return '执行受阻'
  if (props.status === 'paused') return '计算已暂停'
  const item = props.action ? WORKFLOW.actions[props.action as keyof typeof WORKFLOW.actions] : undefined
  return item?.title_running_zh || '等待执行'
})

const workflowVersionLabel = computed(() => props.workflowVersion || WORKFLOW.version)

function nodeState(node: RuntimeNode): NodeState {
  if (node.id === currentNode.value) {
    if (props.status === 'failed' || props.status === 'error') return 'blocked'
    if (props.status === 'paused') return 'paused'
    return 'current'
  }
  if (doneNodes.value.has(node.id)) return 'done'
  return 'pending'
}

function stageProgress(nodes: RuntimeNode[]) {
  const done = nodes.filter((node) => ['done', 'current', 'paused', 'blocked'].includes(nodeState(node))).length
  return `${done}/${nodes.length}`
}
</script>

<template>
  <section
    class="live-workflow workflow-canvas"
    :class="{ 'is-expanded': expanded }"
    data-test="live-workflow"
    :data-current-node="currentNode || undefined"
  >
    <header class="workflow-head">
      <div class="workflow-title-group">
        <div class="eyebrow">HYDRO AGENT · WORKFLOW</div>
        <div class="title-row">
          <h3>实时执行地图</h3>
          <span class="version-pill">v{{ workflowVersionLabel }}</span>
        </div>
        <p>按业务阶段展示当前动作、已完成步骤与 Gate 分支，不再切换 iframe 或追踪相机。</p>
      </div>
      <div class="current-chip" :class="`is-${status || 'idle'}`" aria-live="polite">
        <i aria-hidden="true" />
        <span>{{ currentLabel }}</span>
      </div>
    </header>

    <div class="workflow-scroll">
      <div class="workflow-track">
        <template v-for="(stage, stageIndex) in stages" :key="stage.id">
          <section class="stage-panel" :data-stage="stage.id">
            <header class="stage-head">
              <span class="stage-index">{{ String(stage.index).padStart(2, '0') }}</span>
              <div>
                <strong>{{ stage.label }}</strong>
                <small>{{ stageProgress(stage.nodes) }} 节点有进展</small>
              </div>
            </header>

            <div class="node-stack">
              <template v-for="(node, nodeIndex) in stage.nodes" :key="node.id">
                <article
                  class="workflow-node"
                  :class="[`is-${nodeState(node)}`, { 'is-branch': node.branch }]"
                  :data-node-id="node.id"
                  :data-state="nodeState(node)"
                  data-test="workflow-node"
                  :aria-current="nodeState(node) === 'current' || nodeState(node) === 'paused' || nodeState(node) === 'blocked' ? 'step' : undefined"
                >
                  <div class="node-status" aria-hidden="true"><span /></div>
                  <div class="node-copy">
                    <strong>{{ node.label }}</strong>
                    <span>{{ node.detail }}</span>
                  </div>
                  <span v-if="node.action" class="action-code">{{ node.action.replace('_', '·') }}</span>
                </article>
                <div
                  v-if="nodeIndex < stage.nodes.length - 1"
                  class="node-connector"
                  :class="{ 'is-active': doneNodes.has(node.id) || node.id === currentNode }"
                  aria-hidden="true"
                />
              </template>
            </div>

            <div v-if="stage.id === 'gate'" class="gate-note">
              <strong>Gate 路由</strong>
              <span>达到要求可直接锁定；KEEP / ROLLBACK 且预算允许时返回“有限调参”继续下一轮。</span>
            </div>
          </section>

          <div v-if="stageIndex < stages.length - 1" class="stage-bridge" aria-hidden="true">
            <span />
            <i>›</i>
          </div>
        </template>
      </div>
    </div>

    <footer class="workflow-legend">
      <span><i class="legend-dot current" />当前动作</span>
      <span><i class="legend-dot done" />已完成</span>
      <span><i class="legend-dot paused" />暂停</span>
      <span><i class="legend-dot blocked" />受阻</span>
      <span><i class="legend-dot" />待执行</span>
    </footer>
  </section>
</template>

<style scoped>
.workflow-canvas {
  --wf-bg: rgba(250, 251, 253, 0.78);
  --wf-surface: rgba(255, 255, 255, 0.68);
  --wf-surface-strong: rgba(255, 255, 255, 0.9);
  --wf-text: #1d1d1f;
  --wf-secondary: #62626a;
  --wf-tertiary: #85858e;
  --wf-border: rgba(255, 255, 255, 0.92);
  --wf-separator: rgba(220, 221, 227, 0.72);
  --wf-blue: #007aff;
  --wf-blue-soft: #eaf3ff;
  --wf-green: #248a3d;
  --wf-green-soft: #eaf6ed;
  --wf-amber: #a66500;
  --wf-amber-soft: #fff4df;
  --wf-red: #d70015;
  --wf-red-soft: #fff0f1;
  position: relative;
  min-height: 300px;
  display: flex;
  flex-direction: column;
  margin: 20px 0 10px;
  overflow: hidden;
  border: 1px solid var(--wf-border);
  border-radius: 24px;
  background:
    radial-gradient(circle at 10% 0%, rgba(120, 190, 255, 0.18), transparent 30%),
    radial-gradient(circle at 92% 100%, rgba(111, 214, 166, 0.12), transparent 32%),
    var(--wf-bg);
  box-shadow: 0 8px 28px rgba(16, 24, 40, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(24px) saturate(1.18);
  -webkit-backdrop-filter: blur(24px) saturate(1.18);
  color: var(--wf-text);
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'PingFang SC', 'Helvetica Neue', 'Segoe UI', sans-serif;
}
.workflow-canvas.is-expanded { min-height: min(64vh, 680px); margin-top: 8px; }
.workflow-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 20px 22px 14px;
  border-bottom: 1px solid rgba(232, 233, 238, 0.82);
  background: rgba(255, 255, 255, 0.24);
}
.workflow-title-group { min-width: 0; }
.eyebrow { margin-bottom: 5px; color: var(--wf-tertiary); font-size: 9px; font-weight: 700; letter-spacing: 0.14em; }
.title-row { display: flex; align-items: center; gap: 8px; }
.title-row h3 { margin: 0; font-size: 18px; line-height: 1.2; letter-spacing: -0.02em; }
.version-pill {
  padding: 3px 7px;
  border: 1px solid rgba(0, 122, 255, 0.14);
  border-radius: 999px;
  background: rgba(234, 243, 255, 0.76);
  color: #005fcc;
  font-size: 9px;
  font-weight: 700;
}
.workflow-title-group p { margin: 6px 0 0; max-width: 620px; color: var(--wf-secondary); font-size: 11px; line-height: 1.55; }
.current-chip {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 260px;
  padding: 8px 11px;
  border: 1px solid rgba(0, 122, 255, 0.14);
  border-radius: 999px;
  background: rgba(234, 243, 255, 0.72);
  color: #005fcc;
  font-size: 10px;
  font-weight: 650;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
}
.current-chip i { width: 7px; height: 7px; border-radius: 50%; background: var(--wf-blue); box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.1); }
.current-chip.is-paused { border-color: rgba(166, 101, 0, 0.16); background: rgba(255, 244, 223, 0.82); color: var(--wf-amber); }
.current-chip.is-paused i { background: var(--wf-amber); box-shadow: 0 0 0 4px rgba(166, 101, 0, 0.1); }
.current-chip.is-failed, .current-chip.is-error { border-color: rgba(215, 0, 21, 0.14); background: rgba(255, 240, 241, 0.82); color: var(--wf-red); }
.current-chip.is-failed i, .current-chip.is-error i { background: var(--wf-red); box-shadow: 0 0 0 4px rgba(215, 0, 21, 0.1); }
.workflow-scroll { flex: 1; overflow: auto; padding: 18px 18px 12px; scrollbar-width: thin; scrollbar-color: rgba(98, 98, 106, 0.2) transparent; }
.workflow-track {
  min-width: 980px;
  display: grid;
  grid-template-columns: minmax(190px, 0.95fr) 34px minmax(180px, 0.8fr) 34px minmax(250px, 1.2fr) 34px minmax(210px, 0.95fr);
  align-items: stretch;
  gap: 0;
}
.stage-panel {
  min-width: 0;
  padding: 14px;
  border: 1px solid rgba(255, 255, 255, 0.92);
  border-radius: 20px;
  background: rgba(248, 249, 251, 0.62);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9), 0 2px 8px rgba(16, 24, 40, 0.045);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}
.stage-head { display: flex; align-items: center; gap: 9px; margin-bottom: 13px; }
.stage-index {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: rgba(29, 29, 31, 0.055);
  color: var(--wf-secondary);
  font-size: 10px;
  font-weight: 750;
}
.stage-head div { min-width: 0; }
.stage-head strong { display: block; font-size: 12px; }
.stage-head small { display: block; margin-top: 2px; color: var(--wf-tertiary); font-size: 9px; }
.node-stack { display: flex; flex-direction: column; align-items: stretch; }
.workflow-node {
  position: relative;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  min-height: 56px;
  padding: 10px 10px;
  border: 1px solid var(--wf-separator);
  border-radius: 14px;
  background: var(--wf-surface-strong);
  box-shadow: 0 2px 8px rgba(16, 24, 40, 0.045), inset 0 1px 0 rgba(255, 255, 255, 0.92);
  transition: border-color 180ms ease, background 180ms ease, box-shadow 180ms ease, transform 180ms ease, opacity 180ms ease;
}
.workflow-node.is-pending { opacity: 0.58; background: rgba(255, 255, 255, 0.52); }
.workflow-node.is-current {
  border-color: rgba(0, 122, 255, 0.48);
  background: rgba(234, 243, 255, 0.88);
  box-shadow: 0 8px 24px rgba(0, 122, 255, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.96);
  transform: translateY(-1px);
}
.workflow-node.is-done { border-color: rgba(36, 138, 61, 0.28); background: rgba(234, 246, 237, 0.78); }
.workflow-node.is-paused { border-color: rgba(166, 101, 0, 0.34); background: rgba(255, 244, 223, 0.84); box-shadow: 0 7px 22px rgba(166, 101, 0, 0.09); }
.workflow-node.is-blocked { border-color: rgba(215, 0, 21, 0.32); background: rgba(255, 240, 241, 0.86); box-shadow: 0 7px 22px rgba(215, 0, 21, 0.09); }
.workflow-node.is-branch { min-height: 50px; }
.node-status { display: grid; place-items: center; }
.node-status span { width: 8px; height: 8px; border-radius: 50%; background: #c9cbd2; box-shadow: 0 0 0 4px rgba(133, 133, 142, 0.08); }
.is-current .node-status span { background: var(--wf-blue); box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.12); animation: node-pulse 1.8s ease-in-out infinite; }
.is-done .node-status span { background: var(--wf-green); box-shadow: 0 0 0 4px rgba(36, 138, 61, 0.1); }
.is-paused .node-status span { background: var(--wf-amber); box-shadow: 0 0 0 4px rgba(166, 101, 0, 0.1); }
.is-blocked .node-status span { background: var(--wf-red); box-shadow: 0 0 0 4px rgba(215, 0, 21, 0.1); }
.node-copy { min-width: 0; }
.node-copy strong { display: block; color: var(--wf-text); font-size: 11px; font-weight: 680; line-height: 1.25; }
.node-copy span { display: -webkit-box; margin-top: 3px; overflow: hidden; color: var(--wf-secondary); font-size: 9px; line-height: 1.35; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.action-code { align-self: start; color: var(--wf-tertiary); font-size: 8px; font-weight: 650; letter-spacing: 0.02em; }
.node-connector { width: 1px; height: 11px; margin: 0 auto; background: rgba(197, 199, 207, 0.72); transition: background 180ms ease, box-shadow 180ms ease; }
.node-connector.is-active { background: rgba(0, 122, 255, 0.48); box-shadow: 0 0 8px rgba(0, 122, 255, 0.18); }
.stage-bridge { display: flex; align-items: center; padding: 0 5px; }
.stage-bridge span { flex: 1; height: 1px; background: linear-gradient(90deg, rgba(197, 199, 207, 0.45), rgba(0, 122, 255, 0.38)); }
.stage-bridge i { margin-left: -1px; color: rgba(0, 122, 255, 0.58); font-size: 22px; font-style: normal; font-weight: 300; line-height: 1; }
.gate-note { margin-top: 12px; padding: 10px 11px; border: 1px solid rgba(0, 122, 255, 0.12); border-radius: 12px; background: rgba(234, 243, 255, 0.52); }
.gate-note strong { display: block; color: #005fcc; font-size: 9px; }
.gate-note span { display: block; margin-top: 3px; color: var(--wf-secondary); font-size: 8px; line-height: 1.45; }
.workflow-legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 14px; padding: 9px 14px 14px; color: var(--wf-secondary); font-size: 9px; }
.workflow-legend span { display: inline-flex; align-items: center; gap: 5px; }
.legend-dot { width: 6px; height: 6px; border-radius: 50%; background: #c9cbd2; }
.legend-dot.current { background: var(--wf-blue); }
.legend-dot.done { background: var(--wf-green); }
.legend-dot.paused { background: var(--wf-amber); }
.legend-dot.blocked { background: var(--wf-red); }
@keyframes node-pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.18); } }
@media (prefers-reduced-motion: reduce) { .workflow-node, .node-connector, .node-status span { transition: none !important; animation: none !important; } }
@media (max-width: 760px) {
  .workflow-head { flex-direction: column; padding: 16px; }
  .current-chip { max-width: 100%; }
  .workflow-scroll { padding: 12px; overflow: visible; }
  .workflow-track { min-width: 0; grid-template-columns: 1fr; gap: 0; }
  .stage-bridge { height: 28px; justify-content: center; padding: 0; }
  .stage-bridge span { flex: 0 0 1px; width: 1px; height: 22px; background: linear-gradient(180deg, rgba(197, 199, 207, 0.45), rgba(0, 122, 255, 0.38)); }
  .stage-bridge i { margin: 13px 0 0 -6px; transform: rotate(90deg); }
  .workflow-canvas.is-expanded { min-height: 0; }
}
</style>
