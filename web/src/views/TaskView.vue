<script setup lang="ts">
import { reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useTasksStore } from '../stores/tasks'

const router = useRouter()
const tasks = useTasksStore()
const form = reactive({
  basin_id: 'camels_13235000',
  model_id: 'xaj' as 'xaj' | 'openhydronet',
  start_date: '2020-04-29',
  end_date: '2020-05-01',
  forcing_mode: 'R' as 'R' | 'F',
  base_scheme_id: 'scheme-base',
  allow_optimization: true,
  max_agent_decision_rounds: 20,
  max_optimization_cycles: 4,
})
const submitting = reactive({ value: false })

async function onSubmit() {
  submitting.value = true
  try {
    const task = await tasks.create({ ...form })
    await tasks.refresh()
    await router.push(`/tasks/${task.task_id}/run`)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="page">
    <h1>创建预报任务</h1>
    <p class="lede">填写流域与运行边界后自动执行；不提供 A01–A12 手工勾选。</p>
    <form class="form" @submit.prevent="onSubmit">
      <label>
        流域
        <input v-model="form.basin_id" name="basin_id" required />
      </label>
      <label>
        模型
        <select v-model="form.model_id" name="model_id">
          <option value="xaj">xaj</option>
          <option value="openhydronet" disabled>openhydronet（稍后）</option>
        </select>
      </label>
      <label>
        Forcing 模式
        <select v-model="form.forcing_mode" name="forcing_mode">
          <option value="R">R</option>
          <option value="F">F</option>
        </select>
      </label>
      <label>
        起始日期
        <input v-model="form.start_date" type="date" required />
      </label>
      <label>
        结束日期
        <input v-model="form.end_date" type="date" required />
      </label>
      <label>
        基础方案模板
        <input v-model="form.base_scheme_id" required />
      </label>
      <label class="check">
        <input v-model="form.allow_optimization" type="checkbox" name="allow_optimization" />
        允许有限参数优化
      </label>
      <button type="submit" :disabled="submitting.value">创建并运行</button>
    </form>
  </section>
</template>
