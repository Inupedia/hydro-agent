import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useExperienceStore } from './experience'

function response(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('experience store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads summary without inventing values', async () => {
    const payload = {
      current_version: 4,
      current_skill_hash: 'abc',
      status: 'converging',
      active_count: 12,
      high_confidence_count: 7,
      candidate_count: 1,
      version_count: 4,
      reason: 'recent_window_is_dominated_by_state_optimization',
    }
    vi.stubGlobal('fetch', vi.fn(async () => response(payload)))

    const store = useExperienceStore()
    await store.loadSummary()

    expect(store.summary).toEqual(payload)
    expect(fetch).toHaveBeenCalledWith(
      '/api/experience/summary',
      expect.objectContaining({
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      }),
    )
  })

  it('loads evolution timeline as returned by the server', async () => {
    const payload = [
      {
        event_id: 9,
        task_id: 'task-32',
        experience_id: 'EXP-XAJ-0018',
        event_type: 'REINFORCE',
        from_revision: 3,
        to_revision: 4,
        version_before: 3,
        version_after: 3,
        reason: 'routing adjustment worked again',
        evidence_refs: [
          {
            task_id: 'task-32',
            experiment_id: 'experiment-7',
            evidence_id: 'evidence-7',
          },
        ],
        created_at: '2026-09-18T04:00:00Z',
      },
    ]
    vi.stubGlobal('fetch', vi.fn(async () => response(payload)))

    const store = useExperienceStore()
    await store.loadTimeline()

    expect(store.timeline).toEqual(payload)
    expect(store.timeline[0].experience_id).toBe('EXP-XAJ-0018')
    expect(store.timeline[0].evidence_refs[0].evidence_id).toBe('evidence-7')
  })
})
