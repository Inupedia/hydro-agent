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
  it('shows checking copy before the basin catalog returns', async () => {
    let resolveBasin: (value: unknown) => void = () => undefined
    vi.mocked(api.getBasin).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveBasin = resolve
        }) as never,
    )
    vi.mocked(api.listModelPlans).mockResolvedValue([] as never)
    const wrapper = mount(ModelPreparation, { props: { basinId: 'yaogu' } })
    await Promise.resolve()
    expect(wrapper.get('[data-test="build-plan"]').text()).toBe('正在检查资料…')
    expect(wrapper.get('[data-test="build-plan"]').attributes('disabled')).toBeDefined()
    resolveBasin({
      basin_id: 'yaogu',
      label: '腰古',
      ready_for_build: true,
      materials: { hydro: true, dem: true, gis: true },
    })
    await flushPromises()
    expect(wrapper.get('[data-test="build-plan"]').text()).toBe('新建流域模型')
    wrapper.unmount()
  })

  it('says materials are incomplete only after a successful catalog check', async () => {
    vi.mocked(api.getBasin).mockResolvedValue({
      basin_id: 'yaogu',
      label: '腰古',
      ready_for_build: false,
      materials: { hydro: false, dem: false, gis: false },
    } as never)
    const wrapper = mount(ModelPreparation, { props: { basinId: 'yaogu' } })
    await flushPromises()
    expect(wrapper.get('[data-test="build-plan"]').text()).toBe('本地资料不完整')
    wrapper.unmount()
  })

  it('does not call a fetch error incomplete materials', async () => {
    vi.mocked(api.getBasin).mockRejectedValue(new Error('流域目录暂时无法写入'))
    const wrapper = mount(ModelPreparation, { props: { basinId: 'yaogu' } })
    await flushPromises()
    expect(wrapper.get('[data-test="build-plan"]').text()).toBe('无法读取流域资料')
    expect(wrapper.text()).toContain('重新检查')
    wrapper.unmount()
  })

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
