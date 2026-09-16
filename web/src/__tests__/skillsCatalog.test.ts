import { describe, expect, it } from 'vitest'
import { canonicalSkillId, outputContractLabel, skillTitle } from '../skills/catalog'

describe('skills catalog', () => {
  it('maps legacy ids and product titles', () => {
    expect(canonicalSkillId('xaj-water-balance')).toBe('xaj-calibration-diagnosis')
    expect(skillTitle('xaj-water-balance')).toBe('新安江率定诊断')
    expect(skillTitle('hydrologic-evidence-review')).toBe('水文证据审查')
    expect(outputContractLabel('CalibrationPlan')).toBe('实验计划')
  })
})
