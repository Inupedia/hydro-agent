<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { actionTitle } from '../demo/stages'

const props = defineProps<{
  action?: string | null
  status?: string | null
  completedActions: string[]
  gateStatus?: string | null
  expanded?: boolean
}>()

const frame = ref<HTMLIFrameElement | null>(null)
const loaded = ref(false)

/** Align with Archify node ids in hydro-agent-xaj.workflow.html */
const ACTION_NODE: Record<string, string> = {
  A01_CHECK_DATA: 'task',
  A03_VALIDATE_SCHEME: 'task',
  A05_FORECAST: 'forecast',
  A06_DIAGNOSE: 'task',
  A07_OPTIMIZE: 'optimize',
  A08_GATE: 'gate',
  A09_RESOLVE: 'keep',
  A10_FREEZE: 'freeze',
  A11_REPLAY: 'replay',
  A12_EVALUATE_REPORT: 'results',
}

const label = computed(() => {
  if (props.status === 'failed' || props.status === 'error') return '执行受阻'
  if (props.status === 'paused') return '计算已暂停'
  return actionTitle(props.action)
})

const currentNode = computed(() => {
  const action = props.action || ''
  if (action === 'A09_RESOLVE' && props.gateStatus === 'ACCEPT') return 'freeze'
  return ACTION_NODE[action] || null
})

const doneNodes = computed(() => {
  const done = new Set<string>()
  for (const action of props.completedActions) {
    const node = ACTION_NODE[action]
    if (node) done.add(node)
  }
  // Gate KEEP/ROLLBACK lands on the keep branch in the diagram.
  if (props.gateStatus === 'KEEP' || props.gateStatus === 'ROLLBACK') done.add('keep')
  if (props.gateStatus === 'ACCEPT') done.add('freeze')
  return done
})

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
}

function ready() {
  const doc = frame.value?.contentDocument
  if (!doc) return
  loaded.value = true
  doc.documentElement.setAttribute('data-motion', 'still')
  doc.documentElement.setAttribute('data-embed', 'true')
  if (!doc.getElementById('hydro-live-style')) {
    const style = doc.createElement('style')
    style.id = 'hydro-live-style'
    style.textContent = `
      html, body, .container { width:100%!important; height:100%!important; margin:0!important; padding:0!important; min-height:0!important; background:transparent!important; }
      .diagram-container { width:100%!important; height:100%!important; padding:8px!important; margin:0!important; overflow:hidden!important; background:transparent!important; }
      .diagram-container > svg { width:100%!important; height:100%!important; max-height:none!important; min-width:0!important; }
      .diagram-container::before,.diagram-container::after,.share-chapter-cue,.toolbar,.header,.cards,.diagram-nav,.guided-views { display:none!important; }
      [data-node-id] { transition: opacity .2s, filter .2s; }
      [data-node-id].live-pending { opacity: .42; }
      [data-node-id] > rect { fill:#f4f8fc!important; stroke:#c6d6e5!important; }
      [data-node-id].live-done > rect { fill:#edf7f5!important; stroke:#7cbaaa!important; }
      [data-node-id].live-current > rect { fill:#e0efff!important; stroke:#007aff!important; stroke-width:3px!important; filter:drop-shadow(0 0 5px #007aff33); }
      [data-node-id].live-blocked > rect { fill:#fff0ed!important; stroke:#cc6457!important; }
      text { font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif!important; }
      @media(prefers-reduced-motion:reduce) { * { transition:none!important; animation:none!important; } }
    `
    doc.head.appendChild(style)
  }
  sync()
}

watch(() => [props.action, props.status, props.gateStatus, props.completedActions], sync, { deep: true })
</script>

<template>
  <section class="live-workflow" :class="{ 'is-expanded': expanded }" data-test="live-workflow">
    <div class="workflow-caption">
      <span>执行地图 <small>ARCHIFY</small></span>
      <strong aria-live="polite">{{ label }}</strong>
    </div>
    <iframe
      ref="frame"
      src="/diagrams/hydro-agent-xaj.workflow.html?theme=light&embed=1&motion=still"
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
  background: linear-gradient(140deg, #ffffffb0, #ffffff55);
  border: 1px solid #fff;
  border-radius: 22px;
  margin: 20px 0 10px;
  overflow: hidden;
  transform-origin: 50% 40%;
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
