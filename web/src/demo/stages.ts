/** Audience-facing stage grouping for live actions. */

import { WORKFLOW, type AudienceStageId } from '../generated/workflow'

export type { AudienceStageId }

export type AudienceStage = {
  id: AudienceStageId
  label: string
}

export const AUDIENCE_STAGES: AudienceStage[] = WORKFLOW.display_stages.map((stage) => ({
  id: stage.id,
  label: stage.label,
}))

function actionMeta(action: string | null | undefined) {
  if (!action) return null
  return WORKFLOW.actions[action as keyof typeof WORKFLOW.actions] || null
}

export function stageForAction(action: string | null | undefined): AudienceStageId | null {
  const item = actionMeta(action)
  return item ? (item.display_stage as AudienceStageId) : null
}

export function actionTitle(action: string | null | undefined): string {
  if (!action) return '等待下一步'
  return actionMeta(action)?.title_running_zh || action
}

export function actionDoneTitle(action: string | null | undefined): string {
  if (!action) return '已完成一步'
  return actionMeta(action)?.title_done_zh || actionTitle(action)
}

export function actionExplain(action: string | null | undefined): string {
  if (!action) return '系统正在决定下一步要做什么。'
  return actionMeta(action)?.explain_zh || '系统正在执行该步骤。'
}

export type StageStatus = 'pending' | 'active' | 'done' | 'skipped' | 'blocked'

export function stageStatuses(
  timelineActions: string[],
  currentAction: string | null,
  runStatus: string | null,
): Record<AudienceStageId, StageStatus> {
  const seen = new Set(timelineActions.map((a) => stageForAction(a)).filter(Boolean) as AudienceStageId[])
  const current = stageForAction(currentAction)
  const failed = runStatus === 'failed' || runStatus === 'error'
  const completed = runStatus === 'completed'

  const out = {} as Record<AudienceStageId, StageStatus>
  for (const stage of AUDIENCE_STAGES) {
    const stageIndex = AUDIENCE_STAGES.findIndex((s) => s.id === stage.id)
    const currentIndex = current ? AUDIENCE_STAGES.findIndex((s) => s.id === current) : -1
    if (failed && current === stage.id) {
      out[stage.id] = 'blocked'
    } else if (current === stage.id && !completed) {
      out[stage.id] = 'active'
    } else if (completed) {
      out[stage.id] = seen.has(stage.id) ? 'done' : 'skipped'
    } else if (seen.has(stage.id) && stage.id !== current) {
      out[stage.id] = 'done'
    } else if (currentIndex > stageIndex) {
      out[stage.id] = seen.has(stage.id) ? 'done' : 'skipped'
    } else {
      out[stage.id] = 'pending'
    }
  }
  return out
}

export function gateDecisionZh(
  status: string | null | undefined,
  extras?: {
    reasons?: unknown
    metrics?: Record<string, unknown> | null
  },
): {
  title: string
  reason: string
  tone: 'ok' | 'keep' | 'rollback' | 'unknown'
} {
  const reasonCodes = Array.isArray(extras?.reasons)
    ? extras!.reasons.map(String)
    : typeof extras?.reasons === 'string'
      ? extras.reasons.split(',').map((s) => s.trim()).filter(Boolean)
      : []
  const metrics = extras?.metrics || {}
  const base = typeof metrics.base_primary === 'number' ? metrics.base_primary : null
  const cand = typeof metrics.candidate_primary === 'number' ? metrics.candidate_primary : null
  const delta = typeof metrics.primary_delta === 'number' ? metrics.primary_delta : null
  const metricHint =
    base != null && cand != null
      ? `（主指标 ${base.toFixed(2)} → ${cand.toFixed(2)}${delta != null ? `，Δ=${delta.toFixed(2)}` : ''}）`
      : ''

  const reasonText = (() => {
    if (reasonCodes.some((r) => r.includes('insufficient_absolute_skill'))) {
      return `候选方案相对有改善，但绝对技巧仍低于门槛，因此不采纳${metricHint}。`
    }
    if (reasonCodes.some((r) => r.includes('insufficient_primary_delta'))) {
      return `本次调整没有达到预设的改进幅度，因此继续使用原方案${metricHint}。`
    }
    if (reasonCodes.some((r) => r.includes('lead_guardrail'))) {
      return '某个预见期指标明显变差，触发了安全限制。'
    }
    if (reasonCodes.some((r) => r.includes('high_flow_guardrail'))) {
      return '高流量误差变差超过允许范围，触发了安全限制。'
    }
    return null
  })()

  switch (status) {
    case 'ACCEPT':
      return {
        title: '采用新方案',
        reason: reasonText || `候选方案在验证窗口上达到了改进要求，且绝对技巧过线${metricHint}。`,
        tone: 'ok',
      }
    case 'KEEP':
      return {
        title: '保留原方案',
        reason: reasonText || `本次调整没有达到预设要求，因此继续使用原方案${metricHint}。`,
        tone: 'keep',
      }
    case 'ROLLBACK':
      return {
        title: '回退到原方案',
        reason: reasonText || '候选方案触发了安全限制，系统回退到原来的方案。',
        tone: 'rollback',
      }
    default:
      return {
        title: '本次无法形成有效结论',
        reason: '还没有可用的检查记录，或检查未完成。',
        tone: 'unknown',
      }
  }
}

export const BASIN_LABELS: Record<string, string> = {
  yaogu: '腰古',
}

export function basinLabel(basinId: string): string {
  return BASIN_LABELS[basinId] || basinId
}

export function forcingLabel(mode: 'R' | 'F'): string {
  return mode === 'R' ? '实测气象驱动资料' : '预报气象驱动资料'
}

export function providerErrorZh(error: string | null | undefined): string | null {
  if (!error) return null
  if (error.includes('503') || error.includes('429') || error.includes('502')) {
    return '模型服务暂时繁忙，请稍后重试继续（SiliconFlow HTTP 过载）。'
  }
  if (error.includes('timed out') || error.includes('connection failed')) {
    return '模型服务连接失败或超时，请检查网络后重试。'
  }
  if (error.includes('401') || error.includes('403')) {
    return '模型服务鉴权失败，请检查 API Key。'
  }
  return `模型服务异常：${error}`
}
