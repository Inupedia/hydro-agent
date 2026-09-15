import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SkillsLibrarySheet from '../components/SkillsLibrarySheet.vue'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    listSkills: vi.fn(),
    getSkill: vi.fn(),
    saveSkill: vi.fn(),
    deleteSkillOverride: vi.fn(),
    readSkillResource: vi.fn(),
    saveSkillResource: vi.fn(),
  },
}))

function portal(testId: string) {
  return document.body.querySelector(`[data-test="${testId}"]`) as HTMLElement | null
}

describe('SkillsLibrarySheet', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.mocked(api.listSkills).mockResolvedValue({
      items: [
        {
          skill_id: 'hydro-error-diagnosis',
          name: 'hydro-error-diagnosis',
          description: '诊断',
          title_zh: '误差诊断',
          purpose_zh: '解释误差模式',
          source: 'builtin',
          editable: false,
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
        skill_id: 'hydro-error-diagnosis',
        name: 'hydro-error-diagnosis',
        description: '诊断',
        title_zh: '误差诊断',
        purpose_zh: '解释误差模式',
        source: 'builtin',
        editable: false,
        skill_md: '---\nname: hydro-error-diagnosis\ndescription: 诊断\n---\n\n# body\n',
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
  })

  it('frames the skill list and shows builtin skills as a viewer', async () => {
    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()

    const sheet = portal('skills-library')
    expect(sheet?.querySelector('[data-test="skills-list"]')).toBeTruthy()
    expect(sheet?.querySelector('.skills-list-pane')).toBeTruthy()
    expect(portal('skills-readonly-hint')?.textContent).toContain('预览模式')
    expect(portal('skills-readonly-badge')?.textContent).toContain('只读预览')
    expect(portal('skills-viewer')?.textContent).toContain('hydro-error-diagnosis')
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
    expect(saved).toContain('activation_stages: "diagnosis|experiment"')
    expect(saved).toContain('activation_model_ids: "xaj"')
  })
})
