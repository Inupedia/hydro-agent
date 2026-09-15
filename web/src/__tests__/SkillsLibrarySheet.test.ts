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
          editable: true,
        },
      ],
    })
    vi.mocked(api.getSkill).mockResolvedValue({
      skill_id: 'hydro-error-diagnosis',
      name: 'hydro-error-diagnosis',
      description: '诊断',
      title_zh: '误差诊断',
      purpose_zh: '解释误差模式',
      source: 'builtin',
      editable: true,
      skill_md: '---\nname: hydro-error-diagnosis\ndescription: 诊断\n---\n\n# body\n',
      body: '# body',
      metadata: { title_zh: '误差诊断' },
      resources: [
        {
          path: 'references/metric-patterns.md',
          category: 'references',
          editable: true,
          size: 12,
        },
      ],
    })
    vi.mocked(api.saveSkill).mockImplementation(async (_id, skill_md) => ({
      skill_id: 'hydro-error-diagnosis',
      name: 'hydro-error-diagnosis',
      description: '诊断',
      title_zh: '误差诊断',
      purpose_zh: '解释误差模式',
      source: 'user',
      editable: true,
      skill_md,
      body: 'updated',
      metadata: { title_zh: '误差诊断' },
      resources: [],
    }))
  })

  it('lists skills and saves SKILL.md override', async () => {
    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()

    const sheet = portal('skills-library')
    expect(sheet).toBeTruthy()
    expect(sheet?.textContent).toContain('误差诊断')

    const editor = sheet?.querySelector('[data-test="skills-md-editor"]') as HTMLTextAreaElement
    expect(editor.value).toContain('hydro-error-diagnosis')
    editor.value = `${editor.value}\nextra note\n`
    editor.dispatchEvent(new Event('input'))

    const save = sheet?.querySelector('[data-test="skills-save"]') as HTMLButtonElement
    save.click()
    await flushPromises()

    expect(api.saveSkill).toHaveBeenCalled()
    expect(portal('skills-notice')?.textContent).toContain('已保存')
  })

  it('creates a new skill from the create dialog', async () => {
    vi.mocked(api.saveSkill).mockResolvedValueOnce({
      skill_id: 'hydro-peak-timing',
      name: 'hydro-peak-timing',
      description: '洪峰时滞',
      title_zh: '洪峰时滞',
      purpose_zh: '洪峰时滞',
      source: 'user',
      editable: true,
      skill_md: '---\nname: hydro-peak-timing\ndescription: 洪峰时滞\n---\n',
      body: '',
      metadata: {},
      resources: [],
    })
    vi.mocked(api.listSkills)
      .mockResolvedValueOnce({
        items: [
          {
            skill_id: 'hydro-error-diagnosis',
            name: 'hydro-error-diagnosis',
            description: '诊断',
            title_zh: '误差诊断',
            purpose_zh: '解释误差模式',
            source: 'builtin',
            editable: true,
          },
        ],
      })
      .mockResolvedValueOnce({
        items: [
          {
            skill_id: 'hydro-error-diagnosis',
            name: 'hydro-error-diagnosis',
            description: '诊断',
            title_zh: '误差诊断',
            purpose_zh: '解释误差模式',
            source: 'builtin',
            editable: true,
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
    vi.mocked(api.getSkill).mockResolvedValue({
      skill_id: 'hydro-peak-timing',
      name: 'hydro-peak-timing',
      description: '洪峰时滞',
      title_zh: '洪峰时滞',
      purpose_zh: '洪峰时滞',
      source: 'user',
      editable: true,
      skill_md: '---\nname: hydro-peak-timing\ndescription: 洪峰时滞\n---\n',
      body: '',
      metadata: {},
      resources: [],
    })

    mount(SkillsLibrarySheet, { props: { open: true } })
    await flushPromises()
    portal('skills-create')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    const create = portal('skills-create-dialog')
    expect(create).toBeTruthy()
    const id = create?.querySelector('[data-test="skills-create-id"]') as HTMLInputElement
    const title = create?.querySelector('[data-test="skills-create-title"]') as HTMLInputElement
    id.value = 'hydro-peak-timing'
    id.dispatchEvent(new Event('input'))
    title.value = '洪峰时滞'
    title.dispatchEvent(new Event('input'))
    ;(create?.querySelector('[data-test="skills-create-submit"]') as HTMLButtonElement).click()
    await flushPromises()

    expect(api.saveSkill).toHaveBeenCalledWith(
      'hydro-peak-timing',
      expect.stringContaining('name: hydro-peak-timing'),
    )
  })
})
