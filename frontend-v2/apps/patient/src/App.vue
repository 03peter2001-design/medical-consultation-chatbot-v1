<script setup>
import { onMounted, ref } from 'vue'

import PatientView from './views/PatientView.vue'
import { patientApi } from '@medical/shared/services/patientBackend.js'
import {
  clearInvitationToken,
  readInvitationToken,
} from '@medical/shared/auth/patientInvitation.js'

const state = ref('checking')
const error = ref('')
const invitationToken = ref('')

onMounted(async () => {
  invitationToken.value = readInvitationToken()
  try {
    await patientApi.session()
    state.value = 'ready'
  } catch (requestError) {
    if (requestError.status !== 401 && requestError.status !== 404) error.value = requestError.message
    state.value = invitationToken.value ? 'invited' : 'invalid'
  }
})

async function begin() {
  if (!invitationToken.value || state.value === 'exchanging') return
  state.value = 'exchanging'
  error.value = ''
  try {
    await patientApi.exchangeInvitation(invitationToken.value)
    clearInvitationToken()
    invitationToken.value = ''
    state.value = 'ready'
  } catch (requestError) {
    error.value = requestError.message
    state.value = 'invited'
  }
}
</script>

<template>
  <PatientView v-if="state === 'ready'" />
  <main v-else class="invite-gate">
    <section class="invite-panel" aria-live="polite">
      <div class="invite-mark" aria-hidden="true">十</div>
      <h1>AI 預問診</h1>
      <p v-if="state === 'checking'">正在確認問診連結…</p>
      <template v-else-if="state === 'invalid'">
        <p>此頁需要由院方提供的有效問診連結。</p>
        <p class="invite-help">請回到掛號櫃台或聯絡院方重新取得連結。</p>
      </template>
      <template v-else>
        <p>開始後，此邀請將立即失效，並在本裝置建立安全的問診工作階段。</p>
        <button type="button" :disabled="state === 'exchanging'" @click="begin">
          {{ state === 'exchanging' ? '正在建立工作階段…' : '開始問診' }}
        </button>
      </template>
      <p v-if="error" class="invite-error" role="alert">{{ error }}</p>
    </section>
  </main>
</template>

<style scoped>
.invite-gate { display: grid; min-height: 100dvh; padding: 24px; place-items: center; background: var(--bg); }
.invite-panel { width: min(520px, 100%); padding: 36px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-1); box-shadow: 0 18px 48px rgb(32 51 69 / 10%); text-align: center; }
.invite-mark { display: grid; width: 48px; height: 48px; margin: 0 auto 18px; place-items: center; border-radius: 12px; background: var(--green); color: white; font-size: 26px; font-weight: 700; }
.invite-panel h1 { margin-bottom: 10px; font-size: 26px; }
.invite-panel p { color: var(--muted); }
.invite-help { margin-top: 8px; font-size: 14px; }
.invite-panel button { width: 100%; margin-top: 24px; padding: 12px 18px; border-radius: 7px; background: var(--green); color: white; cursor: pointer; font-weight: 700; }
.invite-panel button:disabled { cursor: wait; opacity: .65; }
.invite-error { margin-top: 14px; color: var(--danger) !important; }
</style>
