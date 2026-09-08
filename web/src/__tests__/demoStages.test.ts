import { describe, expect, it } from 'vitest'
import { actionTitle, gateDecisionZh, stageForAction, stageStatuses } from '../demo/stages'

describe('demo stage mapping', () => {
  it('maps actions to audience stages and keep decision copy', () => {
    expect(stageForAction('A05_FORECAST')).toBe('forecast')
    expect(actionTitle('A08_GATE')).toContain('检查')
    expect(gateDecisionZh('KEEP').title).toBe('保留原方案')
    expect(gateDecisionZh('KEEP').tone).toBe('keep')
    const statuses = stageStatuses(['A01_CHECK_DATA', 'A05_FORECAST'], 'A07_OPTIMIZE', 'running')
    expect(statuses.data).toBe('done')
    expect(statuses.forecast).toBe('done')
    expect(statuses.gate).toBe('active')
    const finished = stageStatuses(['A01_CHECK_DATA', 'A05_FORECAST', 'A12_EVALUATE_REPORT'], null, 'completed')
    expect(finished.data).toBe('done')
    expect(finished.forecast).toBe('done')
    expect(finished.gate).toBe('skipped')
    expect(finished.report).toBe('done')
  })
})
