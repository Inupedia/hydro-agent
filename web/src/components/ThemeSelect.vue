<script setup lang="ts">
import { useTheme, type ThemePreference } from '../composables/useTheme'
import GlassSelect from './GlassSelect.vue'

const { theme, setTheme } = useTheme()
</script>

<template>
  <div class="theme-select">
    <label class="theme-select-field">
      <span>主题配色</span>
      <GlassSelect
        :model-value="theme"
        :options="[
          { value: 'auto', label: '自动' },
          { value: 'light', label: '浅色' },
          { value: 'dark', label: '深色' },
        ]"
        aria-label="主题配色"
        @update:model-value="setTheme($event as ThemePreference)"
      />
    </label>
  </div>
</template>

<style scoped>
.theme-select {
  width: 100%;
}
.theme-select-field {
  display: grid;
  gap: 6px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 550;
  cursor: pointer;
}
</style>
