<script setup lang="ts">
import { ref } from 'vue'
import type { TimelineItem } from '../types/api'

defineProps<{ items: TimelineItem[] }>()
const expanded = ref<Record<string, boolean>>({})

function toggle(id: string) {
  expanded.value[id] = !expanded.value[id]
}
</script>

<template>
  <ol class="timeline">
    <li v-for="item in items" :key="item.id" class="timeline-item">
      <div class="label-row">
        <strong>{{ item.label }}</strong>
        <button
          type="button"
          class="linkish"
          :data-test="`timeline-expand-${item.id}`"
          @click="toggle(item.id)"
        >
          {{ expanded[item.id] ? '收起技术细节' : '展开技术细节' }}
        </button>
      </div>
      <pre v-if="expanded[item.id]" class="details">{{ JSON.stringify(item.details, null, 2) }}</pre>
    </li>
  </ol>
</template>
