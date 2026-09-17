<script setup lang="ts">
import { cn } from '@inspira-ui/plugins'
import { TransitionPresets, useElementVisibility, useTransition } from '@vueuse/core'
import { computed, ref, watch } from 'vue'

type TransitionsPresetsKeys = keyof typeof TransitionPresets

interface NumberTickerProps {
  value?: number | null
  direction?: 'up' | 'down'
  duration?: number
  delay?: number
  decimalPlaces?: number
  class?: string
  transition?: TransitionsPresetsKeys
  empty?: string
  format?: (value: number) => string
}

const props = withDefaults(defineProps<NumberTickerProps>(), {
  value: 0,
  direction: 'up',
  delay: 0,
  duration: 1000,
  decimalPlaces: 3,
  transition: 'easeOutCubic',
  empty: '-',
})

const spanRef = ref<HTMLElement>()
const skipMotion = import.meta.env.MODE === 'test'
const start = props.direction === 'down' ? (props.value ?? 0) : 0
const transitionValue = ref(skipMotion ? (props.value ?? 0) : start)

const transitionOutput = useTransition(transitionValue, {
  delay: skipMotion ? 0 : props.delay,
  duration: skipMotion ? 0 : props.duration,
  transition: TransitionPresets[props.transition],
})

const output = computed(() => {
  if (props.value == null || !Number.isFinite(props.value)) return props.empty
  const numeric = Number(transitionOutput.value.toFixed(props.decimalPlaces))
  if (props.format) return props.format(numeric)
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: props.decimalPlaces,
    maximumFractionDigits: props.decimalPlaces,
  }).format(numeric)
})

const isInView = useElementVisibility(spanRef, { threshold: 0 })
const hasBeenInView = ref(skipMotion)

const stopIsInViewWatcher = watch(
  isInView,
  (isVisible) => {
    if (isVisible && !hasBeenInView.value) {
      hasBeenInView.value = true
      transitionValue.value = props.direction === 'down' ? 0 : (props.value ?? 0)
      stopIsInViewWatcher()
    }
  },
  { immediate: true },
)

watch(
  () => props.value,
  (newVal) => {
    if (hasBeenInView.value) {
      transitionValue.value = props.direction === 'down' ? 0 : (newVal ?? 0)
    }
  },
)
</script>

<template>
  <span
    ref="spanRef"
    :class="cn('inline-block tabular-nums tracking-wider text-inherit', props.class)"
  >
    {{ output }}
  </span>
</template>
