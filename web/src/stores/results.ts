import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import type { ResultSummary } from '../types/api'

export const useResultsStore = defineStore('results', () => {
  const result = ref<ResultSummary | null>(null)

  async function load(taskId: string) {
    result.value = await api.getResults(taskId)
  }

  return { result, load }
})
