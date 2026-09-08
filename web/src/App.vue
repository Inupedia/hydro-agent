<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="shell">
    <header class="top">
      <RouterLink class="brand" to="/tasks">Hydro-Agent</RouterLink>
      <nav>
        <RouterLink to="/tasks">任务</RouterLink>
      </nav>
    </header>
    <main>
      <RouterView />
    </main>
  </div>
</template>
