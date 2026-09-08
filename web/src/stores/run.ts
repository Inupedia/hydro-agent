import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import type { RunSummary, TimelineItem } from '../types/api'

export const useRunStore = defineStore('run', () => {
  const run = ref<RunSummary | null>(null)
  const timeline = ref<TimelineItem[]>([])
  let timer: number | null = null

  async function refresh(taskId: string) {
    run.value = await api.getRun(taskId)
    timeline.value = await api.getTimeline(taskId)
  }

  async function start(taskId: string) {
    run.value = await api.startRun(taskId)
    await refresh(taskId)
  }

  async function pause(taskId: string) {
    run.value = await api.pauseRun(taskId)
  }

  async function resume(taskId: string) {
    run.value = await api.resumeRun(taskId)
  }

  function startPolling(taskId: string) {
    stopPolling()
    void refresh(taskId)
    timer = window.setInterval(() => {
      void refresh(taskId).then(() => {
        if (run.value?.paused || run.value?.status === 'completed' || !run.value?.needs_follow_up) {
          stopPolling()
        }
      })
    }, 2000)
  }

  function stopPolling() {
    if (timer != null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  return { run, timeline, refresh, start, pause, resume, startPolling, stopPolling }
})
