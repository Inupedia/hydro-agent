import { createRouter, createWebHistory } from 'vue-router'
import ResultView from './views/ResultView.vue'
import RunView from './views/RunView.vue'
import TaskView from './views/TaskView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/tasks' },
    { path: '/tasks', component: TaskView },
    { path: '/tasks/:taskId/run', component: RunView },
    { path: '/tasks/:taskId/results', component: ResultView },
  ],
})
