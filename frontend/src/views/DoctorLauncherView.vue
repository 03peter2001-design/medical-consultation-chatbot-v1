<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import QRCode from 'qrcode'

import AppHeader from '../components/AppHeader.vue'
import { api, connectionError } from '../services/backend.js'
import {
  buildPatientPrefill,
  patientAge,
  patientDisplayName,
} from '../services/fhir.js'
import {
  launchCountdownLabel,
  launchSecondsRemaining,
} from '../services/patientLaunch.js'
import {
  initializeSmartPatient,
  isSmartDoctorQrCallback,
} from '../services/smart.js'

const patientRecord = ref(null)
const loadingPatient = ref(true)
const issuing = ref(false)
const error = ref('')
const invitation = ref(null)
const qrDataUrl = ref('')
const remainingSeconds = ref(0)
const copied = ref(false)
let countdownTimer = null

const patient = computed(() => patientRecord.value?.patient || null)
const smartContext = computed(() => patientRecord.value?.smart || null)
const patientName = computed(() => patientDisplayName(patient.value))
const patientAgeLabel = computed(() => {
  const age = patientAge(patient.value?.birthDate)
  return age == null ? '' : `${age} 歲`
})
const countdown = computed(() => launchCountdownLabel(remainingSeconds.value))
const expired = computed(() => Boolean(invitation.value) && remainingSeconds.value <= 0)

function clearInvitation() {
  invitation.value = null
  qrDataUrl.value = ''
  remainingSeconds.value = 0
  copied.value = false
  if (countdownTimer) window.clearInterval(countdownTimer)
  countdownTimer = null
}

function updateCountdown() {
  remainingSeconds.value = launchSecondsRemaining(invitation.value?.expires_at)
  if (remainingSeconds.value <= 0 && countdownTimer) {
    window.clearInterval(countdownTimer)
    countdownTimer = null
  }
}

function startCountdown() {
  if (countdownTimer) window.clearInterval(countdownTimer)
  updateCountdown()
  countdownTimer = window.setInterval(updateCountdown, 1000)
}

async function issueInvitation() {
  if (!patient.value || !smartContext.value || issuing.value) return
  issuing.value = true
  error.value = ''
  clearInvitation()
  try {
    const result = await api.createDoctorLaunchInvitation({
      issuer: smartContext.value.fhirBaseUrl,
      patient_id: patient.value.id,
      ...(smartContext.value.encounterId
        ? { encounter_id: smartContext.value.encounterId }
        : {}),
      prefill: buildPatientPrefill(patientRecord.value),
    })
    const dataUrl = await QRCode.toDataURL(result.code, {
      errorCorrectionLevel: 'M',
      margin: 3,
      width: 320,
      color: { dark: '#102f3b', light: '#ffffff' },
    })
    invitation.value = result
    qrDataUrl.value = dataUrl
    startCountdown()
  } catch (caught) {
    error.value = connectionError(caught)
  } finally {
    issuing.value = false
  }
}

async function copyCode() {
  if (!invitation.value?.code) return
  try {
    await navigator.clipboard.writeText(invitation.value.code)
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1800)
  } catch {
    error.value = '瀏覽器不允許自動複製，請手動選取下方 code。'
  }
}

async function loadSmartLaunch() {
  if (!isSmartDoctorQrCallback()) {
    loadingPatient.value = false
    error.value = '請回到 FHIR Launcher，將 App Launch URL 設為本系統的 launch.html 後重新選擇病人。'
    return
  }
  loadingPatient.value = true
  error.value = ''
  try {
    const record = await initializeSmartPatient()
    if (!record?.patient?.id || !record?.smart?.fhirBaseUrl) {
      throw new Error('SMART Launch Context 缺少 Patient 或 FHIR issuer。')
    }
    patientRecord.value = record
    await issueInvitation()
  } catch (caught) {
    error.value = `無法載入 SMART Launcher 選定的病人（${caught.message}）。`
  } finally {
    loadingPatient.value = false
  }
}

onMounted(loadSmartLaunch)
onBeforeUnmount(clearInvitation)
</script>

<template>
  <div class="app-shell launcher-app">
    <AppHeader
      icon="▦"
      title="掛號 QR Launcher"
      subtitle="SMART on FHIR 選定病人 · 一次性問診 code"
      :status="invitation && !expired ? `code 有效 ${countdown}` : loadingPatient ? '載入 SMART 病人中' : '等待發碼'"
      :status-tone="invitation && !expired ? 'online' : 'idle'"
    >
      <RouterLink class="nav-link" to="/doctor">醫師工作區</RouterLink>
    </AppHeader>

    <main class="launcher-main">
      <section class="launcher-intro">
        <span>SMART LAUNCH CALLBACK</span>
        <h2>已由 FHIR Launcher 選定掛號病人</h2>
        <p>
          本頁只接受 <code>launch.html</code> 完成的 SMART 授權結果。Patient、Encounter
          與病歷預填皆來自本次 launch context；QR 只包含隨機 opaque code。
        </p>
      </section>

      <div class="launcher-grid">
        <section class="launcher-card patient-card" aria-labelledby="selected-patient-title">
          <div class="card-heading">
            <span>STEP 1</span>
            <h3 id="selected-patient-title">確認 Launcher 選定病人</h3>
          </div>

          <div v-if="loadingPatient" class="loading-panel" role="status">
            正在完成 SMART OAuth 並載入 Patient/$everything…
          </div>

          <article v-else-if="patient" class="selected-patient">
            <div class="patient-avatar" aria-hidden="true">病</div>
            <div>
              <span>SMART 已授權</span>
              <h4>{{ patientName }}</h4>
              <p>{{ [patient.gender, patient.birthDate, patientAgeLabel].filter(Boolean).join(' · ') }}</p>
              <code>Patient/{{ patient.id }}</code>
            </div>
          </article>

          <dl v-if="smartContext" class="launch-context">
            <div><dt>FHIR Box</dt><dd>{{ smartContext.fhirBaseUrl }}</dd></div>
            <div><dt>Patient</dt><dd>{{ smartContext.patientId }}</dd></div>
            <div v-if="smartContext.encounterId"><dt>Encounter</dt><dd>{{ smartContext.encounterId }}</dd></div>
          </dl>

          <p class="context-note">
            若病人不正確，請回到原 FHIR Launcher 重新選擇；本頁不允許手動改寫 Patient ID。
          </p>
          <button
            v-if="patient"
            class="issue-button"
            :disabled="issuing"
            @click="issueInvitation"
          >
            {{ issuing ? '產生中…' : invitation ? '重新產生一次性 QR' : '產生一次性 QR 與 code' }}
          </button>
        </section>

        <section class="launcher-card invitation-card" aria-labelledby="invitation-title">
          <div class="card-heading">
            <span>STEP 2</span>
            <h3 id="invitation-title">交給病患報到</h3>
          </div>

          <div v-if="!invitation" class="qr-placeholder">
            <div aria-hidden="true">▦</div>
            <p>{{ issuing ? '正在產生一次性 code…' : '完成 SMART launch 後會在此顯示 QR' }}</p>
          </div>

          <template v-else>
            <div class="expiry-badge" :class="{ expired }" role="status">
              {{ expired ? 'code 已過期，請重新產生' : `剩餘 ${countdown}` }}
            </div>
            <img v-if="qrDataUrl" class="launch-qr" :src="qrDataUrl" alt="一次性問診 QR code" />
            <p class="qr-help">病患可在問診機器開啟相機掃描，或貼上下方 code。</p>
            <div class="raw-code">
              <label for="raw-launch-code">一次性 code</label>
              <code id="raw-launch-code">{{ invitation.code }}</code>
              <button type="button" @click="copyCode">{{ copied ? '已複製' : '複製 code' }}</button>
            </div>
            <dl class="invitation-meta">
              <div><dt>病人</dt><dd>{{ patientName }}</dd></div>
              <div><dt>Patient</dt><dd>{{ patient.id }}</dd></div>
              <div v-if="smartContext?.encounterId"><dt>Encounter</dt><dd>{{ smartContext.encounterId }}</dd></div>
              <div><dt>到期</dt><dd>{{ new Date(invitation.expires_at).toLocaleString() }}</dd></div>
            </dl>
            <p class="security-note">重新產生會撤銷同一掛號尚未使用的舊 code；成功兌換後不能再次使用。</p>
          </template>
        </section>
      </div>

      <p v-if="error" class="launcher-error" role="alert">{{ error }}</p>
    </main>
  </div>
</template>

<style scoped>
.launcher-app { --brand-accent: #176b75; overflow-y: auto; }
.launcher-main { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 34px 0 52px; }
.launcher-intro { max-width: 780px; margin-bottom: 24px; }
.launcher-intro > span,
.card-heading span,
.selected-patient span { color: #176b75; font-size: 11px; font-weight: 800; letter-spacing: 0.11em; }
.launcher-intro h2 { margin: 6px 0 10px; font-size: clamp(25px, 4vw, 40px); line-height: 1.18; }
.launcher-intro p { color: var(--muted); line-height: 1.75; }
.launcher-grid { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(340px, 0.95fr); gap: 20px; align-items: start; }
.launcher-card { display: grid; gap: 14px; padding: 24px; border: 1px solid var(--border); border-radius: 18px; background: var(--surface-1); box-shadow: 0 18px 45px rgb(37 67 91 / 9%); }
.card-heading h3 { margin-top: 3px; font-size: 20px; }
.loading-panel,
.launcher-error { padding: 14px; border: 1px solid #d39a2d; border-radius: 10px; background: #fff7df; color: #75510a; line-height: 1.55; }
.selected-patient { display: flex; align-items: center; gap: 14px; padding: 17px; border: 1px solid rgb(23 107 117 / 25%); border-radius: 12px; background: #edf8f7; }
.patient-avatar { display: grid; width: 52px; height: 52px; flex: 0 0 52px; place-items: center; border-radius: 50%; background: #176b75; color: white; font-weight: 800; }
.selected-patient h4 { margin: 2px 0; font-size: 20px; }
.selected-patient p { color: var(--muted); font-size: 13px; }
.selected-patient code { font-size: 12px; }
.launch-context,
.invitation-meta { width: 100%; }
.launch-context div,
.invitation-meta div { display: grid; grid-template-columns: 90px minmax(0, 1fr); padding: 8px 0; border-bottom: 1px solid var(--border); }
.launch-context dt,
.invitation-meta dt { color: var(--muted); font-size: 12px; }
.launch-context dd,
.invitation-meta dd { overflow-wrap: anywhere; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
.context-note,
.security-note { color: var(--muted); font-size: 12px; line-height: 1.65; }
.issue-button { min-height: 46px; padding: 10px 15px; border: 0; border-radius: 8px; background: #176b75; color: white; cursor: pointer; font-weight: 700; }
.issue-button:disabled { cursor: not-allowed; opacity: 0.45; }
.invitation-card { justify-items: center; }
.invitation-card .card-heading { width: 100%; }
.qr-placeholder { display: grid; min-height: 360px; place-items: center; align-content: center; gap: 12px; color: var(--muted); text-align: center; }
.qr-placeholder div { font-size: 86px; opacity: 0.16; }
.launch-qr { width: min(100%, 320px); border-radius: 10px; }
.qr-help { color: var(--muted); font-size: 13px; text-align: center; }
.expiry-badge { padding: 6px 12px; border-radius: 999px; background: #e4f6f1; color: #08745f; font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 700; }
.expiry-badge.expired { background: #fff0ed; color: var(--danger); }
.raw-code { display: grid; width: 100%; gap: 7px; }
.raw-code label { color: var(--muted); font-size: 12px; font-weight: 700; }
.raw-code code { overflow-wrap: anywhere; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); font-size: 13px; line-height: 1.5; user-select: all; }
.raw-code button { min-height: 44px; padding: 10px 15px; border: 1px solid #176b75; border-radius: 8px; background: white; color: #176b75; cursor: pointer; font-weight: 700; }
.launcher-error { margin-top: 18px; white-space: pre-wrap; }
@media (max-width: 820px) {
  .launcher-app :deep(.app-header) { height: auto; min-height: var(--header-height); flex-wrap: wrap; padding-block: 8px; }
  .launcher-app :deep(.header-actions) { width: 100%; order: 2; margin-left: 0; }
  .launcher-grid { grid-template-columns: 1fr; }
}
@media (max-width: 520px) {
  .launcher-main { width: min(100% - 20px, 1180px); padding-top: 22px; }
  .launcher-card { padding: 17px; }
}
</style>
