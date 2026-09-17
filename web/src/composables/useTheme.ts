import { ref, type Ref } from 'vue'

export type ThemePreference = 'auto' | 'light' | 'dark'

const STORAGE_KEY = 'hydro-theme-preference'

function storedPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value === 'auto' || value === 'light' || value === 'dark') return value
  } catch {
    // Storage can be unavailable in private/embedded contexts; auto is safe.
  }
  return 'auto'
}

function resolvedTheme(preference: ThemePreference): 'light' | 'dark' {
  if (preference !== 'auto') return preference
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return 'light'
}

let mediaWatcherBound = false

export function useTheme() {
  const theme: Ref<ThemePreference> = ref(storedPreference())

  function applyTheme() {
    const root = document.documentElement
    const resolved = resolvedTheme(theme.value)
    root.dataset.theme = resolved
    root.style.colorScheme = resolved
    window.dispatchEvent(new CustomEvent('hydro-theme-change', { detail: resolved }))
  }

  function persistTheme(value: ThemePreference) {
    try {
      localStorage.setItem(STORAGE_KEY, value)
    } catch {
      // Non-persistent runtime is acceptable; the toggle still applies live.
    }
  }

  if (!mediaWatcherBound && typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const changed = () => {
      if (theme.value === 'auto') applyTheme()
    }
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', changed)
    } else {
      media.addListener(changed)
    }
    mediaWatcherBound = true
  }

  applyTheme()

  return {
    theme,
    setTheme(value: ThemePreference) {
      theme.value = value
      persistTheme(value)
      applyTheme()
    },
  }
}
