import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import ExperienceEvolutionPanel from '../components/ExperienceEvolutionPanel.vue'

const mocks = vi.hoisted(() => ({
  getExperienceSummary: vi.fn(),
  listExperienceEntries: vi.fn(),
  listExperienceEvolution: vi.fn(),
  listExperienceVersions: vi.fn(),
  getExperienceRegression: vi.fn(),
  getExperienceEntry: vi.fn(),
  getExperienceVersionDiff: vi.fn(),
}))

vi.mock('../api/client', () => ({ api: mocks }))

describe('ExperienceEvolutionPanel', () => {
  it('renders version, convergence, evidence provenance and structural diff', async () => {
    mocks.getExperienceSummary.mockResolvedValue({
      current_version: 4,
      current_skill_hash: 'e'.repeat(64),
      status: 'converging',
      active_count: 2,
      high_confidence_count: 1,
      candidate_count: 1,
      version_count: 4,
      reason: 'recent_window_is_dominated_by_state_optimization',
    })
    mocks.listExperienceEntries.mockResolvedValue([{
      experience_id: 'EXP-XAJ-0018',
      revision: 3,
      category: 'model',
      scope: { model_ids: ['xaj'], basin_ids: ['yaogu'] },
      pattern: { peak_bias: 'negative' },
      decision: { prefer_param_groups: ['routing'] },
      supporting_evidence: [{ task_id: 'task-1', evidence_id: 'ev-1' }],
      contradicting_evidence: [],
      confidence: 0.86,
      status: 'active',
    }])
    mocks.listExperienceEvolution.mockResolvedValue([{
      event_id: 1,
      task_id: 'task-1',
      experience_id: 'EXP-XAJ-0018',
      event_type: 'REINFORCE',
      reason: 'routing adjustment repeated',
      evidence_refs: [],
      created_at: '2026-09-18T00:00:00Z',
    }])
    mocks.listExperienceVersions.mockResolvedValue([{
      version: 4,
      parent_version: 3,
      status: 'promoted',
      skill_hash: 'e'.repeat(64),
      manifest: {},
      regression: { passed: true },
      created_at: '2026-09-18T00:00:00Z',
    }])
    mocks.getExperienceRegression.mockResolvedValue({ items: [] })
    mocks.getExperienceEntry.mockResolvedValue({
      experience_id: 'EXP-XAJ-0018',
      revision: 3,
      category: 'model',
      scope: { model_ids: ['xaj'], basin_ids: ['yaogu'] },
      pattern: { peak_bias: 'negative' },
      decision: { prefer_param_groups: ['routing'] },
      supporting_evidence: [{ task_id: 'task-1', evidence_id: 'ev-1' }],
      contradicting_evidence: [],
      confidence: 0.86,
      status: 'active',
      revisions: [],
    })
    mocks.getExperienceVersionDiff.mockResolvedValue({
      version: 4,
      parent_version: 3,
      added: ['EXP-XAJ-0018'],
      modified: [],
      superseded: [],
      split: [],
      merged: [],
    })

    const wrapper = mount(ExperienceEvolutionPanel, {
      global: { plugins: [createPinia()] },
      props: { initialExperienceId: 'EXP-XAJ-0018' },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Experience Skill v4')
    expect(wrapper.text()).toContain('趋于收敛')
    expect(wrapper.text()).toContain('EXP-XAJ-0018')
    expect(wrapper.text()).toContain('支持证据')
    expect(wrapper.text()).toContain('ev-1')
    expect(wrapper.get('[data-test="experience-version-diff"]').text()).toContain('新增')
  })
})
