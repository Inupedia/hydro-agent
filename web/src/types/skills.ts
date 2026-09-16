export type SkillSource = 'builtin' | 'user' | 'memory'

export type SkillSummary = {
  skill_id: string
  name: string
  description: string
  title_zh: string
  purpose_zh: string
  source: SkillSource
  editable: boolean
  activation_stages?: string[]
  activation_model_ids?: string[]
  recommended_actions?: string[]
  /** True when this package is one of the six product built-ins. */
  core?: boolean
}

export type SkillValidateResult = {
  standard_compatible: boolean
  domain_ready: boolean
  errors: string[]
  warnings: string[]
}

export type SkillMigrateLegacyResult = {
  migrated: Array<{ legacy_id: string; canonical_id: string; status: string; detail: string }>
  conflicts: Array<{ legacy_id: string; canonical_id: string; status: string; detail: string }>
  count: number
}

export type SkillUsageSummary = {
  task_id: string
  snapshot_sha256: string | null
  frozen_skill_count: number
  invocation_count: number
  frozen_skills: Array<{
    skill_id: string
    source?: string
    skill_sha256?: string
    file_count?: number
    binding?: { activation_stages?: string[]; activation_model_ids?: string[] }
  }>
  usage_by_skill: Array<{
    skill_id: string
    invocation_count: number
    in_snapshot: boolean
    snapshot_skill_sha256?: string | null
    output_contracts: Array<{ contract: string; count: number }>
    last_round_number?: number | null
  }>
  invocations: Array<{
    decision_id?: string
    round_number?: number
    action?: string
    skill_id: string
    skill_sha256?: string
    snapshot_sha256?: string
    output_contract?: string
    model?: string
    loaded_reference_count?: number
    loaded_references?: Array<{ path?: string; sha256?: string }>
  }>
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
