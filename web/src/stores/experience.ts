import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import type {
  ExperienceEntry,
  ExperienceEntryDetail,
  ExperienceEvolutionEvent,
  ExperienceRegressionItem,
  ExperienceSummary,
  ExperienceVersion,
  ExperienceVersionDiff,
} from '../types/api'

export const useExperienceStore = defineStore('experience', () => {
  const summary = ref<ExperienceSummary | null>(null)
  const entries = ref<ExperienceEntry[]>([])
  const timeline = ref<ExperienceEvolutionEvent[]>([])
  const versions = ref<ExperienceVersion[]>([])
  const regression = ref<ExperienceRegressionItem[]>([])
  const selectedExperienceId = ref<string | null>(null)
  const selectedVersion = ref<number | null>(null)
  const selectedEntry = ref<ExperienceEntryDetail | null>(null)
  const selectedDiff = ref<ExperienceVersionDiff | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function loadSummary() {
    summary.value = await api.getExperienceSummary()
    return summary.value
  }

  async function loadEntries() {
    entries.value = await api.listExperienceEntries()
    return entries.value
  }

  async function loadTimeline() {
    timeline.value = await api.listExperienceEvolution()
    return timeline.value
  }

  async function loadVersions() {
    versions.value = await api.listExperienceVersions()
    return versions.value
  }

  async function loadRegression() {
    regression.value = (await api.getExperienceRegression()).items
    return regression.value
  }

  async function loadEntry(experienceId: string) {
    selectedExperienceId.value = experienceId
    selectedEntry.value = await api.getExperienceEntry(experienceId)
    return selectedEntry.value
  }

  async function loadVersionDiff(version: number) {
    selectedVersion.value = version
    selectedDiff.value = await api.getExperienceVersionDiff(version)
    return selectedDiff.value
  }

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      await Promise.all([
        loadSummary(),
        loadEntries(),
        loadTimeline(),
        loadVersions(),
        loadRegression(),
      ])
      if (
        selectedExperienceId.value &&
        entries.value.some((entry) => entry.experience_id === selectedExperienceId.value)
      ) {
        await loadEntry(selectedExperienceId.value)
      }
      if (
        selectedVersion.value !== null &&
        versions.value.some((version) => version.version === selectedVersion.value)
      ) {
        await loadVersionDiff(selectedVersion.value)
      }
    } catch (err) {
      error.value = String((err as Error).message || err)
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    summary,
    entries,
    timeline,
    versions,
    regression,
    selectedExperienceId,
    selectedVersion,
    selectedEntry,
    selectedDiff,
    loading,
    error,
    loadSummary,
    loadEntries,
    loadTimeline,
    loadVersions,
    loadRegression,
    loadEntry,
    loadVersionDiff,
    refresh,
  }
})
