import { createRouter, createWebHashHistory } from 'vue-router'

import DoctorView from './views/DoctorView.vue'
import PatientView from './views/PatientView.vue'

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
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = to.meta.title || 'AI 預問診系統'
})

export default router
