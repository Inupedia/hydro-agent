/** Preserve v1 evidence labels while resolving their v2 presentation nodes. */
export const LEGACY_TO_CURRENT: Record<string, string> = {
  A03_VALIDATE_SCHEME: 'A02_VALIDATE_SCHEME',
  A05_FORECAST: 'A03_FORECAST',
  A06_DIAGNOSE: 'A04_DIAGNOSE',
  A07_OPTIMIZE: 'A05_OPTIMIZE',
  A08_GATE: 'A06_GATE',
  A09_RESOLVE: 'A07_RESOLVE',
  A10_FREEZE: 'A08_FREEZE',
  A11_REPLAY: 'A09_REPLAY',
  A12_EVALUATE_REPORT: 'A10_EVALUATE_REPORT',
}

export const CURRENT_TO_LEGACY: Record<string, string> = Object.fromEntries(
  Object.entries(LEGACY_TO_CURRENT).map(([legacy, current]) => [current, legacy]),
)

export function currentActionId(action: string | null | undefined): string | null {
  if (!action) return null
  return LEGACY_TO_CURRENT[action] || action
}
