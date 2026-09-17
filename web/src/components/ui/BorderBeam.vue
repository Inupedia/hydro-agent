<script setup lang="ts">
/**
 * Inspira UI Border Beam --- ported for this workbench.
 * offset-path round must follow the card radius, not the beam size
 * (registry default `round(var(--size))` makes a large block crawl the border).
 */
import { cn } from '@inspira-ui/plugins'
import { computed } from 'vue'

interface BorderBeamProps {
  class?: string
  size?: number
  duration?: number
  borderWidth?: number
  anchor?: number
  radius?: number
  colorFrom?: string
  colorTo?: string
  delay?: number
}

const props = withDefaults(defineProps<BorderBeamProps>(), {
  size: 56,
  duration: 6,
  anchor: 90,
  borderWidth: 1.5,
  radius: 12,
  colorFrom: 'var(--accent)',
  colorTo: 'var(--accent-hover)',
  delay: 0,
})

const durationInSeconds = computed(() => `${props.duration}s`)
const delayInSeconds = computed(() => `${props.delay}s`)
</script>

<template>
  <div
    aria-hidden="true"
    :class="cn('border-beam pointer-events-none absolute inset-0 rounded-[inherit]', props.class)"
  />
</template>

<style scoped>
.border-beam {
  --size: v-bind(size);
  --duration: v-bind(durationInSeconds);
  --anchor: v-bind(anchor);
  --border-width: v-bind(borderWidth);
  --radius: v-bind(radius);
  --color-from: v-bind(colorFrom);
  --color-to: v-bind(colorTo);
  --delay: v-bind(delayInSeconds);
  border: calc(var(--border-width) * 1px) solid transparent;
  mask:
    linear-gradient(#000 0 0) padding-box,
    linear-gradient(#000 0 0);
  mask-composite: exclude;
  -webkit-mask:
    linear-gradient(#000 0 0) padding-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
}

.border-beam::after {
  content: '';
  position: absolute;
  aspect-ratio: 1;
  width: calc(var(--size) * 1px);
  background: linear-gradient(to left, var(--color-from), var(--color-to), transparent);
  offset-anchor: calc(var(--anchor) * 1%) 50%;
  offset-path: rect(0 auto auto 0 round calc(var(--radius) * 1px));
  animation: border-beam-anim var(--duration) infinite linear;
  animation-delay: var(--delay);
}

@keyframes border-beam-anim {
  to {
    offset-distance: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .border-beam::after {
    animation: none;
    background: var(--color-from);
    offset-distance: 0%;
  }
}
</style>
