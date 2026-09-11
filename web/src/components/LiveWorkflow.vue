<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { actionTitle } from '../demo/stages'
import { diagramHtmlFor, displayNodeFor } from '../generated/workflow'

type ArchifyView = {
  reveal?: (ids: string[], options?: Record<string, unknown>) => unknown
}
type ArchifyWindow = Window & { Archify?: { view?: ArchifyView } }
type CameraReceipt = { finished?: Promise<unknown> }

const CLOSE_SCALE = 2.45
const PAIR_SCALE = 2.85
const PULL_MS = 520
const FLOW_LEAD_MS = 380
const CLOSE_MS = 460
const FLOW_MS = 820

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
const cameraPhase = ref<'close' | 'travel' | ''>('')
let settledNode: string | null = null
let travelGen = 0
const timers: number[] = []

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

function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    timers.push(window.setTimeout(resolve, ms))
  })
}

function clearTimers() {
  while (timers.length) {
    const id = timers.pop()
    if (id !== undefined) window.clearTimeout(id)
  }
}

function stillCurrent(gen: number) {
  return gen === travelGen && loaded.value
}

async function waitCamera(result: unknown, ms: number, gen: number) {
  const finished = (result as CameraReceipt | null)?.finished
  if (finished && typeof finished.then === 'function') {
    await Promise.race([finished.then(() => undefined).catch(() => undefined), sleep(ms + 80)])
  } else {
    await sleep(ms)
  }
  return stillCurrent(gen)
}

function closeUp(instant: boolean) {
  return {
    includeNeighbors: false,
    duration: CLOSE_MS,
    instant,
    padding: 36,
    maxScale: CLOSE_SCALE,
    reason: 'live-close',
  }
}

function pairShot() {
  return {
    includeNeighbors: false,
    duration: PULL_MS,
    instant: false,
    padding: 96,
    maxScale: PAIR_SCALE,
    reason: 'live-travel',
  }
}

function clearEdgeFlow() {
  const doc = frame.value?.contentDocument
  if (!doc) return
  doc.querySelectorAll('.live-travel').forEach((el) => el.classList.remove('live-travel'))
  doc.querySelectorAll('.live-from').forEach((el) => el.classList.remove('live-from'))
  doc.querySelectorAll('.live-travel-dot').forEach((el) => el.remove())
  doc.querySelector('svg')?.classList.remove('live-traveling')
}

function playEdgeFlow(from: string, to: string) {
  const doc = frame.value?.contentDocument
  if (!doc) return
  clearEdgeFlow()
  const svg = doc.querySelector('svg')
  const path = doc.querySelector(`path[data-edge-from="${from}"][data-edge-to="${to}"]`) as SVGPathElement | null
  if (!svg || !path) return
  svg.classList.add('live-traveling')
  doc.querySelector(`[data-node-id="${from}"]`)?.classList.add('live-from')
  path.classList.add('live-travel')
  let length = 120
  try {
    if (typeof path.getTotalLength === 'function') length = Math.max(80, path.getTotalLength())
  } catch {
    length = 120
  }
  path.style.setProperty('--live-len', String(length))
  const dot = doc.createElementNS('http://www.w3.org/2000/svg', 'circle')
  dot.setAttribute('r', '5.5')
  dot.setAttribute('class', 'live-travel-dot')
  const motion = doc.createElementNS('http://www.w3.org/2000/svg', 'animateMotion')
  motion.setAttribute('dur', `${FLOW_MS}ms`)
  motion.setAttribute('repeatCount', '1')
  motion.setAttribute('fill', 'freeze')
  motion.setAttribute('path', path.getAttribute('d') || '')
  dot.appendChild(motion)
  path.parentNode?.appendChild(dot)
  try {
    ;(motion as unknown as { beginElement: () => void }).beginElement()
  } catch {
    /* SMIL optional */
  }
}

async function travelTo(node: string, instant: boolean) {
  const gen = ++travelGen
  clearTimers()
  const from = settledNode
  const view = archifyView()
  if (typeof view?.reveal !== 'function') {
    settledNode = node
    cameraPhase.value = 'close'
    return
  }
  const skipCinema = instant || reducedMotion() || from === node
  if (skipCinema || !from) {
    cameraPhase.value = 'close'
    view.reveal([node], closeUp(instant || reducedMotion()))
    settledNode = node
    clearEdgeFlow()
    return
  }

  cameraPhase.value = 'travel'
  const pulled = view.reveal([from, node], pairShot())
  if (!(await waitCamera(pulled, PULL_MS, gen))) return
  playEdgeFlow(from, node)
  if (!(await waitCamera(null, FLOW_LEAD_MS, gen))) return
  cameraPhase.value = 'close'
  const landed = view.reveal([node], closeUp(false))
  await waitCamera(landed, CLOSE_MS, gen)
  if (!stillCurrent(gen)) return
  settledNode = node
  clearEdgeFlow()
}

function paintNodes() {
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
}

function sync() {
  paintNodes()
  const current = currentNode.value
  if (current && current !== settledNode) {
    requestAnimationFrame(() => {
      void travelTo(current, false)
    })
  }
}

function ready() {
  const doc = frame.value?.contentDocument
  if (!doc) return
  loaded.value = true
  settledNode = null
  cameraPhase.value = ''
  travelGen += 1
  clearTimers()
  clearEdgeFlow()
  doc.documentElement.setAttribute('data-motion', 'still')
  doc.documentElement.setAttribute('data-embed', 'true')
  if (!doc.getElementById('hydro-live-style')) {
    const style = doc.createElement('style')
    style.id = 'hydro-live-style'
    style.textContent = `
      html, body, .container { width:100%!important; height:100%!important; margin:0!important; padding:0!important; min-height:0!important; background:transparent!important; }
      .diagram-container { width:100%!important; height:100%!important; padding:8px!important; margin:0!important; overflow:hidden!important; background:transparent!important; box-shadow:none!important; }
      .diagram-container > svg { width:100%!important; height:100%!important; max-height:none!important; min-width:0!important; transform-origin:0 0!important; }
      .diagram-container::before,.diagram-container::after,.share-chapter-cue,.toolbar,.header,.cards,.diagram-nav,.guided-views { display:none!important; }
      [data-node-id] { transition: opacity .2s, filter .2s; }
      [data-node-id].live-pending { opacity: .42; }
      [data-node-id] > rect { fill:#ffffff!important; stroke:#e5e5ea!important; }
      [data-node-id].live-done > rect { fill:#eaf7ee!important; stroke:#248a3d!important; }
      [data-node-id].live-current > rect { fill:#eaf3ff!important; stroke:#007aff!important; stroke-width:3px!important; filter:drop-shadow(0 0 5px #007aff33); }
      [data-node-id].live-blocked > rect { fill:#fff0f0!important; stroke:#d70015!important; }
      [data-node-id].live-from > rect { fill:#eaf3ff!important; stroke:#64b5ff!important; }
      svg.live-traveling [data-node-id].live-pending { opacity:.2; }
      svg.live-traveling [data-edge-from]:not(.live-travel) { opacity:.16; }
      path[data-edge-from].live-travel {
        stroke:#007aff!important;
        stroke-width:2.8px!important;
        stroke-linecap:round!important;
        stroke-dasharray: var(--live-len, 120);
        stroke-dashoffset: var(--live-len, 120);
        animation: live-edge-flow ${FLOW_MS}ms cubic-bezier(.22,1,.36,1) 1 both;
        filter: drop-shadow(0 0 5px #007aff66);
      }
      .live-travel-dot { fill:#007aff; filter: drop-shadow(0 0 4px #007affaa); }
      @keyframes live-edge-flow {
        from { stroke-dashoffset: var(--live-len, 120); }
        to { stroke-dashoffset: 0; }
      }
      text { font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif!important; }
      @media(prefers-reduced-motion:reduce) { * { transition:none!important; animation:none!important; } }
    `
    doc.head.appendChild(style)
  }
  paintNodes()
  requestAnimationFrame(() => {
    const node = currentNode.value
    if (node) void travelTo(node, reducedMotion())
  })
}

watch(() => [props.action, props.status, props.gateStatus, props.completedActions], sync, { deep: true })

onUnmounted(() => {
  travelGen += 1
  loaded.value = false
  clearTimers()
})
</script>

<template>
  <section class="live-workflow" :class="{ 'is-expanded': expanded }" data-test="live-workflow" :data-camera-node="currentNode || undefined" :data-camera-phase="cameraPhase || undefined">
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
