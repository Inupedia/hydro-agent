/** Shared model display labels for the workbench UI. */

const MODEL_LABELS: Record<string, string> = {
  xaj: '新安江（XAJ）',
  gr4j: 'GR4J',
  hbv: 'HBV-light',
  tank: '三层 Tank + Nash',
  'sac-sma': 'SAC-SMA（NOAA-OWP）',
  openhydronet: 'OpenHydroNet',
}

const MODEL_SHORT: Record<string, string> = {
  xaj: '新安江',
  gr4j: 'GR4J',
  hbv: 'HBV',
  tank: '水箱',
  'sac-sma': 'SAC-SMA（NOAA-OWP）',
  openhydronet: 'OpenHydroNet',
}

export function modelLabel(modelId: string | null | undefined): string {
  const id = String(modelId || '').trim()
  if (!id) return '水文模型'
  return MODEL_LABELS[id] || id.toUpperCase()
}

export function modelShortLabel(modelId: string | null | undefined): string {
  const id = String(modelId || '').trim()
  if (!id) return '模型'
  return MODEL_SHORT[id] || id.toUpperCase()
}

export type WorkbenchModelId = 'xaj' | 'gr4j' | 'hbv' | 'tank' | 'sac-sma' | 'openhydronet'

const LIVE_MODEL_IDS = new Set<string>(['xaj', 'gr4j', 'hbv', 'tank', 'sac-sma'])
const WORKBENCH_MODEL_IDS = new Set<string>([...LIVE_MODEL_IDS, 'openhydronet'])

export function asWorkbenchModelId(
  modelId: string | null | undefined,
  fallback: WorkbenchModelId = 'xaj',
): WorkbenchModelId {
  const id = String(modelId || '').trim()
  return WORKBENCH_MODEL_IDS.has(id) ? (id as WorkbenchModelId) : fallback
}

export function isLiveHydrologyModel(modelId: string | null | undefined): boolean {
  return LIVE_MODEL_IDS.has(String(modelId || '').trim())
}

export function paramTuningTitle(modelId: string | null | undefined): string {
  return `${modelShortLabel(modelId)}参数如何被调整`
}
