import { createRouter, createWebHistory } from 'vue-router'
import PrepareView from './views/PrepareView.vue'
import BriefingView from './views/BriefingView.vue'
import ExecuteView from './views/ExecuteView.vue'
import JudgmentView from './views/JudgmentView.vue'
import ResultDemoView from './views/ResultDemoView.vue'
import ProcessDetailView from './views/ProcessDetailView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'prepare', component: PrepareView },
    { path: '/demo/:taskId/brief', name: 'briefing', component: BriefingView },
    { path: '/demo/:taskId/run', name: 'execute', component: ExecuteView },
    { path: '/demo/:taskId/judgment', name: 'judgment', component: JudgmentView },
    { path: '/demo/:taskId/results', name: 'results', component: ResultDemoView },
    { path: '/demo/:taskId/process', name: 'process', component: ProcessDetailView },
    { path: '/tasks', redirect: '/' },
    { path: '/tasks/:taskId/run', redirect: (to) => `/demo/${to.params.taskId}/run` },
    { path: '/tasks/:taskId/results', redirect: (to) => `/demo/${to.params.taskId}/results` },
  ],
})
