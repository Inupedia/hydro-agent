<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { actionTitle } from '../demo/stages'
import { diagramHtmlFor, displayNodeFor } from '../generated/workflow'

type ArchifyView = {
  reveal?: (ids: string[], options?: Record<string, unknown>) => unknown
}
type ArchifyWindow = Window & { Archify?: { view?: ArchifyView } }

const props = defineProps<{
  action?: string | null
  status?: string | null
  completedActions: string[]
  gateStatus?: string | null
  expanded?: boolean
  workflowVersion?: string | null
}>()

const frame = ref<HTMLIFrameElement | null>(null)
const loaded = ref(false)
let revealedNode: string | null = null

const diagramSrc = computed(
  () => `/diagrams/${diagramHtmlFor(props.workflowVersion)}?theme=light&embed=1&motion=still`,
)

const label = computed(() => {
  if (props.status === 'failed' || props.status === 'error') return '执行受阻'
  if (props.status === 'paused') return '计算已暂停'
  return actionTitle(props.action)
})

const currentNode = computed(() => displayNodeFor(props.action, props.gateStatus || props.status))

const doneNodes = computed(() => {
  const done = new Set<string>()
  for (const action of props.completedActions) {
    const node = displayNodeFor(action)
    if (node) done.add(node)
  }
  if (props.gateStatus === 'KEEP') done.add('keep')
  if (props.gateStatus === 'ROLLBACK') done.add('rollback')
  if (props.gateStatus === 'ACCEPT') done.add('accept')
  return done
})

function reducedMotion() {
  return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
}

function archifyView(): ArchifyView | undefined {
  const frameEl = frame.value
  const win = (frameEl?.contentDocument?.defaultView || frameEl?.contentWindow) as ArchifyWindow | null
  return win?.Archify?.view
}

function focusCamera(instant = false) {
  const node = currentNode.value
  if (!node || !loaded.value) return
  const view = archifyView()
  if (typeof view?.reveal !== 'function') return
  view.reveal([node], {
    includeNeighbors: false,
    duration: 420,
    instant: instant || reducedMotion(),
    padding: 72,
    maxScale: 2.45,
    reason: 'live-step',
  })
  revealedNode = node
}

function sync() {
  const doc = frame.value?.contentDocument
  if (!doc || !loaded.value) return
  const current = currentNode.value
  doc.querySelectorAll('[data-node-id]').forEach((node) => {
    const id = node.getAttribute('data-node-id') || ''
    const isCurrent = Boolean(current && id === current)
    const isDone = doneNodes.value.has(id) && !isCurrent
    node.classList.toggle('live-current', isCurrent)
    node.classList.toggle('live-done', isDone)
    node.classList.toggle('live-blocked', isCurrent && ['failed', 'error'].includes(props.status || ''))
    node.classList.toggle('live-pending', !isCurrent && !isDone)
    if (isCurrent) node.setAttribute('aria-current', 'step')
    else node.removeAttribute('aria-current')
  })
  if (current && current !== revealedNode) {
    requestAnimationFrame(() => focusCamera(!revealedNode))
  }
}

function ready() {
  const doc = frame.value?.contentDocument
  if (!doc) return
  loaded.value = true
  revealedNode = null
  doc.documentElement.setAttribute('data-motion', 'still')
  doc.documentElement.setAttribute('data-embed', 'true')
  if (!doc.getElementById('hydro-live-style')) {
    const style = doc.createElement('style')
    style.id = 'hydro-live-style'
    style.textContent = `
      html, body, .container { width:100%!important; height:100%!important; margin:0!important; padding:0!important; min-height:0!important; background:transparent!important; }
      .diagram-container { width:100%!important; height:100%!important; padding:8px!important; margin:0!important; overflow:hidden!important; background:transparent!important; box-shadow:none!important; }
      .diagram-container > svg { width:100%!important; height:auto!important; max-height:none!important; min-width:0!important; }
      .diagram-container::before,.diagram-container::after,.share-chapter-cue,.toolbar,.header,.cards,.diagram-nav,.guided-views { display:none!important; }
      [data-node-id] { transition: opacity .2s, filter .2s; }
      [data-node-id].live-pending { opacity: .42; }
      [data-node-id] > rect { fill:#ffffff!important; stroke:#e5e5ea!important; }
      [data-node-id].live-done > rect { fill:#eaf7ee!important; stroke:#248a3d!important; }
      [data-node-id].live-current > rect { fill:#eaf3ff!important; stroke:#007aff!important; stroke-width:3px!important; filter:drop-shadow(0 0 5px #007aff33); }
      [data-node-id].live-blocked > rect { fill:#fff0f0!important; stroke:#d70015!important; }
      text { font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif!important; }
      @media(prefers-reduced-motion:reduce) { * { transition:none!important; animation:none!important; } }
    `
    doc.head.appendChild(style)
  }
  sync()
  requestAnimationFrame(() => {
    revealedNode = null
    focusCamera(true)
  })
}

watch(() => [props.action, props.status, props.gateStatus, props.completedActions], sync, { deep: true })
</script>

<template>
  <section class="live-workflow" :class="{ 'is-expanded': expanded }" data-test="live-workflow" :data-camera-node="currentNode || undefined">
    <div class="workflow-caption">
      <span>执行地图</span>
      <strong aria-live="polite">{{ label }}</strong>
    </div>
    <iframe
      ref="frame"
      :src="diagramSrc"
      title="实时执行流程图"
      @load="ready"
    />
    <div class="workflow-key">
      <span><i class="current" />当前动作</span>
      <span><i class="done" />已有完成记录</span>
      <span><i />待执行</span>
    </div>
  </section>
</template>

<style scoped>
.live-workflow {
  flex: 1;
  min-height: 250px;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(255, 255, 255, 0.95);
  border-radius: 22px;
  margin: 20px 0 10px;
  overflow: hidden;
  transform-origin: 50% 40%;
  box-shadow: none;
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}
.live-workflow.is-expanded {
  min-height: min(62vh, 640px);
  margin: 8px 0 0;
}
.live-workflow.is-expanded iframe {
  min-height: min(52vh, 560px);
}
.workflow-caption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px 6px;
  color: #456783;
  font-size: 12px;
  flex-wrap: wrap;
}
.workflow-caption small {
  font-size: 9px;
  letter-spacing: 1.5px;
  margin-left: 8px;
  color: #8198ae;
}
.workflow-caption strong {
  color: #167ccc;
  font-size: 11px;
  font-weight: 500;
}
iframe {
  border: 0;
  width: 100%;
  flex: 1;
  min-height: 220px;
  background: transparent;
}
.workflow-key {
  display: flex;
  justify-content: center;
  gap: 18px;
  padding: 8px 12px 15px;
  color: #70869b;
  font-size: 10px;
}
.workflow-key span {
  display: flex;
  align-items: center;
  gap: 5px;
}
.workflow-key i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #c6d6e5;
}
.workflow-key .current {
  background: #007aff;
}
.workflow-key .done {
  background: #7cbaaa;
}
@media (min-width: 1101px) and (min-height: 700px) {
  .live-workflow {
    min-height: 0;
  }
  .live-workflow.is-expanded {
    min-height: 0;
    flex: 1 1 auto;
  }
  iframe {
    min-height: 120px;
  }
  .live-workflow.is-expanded iframe {
    min-height: 0;
  }
}
@media (max-width: 680px) {
  iframe {
    min-height: 240px;
  }
  .live-workflow.is-expanded {
    min-height: 280px;
  }
  .workflow-caption {
    padding: 14px 12px 4px;
  }
}
</style>
