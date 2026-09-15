import { onMounted, onUnmounted, ref } from 'vue'

/** Reactive match for a CSS media query. Defaults false until mounted (SSR/test-safe). */
export function useMediaQuery(query: string) {
  const matches = ref(false)
  let media: MediaQueryList | null = null

  function sync() {
    matches.value = !!media?.matches
  }

  onMounted(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    media = window.matchMedia(query)
    sync()
    media.addEventListener('change', sync)
  })

  onUnmounted(() => {
    media?.removeEventListener('change', sync)
    media = null
  })

  return matches
}
