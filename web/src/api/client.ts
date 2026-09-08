import type { ResultSummary, RunSummary, TaskCreateRequest, TaskSummary, TimelineItem } from '../types/api'

export type HealthResponse = {
  status: string
  mode?: string
  provider_model?: string | null
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
