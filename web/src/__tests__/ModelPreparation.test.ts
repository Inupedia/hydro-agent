import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ModelPreparation from '../components/ModelPreparation.vue'
import { api } from '../api/client'

function portal(testId: string) {
  return document.body.querySelector(`[data-test="${testId}"]`) as HTMLElement | null
}

vi.mock('../api/client', () => ({
  api: {
    getBasin: vi.fn(),
    listModelPlans: vi.fn(),
    getModelPlan: vi.fn(),
    createModelPlan: vi.fn(),
    renameModelPlan: vi.fn(),
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

afterEach(() => {
  document.body.querySelectorAll('.glass-dialog-backdrop').forEach((node) => node.remove())
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

  it('opens bulk plan management in the shared glass dialog', async () => {
    const wrapper = mount(ModelPreparation, { props: { basinId: 'yaogu' } })
    await flushPromises()
    expect(portal('bulk-plan-manager')).toBeNull()
    await wrapper.get('[data-test="manage-plans"]').trigger('click')
    await flushPromises()
    const dialog = portal('bulk-plan-manager')
    expect(dialog).not.toBeNull()
    expect(dialog?.parentElement).toBe(document.body)
    expect(dialog?.classList.contains('glass-dialog-backdrop')).toBe(true)
    expect(dialog?.textContent).toContain('批量管理')
    wrapper.unmount()
  })

  it('opens the build dialog instead of appending the modeling flow', async () => {
    const created = {
      plan_id: 'plan-new',
      basin_id: 'yaogu',
      model_mode: 'lumped',
      status: 'running',
      stages: [
        { code: 'M01_CHECK_MATERIALS', label: '检查并确认资料', status: 'completed', detail: '' },
        { code: 'M02_DELINEATE', label: '划分计算单元', status: 'running', detail: '' },
        { code: 'M03_REVIEW_BOUNDARY', label: '复核出口与流域边界', status: 'pending', detail: '' },
        { code: 'M04_BUILD_INPUTS', label: '构建面雨量与模型输入', status: 'pending', detail: '' },
        { code: 'M05_VALIDATE_PLAN', label: '校验并保存完整方案', status: 'pending', detail: '' },
      ],
    }
    vi.mocked(api.createModelPlan).mockResolvedValue(created as never)
    vi.mocked(api.listModelPlans).mockResolvedValue([created] as never)
    vi.mocked(api.getModelPlan).mockResolvedValue(created as never)
    const wrapper = mount(ModelPreparation, { props: { basinId: 'yaogu' } })
    await flushPromises()
    expect(portal('build-plan-dialog')).toBeNull()
    await wrapper.get('[data-test="build-plan"]').trigger('click')
    await flushPromises()
    const dialog = portal('build-plan-dialog')
    expect(dialog).not.toBeNull()
    expect(dialog?.parentElement).toBe(document.body)
    expect(dialog?.textContent).toContain('划分计算单元')
    expect(dialog?.textContent).toContain('检查并确认资料')
    expect(dialog?.textContent).not.toContain('构建面雨量与模型输入')
    expect(dialog?.textContent).not.toContain('校验并保存完整方案')
    expect(dialog?.querySelector('[data-active="true"]')).not.toBeNull()
    expect(wrapper.find('[data-test="model-steps"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="gis-map"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="plan-summary"]').text()).toContain('建模中')
    wrapper.unmount()
  })

  it('keeps boundary review and confirm actions inside the build dialog', async () => {
    const review = {
      plan_id: 'plan-review',
      basin_id: 'yaogu',
      model_mode: 'lumped',
      status: 'awaiting_review',
      boundary_hash: 'hash-1',
      boundary: { dem_area_km2: 12.34, note: '核对出口' },
      unit_count: 1,
      stages: [
        { code: 'M03_REVIEW_BOUNDARY', label: '复核出口与流域边界', status: 'awaiting_review', detail: '请确认' },
      ],
    }
    vi.mocked(api.listModelPlans).mockResolvedValue([review] as never)
    vi.mocked(api.getModelPlan).mockResolvedValue(review as never)
    vi.mocked(api.confirmBoundary).mockResolvedValue({ ...review, status: 'running' } as never)
    const wrapper = mount(ModelPreparation, { props: { basinId: 'yaogu', selectedId: review.plan_id } })
    await flushPromises()
    const dialog = portal('build-plan-dialog')
    expect(dialog).not.toBeNull()
    expect(dialog?.textContent).toContain('我已确认出口位置、面积与单元划分')
    expect(dialog?.textContent).toContain('12.34')
    const boundaryStep = dialog?.querySelector('[data-step="M03_REVIEW_BOUNDARY"]')
    expect(boundaryStep?.querySelector('[data-test="boundary-step-body"]')).not.toBeNull()
    expect(boundaryStep?.querySelector('[data-test="review-check"]')).not.toBeNull()
    const confirm = dialog?.querySelector<HTMLButtonElement>('[data-test="confirm-boundary"]')
    expect(confirm?.disabled).toBe(true)
    dialog?.querySelector<HTMLInputElement>('[data-test="review-check"]')?.click()
    await flushPromises()
    expect(dialog?.querySelector<HTMLButtonElement>('[data-test="confirm-boundary"]')?.disabled).toBe(false)
    dialog?.querySelector<HTMLButtonElement>('[data-test="confirm-boundary"]')?.click()
    await flushPromises()
    expect(api.confirmBoundary).toHaveBeenCalledWith('plan-review', 'hash-1')
    wrapper.unmount()
  })
})
