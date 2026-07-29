import { createRouter, createWebHashHistory } from 'vue-router'

import DoctorView from './views/DoctorView.vue'
import PatientView from './views/PatientView.vue'
import RuleCenterView from './views/RuleCenterView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'patient',
      component: PatientView,
      meta: { title: 'AI 預問診系統' },
    },
    {
      path: '/doctor',
      name: 'doctor',
      component: DoctorView,
      meta: { title: '醫師端病例與文獻助手' },
    },
    {
      path: '/doctor/rules',
      name: 'doctor-rules',
      component: RuleCenterView,
      meta: { title: '醫師端規則中心' },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = to.meta.title || 'AI 預問診系統'
})

export default router
