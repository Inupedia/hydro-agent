import { createRouter, createWebHistory } from 'vue-router'
import ObservatoryView from './views/ObservatoryView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'observatory', component: ObservatoryView },
    { path: '/demo/:taskId/:section?', component: ObservatoryView },
    { path: '/tasks', redirect: '/' },
    { path: '/tasks/:taskId/:section?', component: ObservatoryView },
  ],
})
