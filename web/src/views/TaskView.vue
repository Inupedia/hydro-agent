<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useTasksStore } from '../stores/tasks'

const router = useRouter()
const tasks = useTasksStore()
const showAdvanced = ref(false)
const form = reactive({
  basin_id: 'yaogu',
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
    <p class="lede">
      点一下就会自动跑完整流程。你不需要懂水文模型参数，也不用勾选技术动作——系统会自己预报、尝试改进、把关、锁定，并给出白话结果说明。
    </p>
    <form class="form" @submit.prevent="onSubmit">
      <label>
        流域
        <input name="basin_id" value="yaogu" readonly />
      </label>
      <label>
        模型
        <select v-model="form.model_id" name="model_id">
          <option value="xaj">新安江（XAJ）</option>
          <option value="openhydronet" disabled>OpenHydroNet（稍后）</option>
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

      <button type="button" class="linkish" @click="showAdvanced = !showAdvanced">
        {{ showAdvanced ? '收起高级选项' : '高级选项（一般不用改）' }}
      </button>
      <template v-if="showAdvanced">
        <label>
          Forcing 模式
          <select v-model="form.forcing_mode" name="forcing_mode">
            <option value="R">R（实测强迫）</option>
            <option value="F">F（预报强迫）</option>
          </select>
        </label>
        <label>
          基础方案模板
          <input v-model="form.base_scheme_id" required />
        </label>
        <label class="check">
          <input v-model="form.allow_optimization" type="checkbox" name="allow_optimization" />
          允许有限参数优化
        </label>
      </template>

      <button type="submit" :disabled="submitting.value">创建并自动运行</button>
    </form>
  </section>
</template>
