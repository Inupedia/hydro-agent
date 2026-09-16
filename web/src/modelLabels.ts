/** Shared model display labels for the workbench UI. */

const MODEL_LABELS: Record<string, string> = {
  xaj: '新安江（XAJ）',
  gr4j: 'GR4J',
  openhydronet: 'OpenHydroNet',
}

const MODEL_SHORT: Record<string, string> = {
  xaj: '新安江',
  gr4j: 'GR4J',
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

export function paramTuningTitle(modelId: string | null | undefined): string {
  return `${modelShortLabel(modelId)}参数如何被调整`
}
