<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@inspira-ui/plugins'
import { ref, watchEffect } from 'vue'

interface RippleButtonProps {
  class?: HTMLAttributes['class']
  rippleColor?: string
  duration?: number
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
}

const props = withDefaults(defineProps<RippleButtonProps>(), {
  rippleColor: 'rgba(255, 255, 255, 0.45)',
  duration: 600,
  type: 'button',
  disabled: false,
})

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()

const rippleButtonRef = ref<HTMLButtonElement | null>(null)
const buttonRipples = ref<Array<{ x: number; y: number; size: number; key: number }>>([])

function handleClick(event: MouseEvent) {
  if (props.disabled) return
  createRipple(event)
  emit('click', event)
}

function createRipple(event: MouseEvent) {
  const button = rippleButtonRef.value
  if (!button) return
  const rect = button.getBoundingClientRect()
  const size = Math.max(rect.width, rect.height)
  const x = event.clientX - rect.left - size / 2
  const y = event.clientY - rect.top - size / 2
  buttonRipples.value.push({ x, y, size, key: Date.now() })
}

watchEffect(() => {
  if (buttonRipples.value.length > 0) {
    const lastRipple = buttonRipples.value[buttonRipples.value.length - 1]
    window.setTimeout(() => {
      buttonRipples.value = buttonRipples.value.filter((ripple) => ripple.key !== lastRipple.key)
    }, props.duration)
  }
})
</script>

<template>
  <button
    ref="rippleButtonRef"
    :type="type"
    :disabled="disabled"
    :style="{ '--duration': `${duration}ms` }"
    :class="
      cn(
        'relative inline-flex cursor-pointer items-center justify-center overflow-hidden text-center',
        props.class,
      )
    "
    @click="handleClick"
  >
    <span class="relative z-10"><slot /></span>
    <span
      v-for="ripple in buttonRipples"
      :key="ripple.key"
      class="ripple-animation absolute rounded-full opacity-30"
      :style="{
        width: `${ripple.size}px`,
        height: `${ripple.size}px`,
        top: `${ripple.y}px`,
        left: `${ripple.x}px`,
        backgroundColor: rippleColor,
        transform: 'scale(0)',
        animationDuration: `${duration}ms`,
      }"
    />
  </button>
</template>

<style scoped>
@keyframes rippling {
  0% {
    opacity: 1;
  }
  100% {
    transform: scale(2);
    opacity: 0;
  }
}

.ripple-animation {
  animation: rippling var(--duration) ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .ripple-animation {
    animation: none;
    display: none;
  }
}
</style>
