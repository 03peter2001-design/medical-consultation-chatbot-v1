import { createRouter, createWebHashHistory } from 'vue-router'

import DoctorView from './views/DoctorView.vue'
import RuleCenterView from './views/RuleCenterView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/doctor' },
    { path: '/doctor', name: 'doctor', component: DoctorView, meta: { title: 'AI 醫師工作台' } },
    { path: '/doctor/rules', name: 'doctor-rules', component: RuleCenterView, meta: { title: 'AI 規則中心' } },
    { path: '/:pathMatch(.*)*', redirect: '/doctor' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = to.meta.title || 'AI 醫師工作台'
})

export default router
