import { expect, it } from 'vitest'
import { hydrographTitleZh } from '../chartTheme'

it('uses Chinese titles even when the payload still has English copy', () => {
  expect(hydrographTitleZh({ kind: 'calibration' })).toBe('观测与基线 / 候选 · 率定窗口')
  expect(hydrographTitleZh({ kind: 'independent_test', calibrated: true })).toBe('观测与冻结方案 · 独立检验')
  expect(hydrographTitleZh({ gate_status: 'KEEP' })).toBe('观测与冻结方案 · 独立检验（维持原方案）')
  expect(hydrographTitleZh({ title: 'Observed vs Frozen Scheme · Independent Test' })).toBe(
    '观测与冻结方案 · 独立检验',
  )
})
