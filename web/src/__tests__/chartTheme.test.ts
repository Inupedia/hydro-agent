import { expect, it } from 'vitest'
import { hydrographTitleZh } from '../chartTheme'

it('uses Chinese conclusion titles even when the payload still has English copy', () => {
  expect(hydrographTitleZh({ kind: 'calibration' })).toBe('率定窗里，观测、基准与候选差在哪里')
  expect(hydrographTitleZh({ kind: 'independent_test', calibrated: true })).toBe(
    '独立检验：最终方案是否贴住观测',
  )
  expect(hydrographTitleZh({ gate_status: 'KEEP' })).toBe('维持原方案后，过程线仍与观测对照')
  expect(hydrographTitleZh({ title: 'Observed vs Frozen Scheme · Independent Test' })).toBe(
    '独立检验：最终方案是否贴住观测',
  )
})
