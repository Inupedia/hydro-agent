/** Product-facing catalog for built-in Agent Skills packages. */

export const CORE_SKILL_TITLES: Record<string, string> = {
  'hydrology-data-review': '水文资料审查',
  'hydrologic-evidence-review': '水文证据审查',
  'xaj-calibration-diagnosis': '新安江率定诊断',
  'gr4j-calibration-diagnosis': 'GR4J 率定诊断',
  'hbv-calibration-diagnosis': 'HBV 率定诊断',
  'tank-calibration-diagnosis': '水箱模型率定诊断',
  'sac-sma-calibration-diagnosis': 'SAC-SMA 率定诊断',
  'calibration-experiment-design': '率定实验设计',
  'calibration-result-review': '率定结果复盘',
  'hydrology-reporting': '水文实验报告',
}

/** Retired twelve-package IDs → current six-package SSOT. */
export const LEGACY_SKILL_ALIASES: Record<string, string> = {
  'hydro-data-readiness': 'hydrology-data-review',
  'hydro-modeling-prep': 'hydrology-data-review',
  'hydro-error-diagnosis': 'hydrologic-evidence-review',
  'openhydronet-diagnosis': 'hydrologic-evidence-review',
  'xaj-calibration': 'xaj-calibration-diagnosis',
  'xaj-water-balance': 'xaj-calibration-diagnosis',
  'xaj-runoff-generation': 'xaj-calibration-diagnosis',
  'xaj-routing-diagnosis': 'xaj-calibration-diagnosis',
  'hydro-experiment-design': 'calibration-experiment-design',
  'hydro-campaign-design': 'calibration-experiment-design',
  'gbt-22482-accuracy': 'calibration-result-review',
  'hydro-report-closeout': 'hydrology-reporting',
}

export const OUTPUT_CONTRACT_LABELS: Record<string, string> = {
  EvidenceInterpretation: '证据解读',
  DiagnosisHypothesis: '诊断假设',
  CalibrationPlan: '实验计划',
  ExperimentReview: '结果复盘',
  AgentDecision: '行动决策',
}

export function canonicalSkillId(skillId: string): string {
  return LEGACY_SKILL_ALIASES[skillId] || skillId
}

export function skillTitle(skillId: string, fallback?: string | null): string {
  const canonical = canonicalSkillId(skillId)
  return CORE_SKILL_TITLES[canonical] || fallback || skillId
}

export function outputContractLabel(contract?: string | null): string | null {
  if (!contract) return null
  return OUTPUT_CONTRACT_LABELS[contract] || contract
}
