import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CaseSkillUsageDialog from '../components/CaseSkillUsageDialog.vue'

const mocks = vi.hoisted(() => ({ getTaskSkillUsage: vi.fn(), getAgentLog: vi.fn() }))
vi.mock('../api/client', () => ({ api: mocks }))

afterEach(() => { document.body.innerHTML = '' })

describe('CaseSkillUsageDialog', () => {
  it('summarizes Skills and Tools together', async () => {
    mocks.getTaskSkillUsage.mockResolvedValue({
      task_id: 'task-1', snapshot_sha256: 'a'.repeat(64), frozen_skill_count: 2, invocation_count: 3,
      frozen_skills: [], usage_by_skill: [{ skill_id: 'hydrologic-evidence-review', invocation_count: 3, in_snapshot: true, output_contracts: [], last_round_number: 2 }], invocations: [],
    })
    mocks.getAgentLog.mockResolvedValue({ task_id: 'task-1', rounds: [{ tool_calls: [
      { action: 'A05_OPTIMIZE', tool_id: 'calibration.optimize', tool_name_zh: '参数优化工具', category: 'optimization', status: 'completed', metrics: { model_evaluations: 48 } },
      { action: 'A06_GATE', tool_id: 'validation.gate', tool_name_zh: '方案验证 Gate', category: 'validation', status: 'completed', metrics: {} },
    ] }] })
    const wrapper = mount(CaseSkillUsageDialog, { props: { open: true, taskId: 'task-1' } })
    await flushPromises()
    const dialog = document.body.querySelector('[data-test="case-skill-usage"]')
    expect(dialog?.textContent).toContain('Agent 能力调用')
    expect(dialog?.textContent).toContain('本次调用的技能')
    expect(dialog?.textContent).toContain('本次调用的执行工具')
    expect(dialog?.textContent).toContain('48')
    const toolsTab = dialog?.querySelector<HTMLButtonElement>('#case-tools-tab')
    toolsTab?.click()
    await flushPromises()
    expect(dialog?.textContent).toContain('参数优化工具')
    expect(dialog?.textContent).toContain('方案验证 Gate')
    wrapper.unmount()
  })
})
