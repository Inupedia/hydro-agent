import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ModelPreparation from '../components/ModelPreparation.vue'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    getBasin: vi.fn(),
    listModelPlans: vi.fn(),
    getModelPlan: vi.fn(),
    createModelPlan: vi.fn(),
    confirmBoundary: vi.fn(),
    deleteModelPlan: vi.fn(),
  },
}))

const plan = {
  plan_id: 'plan-aaaaaaaaaaaa',
  basin_id: 'yaogu',
  model_mode: 'lumped',
  status: 'ready',
  stages: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getBasin).mockResolvedValue({
    basin_id: 'yaogu',
    label: '腰古',
    ready_for_build: true,
    materials: { hydro: true, dem: true, gis: true },
  } as never)
  vi.mocked(api.listModelPlans).mockResolvedValue([plan] as never)
})

describe('ModelPreparation', () => {
  it('deletes a reused plan and clears the selection', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.mocked(api.deleteModelPlan).mockResolvedValue(undefined)
    vi.mocked(api.listModelPlans).mockResolvedValueOnce([plan] as never).mockResolvedValueOnce([] as never)
    const wrapper = mount(ModelPreparation, { props: { basinId: 'yaogu', selectedId: plan.plan_id } })
    await flushPromises()
    const emitted = wrapper.emitted('selected') || []
    expect(emitted.at(-1)?.[0]).toMatchObject({ plan_id: plan.plan_id })
    await wrapper.get('[data-test="delete-plan"]').trigger('click')
    await flushPromises()
    expect(api.deleteModelPlan).toHaveBeenCalledWith(plan.plan_id)
    expect(wrapper.emitted('selected')?.at(-1)?.[0]).toBeNull()
    wrapper.unmount()
  })
})
