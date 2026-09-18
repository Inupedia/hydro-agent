import type {
  AgentLogSummary,
  ExperienceEntry,
  ExperienceEntryDetail,
  ExperienceEvolutionEvent,
  ExperienceRegressionItem,
  ExperienceSummary,
  ExperienceVersion,
  ExperienceVersionDiff,
  BasinInfo,
  ModelPlan,
  ResultSummary,
  RunSummary,
  TaskCreateRequest,
  TaskSummary,
  TimelineItem,
} from '../types/api'
import type { ResearchSummary } from '../types/research'
import type {
  SkillDetail,
  SkillOverrideDeleteResult,
  SkillResourceContent,
  SkillSummary,
  SkillUsageSummary,
  SkillValidateResult,
  SkillMigrateLegacyResult,
} from '../types/skills'

export type { BasinInfo, ModelPlan }

export type HealthResponse = {
  status: string
  model_preparation?: boolean
  basin_catalog?: boolean
  hydrologist_tune?: boolean
  orchestrator?: string
  mode?: string
  provider_model?: string | null
  run_slots_used?: number
  run_slots_max?: number
  run_queue?: number
}

export type HydrologistSession = {
  session_id: string
  plan_id: string
  task_id?: string | null
  stage: string
  status: string
  error?: string | null
  editable?: string[]
  baseline_params?: Record<string, number>
  current_params?: Record<string, number>
  baseline_metrics?: Record<string, number | null>
  candidate_metrics?: Record<string, number | null>
  comparison?: {
    metric_delta?: Record<string, number | null>
    parameter_delta?: Record<string, number>
    improved_nse?: boolean | null
  } | null
  candidate_scheme_id?: string | null
  notes?: string[]
}

export type LLMConfigPayload = {
  provider_id: string
  base_url: string
  model: string
  api_key: string
  timeout_seconds: number
  max_retries: number
}

export type LLMSettingsResult = {
  provider_id: string
  base_url: string
  model: string
  api_key_set: boolean
  timeout_seconds: number
  max_retries: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`API ${response.status}: ${detail || path}`)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  listBasins() {
    return request<BasinInfo[]>('/api/basins')
  },
  getBasin(id: string) {
    return request<BasinInfo>(`/api/basins/${id}`)
  },
  listModelPlans() {
    return request<ModelPlan[]>('/api/model-plans')
  },
  getModelPlan(id: string) {
    return request<ModelPlan>(`/api/model-plans/${id}`)
  },
  createModelPlan(config: Record<string, string | number>) {
    return request<ModelPlan>('/api/model-plans', { method: 'POST', body: JSON.stringify(config) })
  },
  renameModelPlan(id: string, name: string | null) {
    return request<ModelPlan>(`/api/model-plans/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    })
  },
  confirmBoundary(id: string, boundary_hash: string) {
    return request<ModelPlan>(`/api/model-plans/${encodeURIComponent(id)}/confirm-boundary`, {
      method: 'POST',
      body: JSON.stringify({ boundary_hash }),
    })
  },
  deleteModelPlan(id: string) {
    return request<void>(`/api/model-plans/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },
  createHydrologistSession(body: { plan_id: string; task_id?: string | null }) {
    return request<HydrologistSession>('/api/hydrologist/sessions', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  getHydrologistSession(id: string) {
    return request<HydrologistSession>(`/api/hydrologist/sessions/${encodeURIComponent(id)}`)
  },
  hydrologistStep(
    id: string,
    body: { step: string; params?: Record<string, number>; note?: string; task_id?: string | null },
  ) {
    return request<HydrologistSession>(`/api/hydrologist/sessions/${encodeURIComponent(id)}/step`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  health() {
    return request<HealthResponse>('/api/health')
  },
  getLLMSettings() {
    return request<LLMSettingsResult>('/api/llm/settings')
  },
  saveLLMSettings(payload: LLMConfigPayload) {
    return request<LLMSettingsResult & { ok: boolean }>('/api/llm/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },
  createTask(body: TaskCreateRequest) {
    return request<TaskSummary>('/api/tasks', { method: 'POST', body: JSON.stringify(body) })
  },
  listTasks() {
    return request<TaskSummary[]>('/api/tasks')
  },
  getTask(taskId: string) {
    return request<TaskSummary>(`/api/tasks/${encodeURIComponent(taskId)}`)
  },
  renameTask(taskId: string, name: string | null) {
    return request<TaskSummary>(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    })
  },
  deleteTask(taskId: string) {
    return request<void>(`/api/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' })
  },
  startRun(taskId: string) {
    return request<RunSummary>(`/api/tasks/${taskId}/run`, { method: 'POST' })
  },
  pauseRun(taskId: string) {
    return request<RunSummary>(`/api/tasks/${taskId}/pause`, { method: 'POST' })
  },
  resumeRun(taskId: string) {
    return request<RunSummary>(`/api/tasks/${taskId}/resume`, { method: 'POST' })
  },
  cancelRun(taskId: string) {
    return request<RunSummary>(`/api/tasks/${taskId}/cancel`, { method: 'POST' })
  },
  getRun(taskId: string) {
    return request<RunSummary>(`/api/tasks/${taskId}/run`)
  },
  getTimeline(taskId: string) {
    return request<TimelineItem[]>(`/api/tasks/${taskId}/timeline`)
  },
  getAgentLog(taskId: string) {
    return request<AgentLogSummary>(`/api/tasks/${taskId}/agent-log`)
  },
  getResults(taskId: string) {
    return request<ResultSummary>(`/api/tasks/${taskId}/results`)
  },
  getResearch(taskId: string) {
    return request<ResearchSummary>(`/api/tasks/${taskId}/research`)
  },
  getExperienceSummary() {
    return request<ExperienceSummary>('/api/experience/summary')
  },
  listExperienceEntries() {
    return request<ExperienceEntry[]>('/api/experience/entries')
  },
  getExperienceEntry(experienceId: string) {
    return request<ExperienceEntryDetail>(
      `/api/experience/entries/${encodeURIComponent(experienceId)}`,
    )
  },
  listExperienceEvolution() {
    return request<ExperienceEvolutionEvent[]>('/api/experience/evolution')
  },
  listExperienceVersions() {
    return request<ExperienceVersion[]>('/api/experience/versions')
  },
  getExperienceVersion(version: number) {
    return request<ExperienceVersion>(`/api/experience/versions/${version}`)
  },
  getExperienceVersionDiff(version: number) {
    return request<ExperienceVersionDiff>(`/api/experience/versions/${version}/diff`)
  },
  getExperienceRegression() {
    return request<{ items: ExperienceRegressionItem[] }>('/api/experience/regression')
  },
  listSkills() {
    return request<{ items: SkillSummary[] }>('/api/skills')
  },
  getSkill(skillId: string) {
    return request<SkillDetail>(`/api/skills/${encodeURIComponent(skillId)}`)
  },
  saveSkill(skillId: string, skill_md: string) {
    return request<SkillDetail>(`/api/skills/${encodeURIComponent(skillId)}`, {
      method: 'PUT',
      body: JSON.stringify({ skill_md }),
    })
  },
  validateSkill(skillId: string, skill_md: string) {
    return request<SkillValidateResult>(
      `/api/skills/${encodeURIComponent(skillId)}/validate`,
      { method: 'POST', body: JSON.stringify({ skill_md }) },
    )
  },
  saveSkillBinding(skillId: string, activation_stages: string[], activation_model_ids: string[]) {
    return request<SkillDetail>(`/api/skills/${encodeURIComponent(skillId)}/binding`, {
      method: 'PUT',
      body: JSON.stringify({ activation_stages, activation_model_ids }),
    })
  },
  deleteSkillOverride(skillId: string) {
    return request<SkillOverrideDeleteResult>(
      `/api/skills/${encodeURIComponent(skillId)}/override`,
      { method: 'DELETE' },
    )
  },
  copySkillFromBuiltin(skillId: string) {
    return request<SkillDetail>(
      `/api/skills/${encodeURIComponent(skillId)}/copy-from-builtin`,
      { method: 'POST' },
    )
  },
  reloadSkills() {
    return request<{ skill_ids: string[]; count: number }>('/api/skills/reload', {
      method: 'POST',
    })
  },
  migrateLegacySkills() {
    return request<SkillMigrateLegacyResult>('/api/skills/migrate-legacy', { method: 'POST' })
  },
  getTaskSkillSnapshot(taskId: string) {
    return request<{
      task_id: string
      snapshot_sha256: string
      skills: Array<{
        skill_id: string
        source: string
        skill_sha256: string
        file_count: number
        binding: { activation_stages?: string[]; activation_model_ids?: string[] }
      }>
    }>(`/api/tasks/${encodeURIComponent(taskId)}/skill-snapshot`)
  },
  getTaskSkillUsage(taskId: string) {
    return request<SkillUsageSummary>(`/api/tasks/${encodeURIComponent(taskId)}/skill-usage`)
  },
  listSkillResources(skillId: string) {
    return request<{ items: SkillDetail['resources'] }>(
      `/api/skills/${encodeURIComponent(skillId)}/resources`,
    )
  },
  readSkillResource(skillId: string, resourcePath: string) {
    return request<SkillResourceContent>(
      `/api/skills/${encodeURIComponent(skillId)}/resources/${resourcePath
        .split('/')
        .map(encodeURIComponent)
        .join('/')}`,
    )
  },
  saveSkillResource(skillId: string, resourcePath: string, content: string) {
    return request<SkillResourceContent & { source: string }>(
      `/api/skills/${encodeURIComponent(skillId)}/resources/${resourcePath
        .split('/')
        .map(encodeURIComponent)
        .join('/')}`,
      {
        method: 'PUT',
        body: JSON.stringify({ content }),
      },
    )
  },
}
