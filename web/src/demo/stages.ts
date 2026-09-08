/** Audience-facing stage grouping for live actions. */

export type AudienceStageId = 'data' | 'forecast' | 'gate' | 'report'

export type AudienceStage = {
  id: AudienceStageId
  label: string
}

export const AUDIENCE_STAGES: AudienceStage[] = [
  { id: 'data', label: '准备资料' },
  { id: 'forecast', label: '计算预测' },
  { id: 'gate', label: '检查与改进' },
  { id: 'report', label: '形成结果' },
]

const ACTION_STAGE: Record<string, AudienceStageId> = {
  A01_CHECK_DATA: 'data',
  A03_VALIDATE_SCHEME: 'data',
  A05_FORECAST: 'forecast',
  A06_DIAGNOSE: 'gate',
  A07_OPTIMIZE: 'gate',
  A08_GATE: 'gate',
  A09_RESOLVE: 'gate',
  A10_FREEZE: 'report',
  A11_REPLAY: 'report',
  A12_EVALUATE_REPORT: 'report',
}

export const ACTION_TITLE_ZH: Record<string, string> = {
  A01_CHECK_DATA: '正在检查资料',
  A03_VALIDATE_SCHEME: '正在校验方案',
  A05_FORECAST: '正在计算预测',
  A06_DIAGNOSE: '正在诊断预报误差',
  A07_OPTIMIZE: '正在尝试调整参数',
  A08_GATE: '正在检查是否达到要求',
  A09_RESOLVE: '正在落实检查结论',
  A10_FREEZE: '正在确定采用方案',
  A11_REPLAY: '正在做历史资料回放',
  A12_EVALUATE_REPORT: '正在整理结果与报告',
}

export const ACTION_EXPLAIN_ZH: Record<string, string> = {
  A01_CHECK_DATA: '确认本次计算需要的气象与流量资料是否齐全。',
  A03_VALIDATE_SCHEME: '确认基础计算方案可以投入运行。',
  A05_FORECAST: '用当前方案计算未来几天的流量。',
  A06_DIAGNOSE: '对照观测，判断误差更可能来自哪里。',
  A07_OPTIMIZE: '在有限范围内尝试更合适的参数。',
  A08_GATE: '比较候选方案与原方案，看是否值得更换。',
  A09_RESOLVE: '根据检查结果决定采用、保留或回退。',
  A10_FREEZE: '把当前采用方案锁定，供后续回放与报告使用。',
  A11_REPLAY: '用历史资料把锁定方案再跑一遍，方便对照。',
  A12_EVALUATE_REPORT: '汇总指标、说明与可下载产物。',
}

export function stageForAction(action: string | null | undefined): AudienceStageId | null {
  if (!action) return null
  return ACTION_STAGE[action] ?? null
}

export function actionTitle(action: string | null | undefined): string {
  if (!action) return '等待下一步'
  return ACTION_TITLE_ZH[action] || action
}

export function actionDoneTitle(action: string | null | undefined): string {
  if (!action) return '已完成一步'
  const map: Record<string, string> = {
    A01_CHECK_DATA: '检查了资料',
    A03_VALIDATE_SCHEME: '校验了方案',
    A05_FORECAST: '完成了流量预测',
    A06_DIAGNOSE: '诊断了预报误差',
    A07_OPTIMIZE: '尝试调整了参数',
    A08_GATE: '检查了是否达到要求',
    A09_RESOLVE: '落实了检查结论',
    A10_FREEZE: '确定了采用方案',
    A11_REPLAY: '完成了历史资料回放',
    A12_EVALUATE_REPORT: '整理了结果与报告',
  }
  return map[action] || actionTitle(action)
}

export function actionExplain(action: string | null | undefined): string {
  if (!action) return '系统正在决定下一步要做什么。'
  return ACTION_EXPLAIN_ZH[action] || '系统正在执行该步骤。'
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
      // Never paint skipped work as success.
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

export function gateDecisionZh(status: string | null | undefined): {
  title: string
  reason: string
  tone: 'ok' | 'keep' | 'rollback' | 'unknown'
} {
  switch (status) {
    case 'ACCEPT':
      return {
        title: '采用新方案',
        reason: '候选方案在验证窗口上达到了预设的改进要求。',
        tone: 'ok',
      }
    case 'KEEP':
      return {
        title: '保留原方案',
        reason: '本次调整没有达到预设的改进要求，因此继续使用原方案。',
        tone: 'keep',
      }
    case 'ROLLBACK':
      return {
        title: '回退到原方案',
        reason: '候选方案触发了安全限制，系统回退到原来的方案。',
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
  camels_13235000: 'Lowman（Snake River 支流）',
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
