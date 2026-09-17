import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { useTheme } from './composables/useTheme'
import './inspira.css'
import './styles.css'
import './theme.css'
import './scrollbars.css'

useTheme()

createApp(App).use(createPinia()).use(router).mount('#app')
