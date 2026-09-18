import { currentActionId } from '../workflow/legacyActions'

export type ToolCategory =
  | 'data'
  | 'model'
  | 'diagnosis'
  | 'optimization'
  | 'validation'
  | 'governance'
  | 'replay'
  | 'report'

export type ToolDescriptor = {
  id: string
  action: string
  nameZh: string
  category: ToolCategory
  descriptionZh: string
}

export const TOOL_CATALOG: Record<string, ToolDescriptor> = {
  A01_CHECK_DATA: {
    id: 'data.inspect',
    action: 'A01_CHECK_DATA',
    nameZh: '数据检查工具',
    category: 'data',
    descriptionZh: '检查水文数据完整性、时间范围和基础质量。',
  },
  A02_VALIDATE_SCHEME: {
    id: 'scheme.validate',
    action: 'A02_VALIDATE_SCHEME',
    nameZh: '方案校验工具',
    category: 'validation',
    descriptionZh: '检查当前模型方案是否满足实验执行条件。',
  },
  A03_FORECAST: {
    id: 'hydrology.forecast',
    action: 'A03_FORECAST',
    nameZh: '水文模型运行器',
    category: 'model',
    descriptionZh: '运行当前水文模型并生成模拟结果。',
  },
  A04_DIAGNOSE: {
    id: 'hydrology.diagnose',
    action: 'A04_DIAGNOSE',
    nameZh: '模型诊断工具',
    category: 'diagnosis',
    descriptionZh: '基于模型输出和评价指标识别主要误差特征。',
  },
  A05_OPTIMIZE: {
    id: 'calibration.optimize',
    action: 'A05_OPTIMIZE',
    nameZh: '参数优化工具',
    category: 'optimization',
    descriptionZh: '按照 Agent 设计的实验方案执行参数搜索和模型计算。',
  },
  A06_GATE: {
    id: 'validation.gate',
    action: 'A06_GATE',
    nameZh: '方案验证 Gate',
    category: 'validation',
    descriptionZh: '依据确定性评价条件判断候选方案是否可接受。',
  },
  A07_RESOLVE: {
    id: 'scheme.resolve',
    action: 'A07_RESOLVE',
    nameZh: '方案决策工具',
    category: 'governance',
    descriptionZh: '根据验证结果执行接受、保留或回退。',
  },
  A08_FREEZE: {
    id: 'scheme.freeze',
    action: 'A08_FREEZE',
    nameZh: '方案冻结工具',
    category: 'governance',
    descriptionZh: '固定最终候选方案及研究快照。',
  },
  A09_REPLAY: {
    id: 'replay.history',
    action: 'A09_REPLAY',
    nameZh: '历史回放工具',
    category: 'replay',
    descriptionZh: '使用独立历史数据验证方案表现。',
  },
  A10_EVALUATE_REPORT: {
    id: 'evaluation.report',
    action: 'A10_EVALUATE_REPORT',
    nameZh: '评价报告工具',
    category: 'report',
    descriptionZh: '汇总实验结果、指标、证据和最终结论。',
  },
}

export function toolForAction(action: string | null | undefined): ToolDescriptor | null {
  if (!action) return null
  return TOOL_CATALOG[currentActionId(action)] || null
}
