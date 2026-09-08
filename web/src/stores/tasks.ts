import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import type { TaskCreateRequest, TaskSummary } from '../types/api'

export const useTasksStore = defineStore('tasks', () => {
  const tasks = ref<TaskSummary[]>([])
  const error = ref<string | null>(null)

  async function refresh() {
    tasks.value = await api.listTasks()
  }

  async function create(body: TaskCreateRequest) {
    error.value = null
    const task = await api.createTask(body)
    await refresh()
    return task
  }

  return { tasks, error, refresh, create }
})
