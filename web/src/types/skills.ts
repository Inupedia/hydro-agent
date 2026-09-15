export type SkillSource = 'builtin' | 'user' | 'memory'

export type SkillSummary = {
  skill_id: string
  name: string
  description: string
  title_zh: string
  purpose_zh: string
  source: SkillSource
  editable: boolean
}

export type SkillResource = {
  path: string
  category: 'references' | 'assets' | 'scripts' | string
  editable: boolean
  size: number
}

export type SkillDetail = SkillSummary & {
  skill_md: string
  body: string
  metadata: Record<string, string>
  license?: string | null
  compatibility?: string | null
  allowed_tools?: string | null
  resources: SkillResource[]
}

export type SkillResourceContent = {
  skill_id: string
  path: string
  content: string
}

export type SkillOverrideDeleteResult = {
  skill_id: string
  override_deleted: boolean
  restored_builtin: boolean
  active: boolean
}
