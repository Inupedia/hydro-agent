import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SpatialHeterogeneityPanel from '../components/SpatialHeterogeneityPanel.vue'

describe('SpatialHeterogeneityPanel', () => {
  it('shows spatial facts, candidate units, and recommendation evidence', () => {
    const wrapper = mount(SpatialHeterogeneityPanel, {
      props: {
        profileStatus: 'partial',
        profile: {
          elevation: { status: 'available', mean: 420, std: 180 },
          slope: { status: 'available', mean: 12.5, std: 6.2 },
          precipitation: { status: 'available', mean: 1100, std: 240, cv: 0.22 },
          land_cover: { status: 'unknown', fractions: {} },
          soil: { status: 'unknown', fractions: {} },
          drainage: { status: 'available', area_km2: 120, stream_density_km_per_km2: 0.6 },
          evidence_quality: [],
        },
        candidates: [
          {
            candidate_id: 'lumped-001',
            kind: 'lumped',
            unit_ids: ['basin'],
            unit_count: 1,
            area_distribution_km2: [120],
            evidence_refs: ['drainage.area_km2'],
            preserved_contrasts: [],
            lost_contrasts: ['elevation'],
            complexity_notes: [],
          },
          {
            candidate_id: 'topology-004',
            kind: 'topology_subbasin',
            unit_ids: ['1', '2', '3', '4'],
            unit_count: 4,
            area_distribution_km2: [20, 30, 35, 35],
            evidence_refs: ['precipitation.cv', 'elevation.std'],
            preserved_contrasts: ['elevation', 'precipitation'],
            lost_contrasts: [],
            complexity_notes: [],
          },
        ],
        recommendation: {
          candidate_id: 'topology-004',
          rationale: '降雨和高程差异明显',
          evidence_refs: ['precipitation.cv', 'elevation.std'],
          confidence: 0.78,
          uncertainties: ['land_cover', 'soil'],
          source: 'agent',
        },
      },
    })

    expect(wrapper.text()).toContain('空间异质性')
    expect(wrapper.text()).toContain('4 个单元')
    expect(wrapper.text()).toContain('降雨和高程差异明显')
    expect(wrapper.text()).toContain('资料缺失')
    expect(wrapper.text()).toContain('precipitation.cv')
    expect(wrapper.text()).not.toContain('综合异质性评分')
  })
})
