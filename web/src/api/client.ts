import type {
  BasinInfo,
  ModelPlan,
  ResultSummary,
  RunSummary,
  TaskCreateRequest,
  TaskSummary,
  TimelineItem,
} from '../types/api'

export type { BasinInfo, ModelPlan }

export type HealthResponse = {
  status: string
  model_preparation?: boolean
  basin_catalog?: boolean
  hydrologist_tune?: boolean
  orchestrator?: string
  mode?: string
  provider_model?: string | null
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
  confirmBoundary(id: string, boundary_hash: string) {
    return request<ModelPlan>(`/api/model-plans/${id}/confirm-boundary`, {
      method: 'POST',
      body: JSON.stringify({ boundary_hash }),
    })
  },
  deleteModelPlan(id: string) {
    return request<void>(`/api/model-plans/${id}`, { method: 'DELETE' })
  },
  createHydrologistSession(body: { plan_id: string; task_id?: string | null }) {
    return request<HydrologistSession>('/api/hydrologist/sessions', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  getHydrologistSession(id: string) {
    return request<HydrologistSession>(`/api/hydrologist/sessions/${id}`)
  },
  hydrologistStep(
    id: string,
    body: { step: string; params?: Record<string, number>; note?: string; task_id?: string | null },
  ) {
    return request<HydrologistSession>(`/api/hydrologist/sessions/${id}/step`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  health() {
    return request<HealthResponse>('/api/health')
  },
  createTask(body: TaskCreateRequest) {
    return request<TaskSummary>('/api/tasks', { method: 'POST', body: JSON.stringify(body) })
  },
  listTasks() {
    return request<TaskSummary[]>('/api/tasks')
  },
  getTask(taskId: string) {
    return request<TaskSummary>(`/api/tasks/${taskId}`)
  },
  deleteTask(taskId: string) {
    return request<void>(`/api/tasks/${taskId}`, { method: 'DELETE' })
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
  getRun(taskId: string) {
    return request<RunSummary>(`/api/tasks/${taskId}/run`)
  },
  getTimeline(taskId: string) {
    return request<TimelineItem[]>(`/api/tasks/${taskId}/timeline`)
  },
  getResults(taskId: string) {
    return request<ResultSummary>(`/api/tasks/${taskId}/results`)
  },
}
