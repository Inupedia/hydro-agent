import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import TaskView from '../views/TaskView.vue'

vi.mock('../api/client', () => ({
  api: {
    createTask: vi.fn(async () => ({
      task_id: 'task-demo',
      basin_id: 'camels_13235000',
      model_id: 'xaj',
      phase: 'B',
      status: 'created',
      paused: false,
      current_scheme_id: 'scheme',
      agent_rounds_used: 0,
      optimization_cycles_used: 0,
    })),
    listTasks: vi.fn(async () => []),
  },
}))

async function mountWithApp() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/tasks', component: TaskView },
      { path: '/tasks/:taskId/run', component: { template: '<div>run</div>' } },
    ],
  })
  await router.push('/tasks')
  await router.isReady()
  return mount(TaskView, {
    global: {
      plugins: [createPinia(), router],
    },
  })
}

describe('TaskView', () => {
  it('creates a task using domain fields without action checkboxes', async () => {
    const wrapper = await mountWithApp()
    expect(wrapper.text()).toContain('创建预报任务')
    expect(wrapper.text()).toContain('流域')
    expect(wrapper.text()).toContain('模型')
    expect(wrapper.text()).toContain('高级选项')
    expect(wrapper.text()).not.toContain('Forcing 模式')
    await wrapper.get('button.linkish').trigger('click')
    expect(wrapper.text()).toContain('Forcing 模式')
    expect(wrapper.findAll('input[type="checkbox"][name^="A0"]')).toHaveLength(0)
  })
})
