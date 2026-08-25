import { createRouter, createWebHashHistory } from 'vue-router'

import DoctorView from './views/DoctorView.vue'
import PatientView from './views/PatientView.vue'
import RuleCenterView from './views/RuleCenterView.vue'
import SnomedSearchView from './views/SnomedSearchView.vue'

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
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
    {
      path: '/doctor/terminology/snomed',
      name: 'snomed-search',
      component: SnomedSearchView,
      meta: { title: 'SNOMED CT 編碼查詢' },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = to.meta.title || 'AI 預問診系統'
})

export default router
