<script setup>
import { onMounted, ref } from 'vue'

import PatientLaunchEntry from './components/PatientLaunchEntry.vue'
import PatientView from './views/PatientView.vue'
import { patientApi } from '@medical/shared/services/patientBackend.js'
import {
  clearInvitationToken,
  invitationCodeFromScan,
  isPatientSessionPayload,
  readInvitationToken,
} from '@medical/shared/auth/patientInvitation.js'

const state = ref('checking')
const error = ref('')
const invitationToken = ref('')
const patientSession = ref(null)
let exchangedInvitationToken = ''

function acceptPatientSession(session) {
  if (!isPatientSessionPayload(session)) {
    throw new Error('院方回傳的問診工作階段格式不正確，請重新取得邀請。')
  }
  patientSession.value = session
  invitationToken.value = ''
  clearInvitationToken()
  state.value = 'ready'
}

onMounted(async () => {
  invitationToken.value =
    invitationCodeFromScan(window.location.href) || readInvitationToken()
  try {
    acceptPatientSession(await patientApi.session())
  } catch (requestError) {
    if (requestError.status !== 401 && requestError.status !== 404) {
      error.value = requestError.message
    }
    state.value = invitationToken.value ? 'invited' : 'invalid'
  }
})

async function redeemInvitation(scannedCode = invitationToken.value) {
  if (state.value === 'exchanging') return
  const code = invitationCodeFromScan(scannedCode)
  if (!code) {
    error.value = 'code 格式不正確，請重新掃描或完整貼上。'
    return
  }

  state.value = 'exchanging'
  error.value = ''
  try {
    // A valid HttpOnly session always wins over a token left in the URL. This
    // also makes a retry after a successful exchange safe and idempotent.
    try {
      acceptPatientSession(await patientApi.session())
      return
    } catch (sessionError) {
      if (sessionError.status !== 401 && sessionError.status !== 404) throw sessionError
    }

    if (exchangedInvitationToken !== code) {
      await patientApi.exchangeInvitation(code)
      exchangedInvitationToken = code
      clearInvitationToken()
    }
    acceptPatientSession(await patientApi.session())
  } catch (requestError) {
    error.value =
      exchangedInvitationToken === code
        ? `病患 session 已建立，但暫時無法驗證（${requestError.message}）。請保留本頁並重試。`
        : `無法驗證此 code（${requestError.message}）。code 可能已過期或使用過。`
    invitationToken.value = code
    state.value = 'invited'
  }
}
</script>

<template>
  <PatientView
    v-if="state === 'ready'"
    :patient-session="patientSession"
  />
  <main v-else class="invite-gate">
    <section class="invite-panel" aria-live="polite">
      <div class="invite-mark" aria-hidden="true">十</div>
      <h1>AI 預問診</h1>
      <p v-if="state === 'checking'">正在確認問診連結…</p>
      <template v-else>
        <p v-if="state === 'invalid'">此頁需要由院方提供的有效問診 code。</p>
        <p v-else>驗證後，此邀請將立即失效，並在本裝置建立安全的問診工作階段。</p>
        <PatientLaunchEntry
          v-model="invitationToken"
          :redeeming="state === 'exchanging'"
          :error="error"
          @redeem="redeemInvitation"
        />
        <p class="invite-help">無法取得 code 時，請回到掛號櫃台或聯絡院方重新取得。</p>
      </template>
    </section>
  </main>
</template>

<style scoped>
.invite-gate { display: grid; min-height: 100dvh; padding: 24px; place-items: center; background: var(--bg); }
.invite-panel { display: grid; width: min(620px, 100%); gap: 14px; padding: 36px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-1); box-shadow: 0 18px 48px rgb(32 51 69 / 10%); text-align: center; }
.invite-mark { display: grid; width: 48px; height: 48px; margin: 0 auto 18px; place-items: center; border-radius: 12px; background: var(--green); color: white; font-size: 26px; font-weight: 700; }
.invite-panel h1 { margin-bottom: 10px; font-size: 26px; }
.invite-panel p { color: var(--muted); }
.invite-help { margin-top: 8px; font-size: 14px; }
</style>
