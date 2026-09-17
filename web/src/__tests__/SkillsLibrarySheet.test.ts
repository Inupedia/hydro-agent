import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SkillsLibrarySheet from '../components/SkillsLibrarySheet.vue'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    listSkills: vi.fn(),
    getSkill: vi.fn(),
    saveSkill: vi.fn(),
    validateSkill: vi.fn(),
    saveSkillBinding: vi.fn(),
    deleteSkillOverride: vi.fn(),
    copySkillFromBuiltin: vi.fn(),
    readSkillResource: vi.fn(),
    saveSkillResource: vi.fn(),
    getTaskSkillUsage: vi.fn(),
  },
}))

function portal(testId: string) {
  return document.body.querySelector(`[data-test="${testId}"]`) as HTMLElement | null
}

describe('SkillsLibrarySheet', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
    vi.mocked(api.listSkills).mockResolvedValue({
      items: [
        {
          skill_id: 'hydrologic-evidence-review',
          name: 'hydrologic-evidence-review',
          description: '诊断',
          title_zh: '误差诊断',
          purpose_zh: '解释误差模式',
          source: 'builtin',
          editable: false,
          core: true,
        },
        {
          skill_id: 'hydro-peak-timing',
          name: 'hydro-peak-timing',
          description: '洪峰时滞',
          title_zh: '洪峰时滞',
          purpose_zh: '洪峰时滞',
          source: 'user',
          editable: true,
        },
      ],
    })
    vi.mocked(api.getSkill).mockImplementation(async (skillId: string) => {
      if (skillId === 'hydro-peak-timing') {
        return {
          skill_id: 'hydro-peak-timing',
          name: 'hydro-peak-timing',
          description: '洪峰时滞',
          title_zh: '洪峰时滞',
          purpose_zh: '洪峰时滞',
          source: 'user',
          editable: true,
          skill_md: '---\nname: hydro-peak-timing\ndescription: 洪峰时滞\n---\n\n# body\n',
          body: '# body',
          metadata: { title_zh: '洪峰时滞' },
          resources: [],
        }
      }
      return {
        skill_id: 'hydrologic-evidence-review',
        name: 'hydrologic-evidence-review',
        description: '诊断',
        title_zh: '误差诊断',
        purpose_zh: '解释误差模式',
        source: 'builtin',
        editable: false,
        skill_md: '---\nname: hydrologic-evidence-review\ndescription: 诊断\n---\n\n# body\n',
        body: '# body',
        metadata: { title_zh: '误差诊断' },
        resources: [
          {
            path: 'references/metric-patterns.md',
            category: 'references',
            editable: false,
            size: 12,
          },
        ],
      }
    })
    vi.mocked(api.saveSkill).mockImplementation(async (_id, skill_md) => ({
      skill_id: 'hydro-peak-timing',
      name: 'hydro-peak-timing',
      description: '洪峰时滞',
      title_zh: '洪峰时滞',
      purpose_zh: '洪峰时滞',
      source: 'user',
      editable: true,
      skill_md,
      body: 'updated',
      metadata: { title_zh: '洪峰时滞' },
      resources: [],
    }))
    vi.mocked(api.saveSkillBinding).mockImplementation(async (skillId, stages, models) => ({
      skill_id: skillId,
      name: skillId,
      description: '洪峰时滞',
      title_zh: '洪峰时滞',
      purpose_zh: '洪峰时滞',
      source: 'user',
      editable: true,
      activation_stages: stages,
      activation_model_ids: models,
      skill_md: '---\nname: hydro-peak-timing\ndescription: 洪峰时滞\n---\n\n# body\n',
      body: '# body',
      metadata: {},
      resources: [],
    }))
    vi.mocked(api.validateSkill).mockResolvedValue({
      standard_compatible: true,
      domain_ready: false,
      errors: ['prompt Reference is missing: references/missing.md'],
      warnings: [],
    })
  })

  it('shows draft validation without saving the Skill', async () => {
    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()
    const sheet = portal('skills-library')
    ;(sheet?.querySelector('[data-test="skill-row-hydro-peak-timing"]') as HTMLButtonElement).click()
    await flushPromises()
    ;(sheet?.querySelector('[data-test="skills-validate"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(api.validateSkill).toHaveBeenCalledWith('hydro-peak-timing', expect.stringContaining('name: hydro-peak-timing'))
    expect(portal('skills-error')?.textContent).toContain('references/missing.md')
    expect(api.saveSkill).not.toHaveBeenCalled()
  })

  it('frames the skill list and shows builtin skills as a viewer', async () => {
    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()

    const sheet = portal('skills-library')
    expect(sheet?.querySelector('[data-test="skills-list"]')).toBeTruthy()
    expect(sheet?.querySelector('.skills-list-pane')).toBeTruthy()
    expect(portal('skills-readonly-hint')?.textContent).toContain('预览模式')
    expect(portal('skills-readonly-badge')?.textContent).toContain('只读预览')
    expect(portal('skills-viewer')?.textContent).toContain('hydrologic-evidence-review')
    expect(sheet?.querySelector('[data-test="skills-md-editor"]')).toBeNull()
    expect(portal('skills-save')).toBeNull()
    expect(portal('skills-readonly-footer')?.textContent).toContain('无法保存')
    expect(api.saveSkill).not.toHaveBeenCalled()
  })

  it('saves edits for user skills with a real editor', async () => {
    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()

    const sheet = portal('skills-library')
    ;(sheet?.querySelector('[data-test="skill-row-hydro-peak-timing"]') as HTMLButtonElement).click()
    await flushPromises()

    expect(portal('skills-readonly-hint')).toBeNull()
    expect(portal('skills-viewer')).toBeNull()
    const editor = sheet?.querySelector('[data-test="skills-md-editor"]') as HTMLTextAreaElement
    expect(editor).toBeTruthy()
    editor.value = `${editor.value}\nextra note\n`
    editor.dispatchEvent(new Event('input'))

    const save = sheet?.querySelector('[data-test="skills-save"]') as HTMLButtonElement
    expect(save.disabled).toBe(false)
    save.click()
    await flushPromises()

    expect(api.saveSkill).toHaveBeenCalled()
    expect(portal('skills-notice')?.textContent).toContain('已保存')
  })

  it('edits workflow binding outside SKILL.md', async () => {
    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()
    const sheet = portal('skills-library')
    ;(sheet?.querySelector('[data-test="skill-row-hydro-peak-timing"]') as HTMLButtonElement).click()
    await flushPromises()
    ;(sheet?.querySelector('[data-test="skills-tab-binding"]') as HTMLButtonElement).click()
    await flushPromises()
    const diagnosis = sheet?.querySelector('[data-test="skills-binding-diagnosis"]') as HTMLInputElement
    diagnosis.checked = true
    diagnosis.dispatchEvent(new Event('change'))
    ;(sheet?.querySelector('[data-test="skills-save"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(api.saveSkillBinding).toHaveBeenCalledWith('hydro-peak-timing', ['diagnosis'], [])
    expect(api.saveSkill).not.toHaveBeenCalled()
    expect(sheet?.textContent).toContain('结果诊断')
    expect(sheet?.textContent).toContain('参数调整')
  })

  it('create dialog stage options match LiveWorkflow labels', async () => {
    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()
    portal('skills-create')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    const create = portal('skills-create-dialog')
    ;(create?.querySelector('[data-test="skills-create-stage"]') as HTMLButtonElement).click()
    await flushPromises()
    const options = Array.from(document.querySelectorAll('[role="listbox"][aria-label="进入 Agent 的环节"] .glass-select-option-copy')).map(
      (node) => node.textContent?.trim(),
    )
    expect(options).toEqual(['任务准备', '结果诊断', '参数调整', '质量把关', '结果确认'])
    expect(create?.textContent).toContain('执行计算')
    expect(portal('skills-migrate-legacy')).toBeNull()
  })

  it('creates a new skill from the create dialog', async () => {
    vi.mocked(api.saveSkill).mockResolvedValueOnce({
      skill_id: 'hydro-new-skill',
      name: 'hydro-new-skill',
      description: '新技能',
      title_zh: '新技能',
      purpose_zh: '新技能',
      source: 'user',
      editable: true,
      skill_md: '---\nname: hydro-new-skill\ndescription: 新技能\n---\n',
      body: '',
      metadata: {},
      resources: [],
    })
    vi.mocked(api.getSkill).mockResolvedValue({
      skill_id: 'hydro-new-skill',
      name: 'hydro-new-skill',
      description: '新技能',
      title_zh: '新技能',
      purpose_zh: '新技能',
      source: 'user',
      editable: true,
      skill_md: '---\nname: hydro-new-skill\ndescription: 新技能\n---\n',
      body: '',
      metadata: {},
      resources: [],
    })

    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()
    portal('skills-create')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    const create = portal('skills-create-dialog')
    const id = create?.querySelector('[data-test="skills-create-id"]') as HTMLInputElement
    const title = create?.querySelector('[data-test="skills-create-title"]') as HTMLInputElement
    id.value = 'hydro-new-skill'
    id.dispatchEvent(new Event('input'))
    title.value = '新技能'
    title.dispatchEvent(new Event('input'))
    ;(create?.querySelector('[data-test="skills-create-submit"]') as HTMLButtonElement).click()
    await flushPromises()

    expect(api.saveSkill).toHaveBeenCalledWith(
      'hydro-new-skill',
      expect.stringContaining('name: hydro-new-skill'),
    )
    const saved = vi.mocked(api.saveSkill).mock.calls.at(-1)?.[1] || ''
    expect(saved).not.toContain('activation_stages:')
    expect(saved).not.toContain('activation_model_ids:')
    expect(api.saveSkillBinding).toHaveBeenCalledWith(
      'hydro-new-skill',
      ['diagnosis'],
      ['xaj'],
    )
  })

  it('copies a builtin skill into the user overlay', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.copySkillFromBuiltin).mockResolvedValue({
      skill_id: 'hydrologic-evidence-review',
      name: 'hydrologic-evidence-review',
      description: '诊断',
      title_zh: '误差诊断',
      purpose_zh: '解释误差模式',
      source: 'user',
      editable: true,
      skill_md: '---\nname: hydrologic-evidence-review\ndescription: 诊断\n---\n\n# body\n',
      body: '# body',
      metadata: { title_zh: '误差诊断' },
      resources: [],
    })
    vi.mocked(api.listSkills)
      .mockResolvedValueOnce({
        items: [
          {
            skill_id: 'hydrologic-evidence-review',
            name: 'hydrologic-evidence-review',
            description: '诊断',
            title_zh: '误差诊断',
            purpose_zh: '解释误差模式',
            source: 'builtin',
            editable: false,
          },
        ],
      })
      .mockResolvedValueOnce({
        items: [
          {
            skill_id: 'hydrologic-evidence-review',
            name: 'hydrologic-evidence-review',
            description: '诊断',
            title_zh: '误差诊断',
            purpose_zh: '解释误差模式',
            source: 'user',
            editable: true,
          },
        ],
      })

    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()

    const copy = portal('skills-copy-builtin') as HTMLButtonElement
    expect(copy.disabled).toBe(false)
    vi.mocked(api.getSkill).mockResolvedValue({
      skill_id: 'hydrologic-evidence-review',
      name: 'hydrologic-evidence-review',
      description: '诊断',
      title_zh: '误差诊断',
      purpose_zh: '解释误差模式',
      source: 'user',
      editable: true,
      skill_md: '---\nname: hydrologic-evidence-review\ndescription: 诊断\n---\n\n# body\n',
      body: '# body',
      metadata: { title_zh: '误差诊断' },
      resources: [],
    })
    copy.click()
    await flushPromises()

    expect(api.copySkillFromBuiltin).toHaveBeenCalledWith('hydrologic-evidence-review')
    expect(portal('skills-notice')?.textContent).toContain('已复制为用户版')
  })

  it('shows campaign skill usage for the active task', async () => {
    vi.mocked(api.getTaskSkillUsage).mockResolvedValue({
      task_id: 'task-1',
      snapshot_sha256: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
      frozen_skill_count: 1,
      invocation_count: 1,
      frozen_skills: [
        {
          skill_id: 'hydrologic-evidence-review',
          source: 'builtin',
          skill_sha256: 'a'.repeat(64),
          file_count: 1,
        },
      ],
      usage_by_skill: [
        {
          skill_id: 'hydrologic-evidence-review',
          invocation_count: 1,
          in_snapshot: true,
          snapshot_skill_sha256: 'a'.repeat(64),
          output_contracts: [{ contract: 'EvidenceInterpretation', count: 1 }],
          last_round_number: 2,
        },
      ],
      invocations: [
        {
          decision_id: 'd1',
          round_number: 2,
          action: 'A05_OPTIMIZE',
          skill_id: 'hydrologic-evidence-review',
          output_contract: 'EvidenceInterpretation',
        },
      ],
    })

    mount(SkillsLibrarySheet, { props: { open: true, taskId: 'task-1' } })
    await flushPromises()

    const openUsage = portal('skills-open-usage') as HTMLButtonElement
    expect(openUsage).toBeTruthy()
    openUsage.click()
    await flushPromises()

    expect(api.getTaskSkillUsage).toHaveBeenCalledWith('task-1')
    expect(portal('skills-usage-panel')).toBeTruthy()
    expect(portal('skills-usage-snapshot')?.textContent).toContain('Snapshot')
    expect(portal('skills-usage-row-hydrologic-evidence-review')?.textContent).toContain('EvidenceInterpretation')
  })
})
