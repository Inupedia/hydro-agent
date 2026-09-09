import gsap from 'gsap'

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function motionDuration(seconds: number): number {
  return prefersReducedMotion() ? 0.01 : seconds
}

export { gsap }
