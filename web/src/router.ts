import { createRouter, createWebHistory } from 'vue-router'
import ProductObservatoryView from './views/ProductObservatoryView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'observatory', component: ProductObservatoryView },
    { path: '/tasks', redirect: '/' },
    { path: '/tasks/:taskId/:section?', component: ProductObservatoryView },
    // Keep old shared links working, but render the same single product workflow.
    { path: '/demo/:taskId/:section?', component: ProductObservatoryView },
  ],
})
