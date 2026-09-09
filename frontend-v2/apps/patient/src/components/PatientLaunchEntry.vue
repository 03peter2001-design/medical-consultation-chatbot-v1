<script setup>
import { computed, ref } from 'vue'

import {
  invitationCodeFromScan,
  normalizeInvitationCode,
} from '@medical/shared/auth/patientInvitation.js'
import QrCodeScanner from './QrCodeScanner.vue'

defineProps({
  redeeming: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['redeem'])
const code = defineModel({ type: String, default: '' })
const scannerOpen = ref(false)
const normalizedCode = computed(() => normalizeInvitationCode(code.value))
const redeemableCode = computed(() => invitationCodeFromScan(normalizedCode.value))
const codeValid = computed(() => Boolean(redeemableCode.value))

function redeem() {
  if (!codeValid.value) return
  emit('redeem', redeemableCode.value)
}

function acceptScan(scannedCode) {
  code.value = scannedCode
  scannerOpen.value = false
  emit('redeem', scannedCode)
}
</script>

<template>
  <section class="patient-launch-entry" aria-labelledby="launch-entry-title">
    <div class="launch-entry-heading">
      <div>
        <span class="launch-eyebrow">掛號報到</span>
        <h2 id="launch-entry-title">掃描 QR 或貼上一次性 code</h2>
      </div>
      <button
        class="scan-button"
        type="button"
        :disabled="redeeming"
        @click="scannerOpen = !scannerOpen"
      >
        {{ scannerOpen ? '關閉掃描' : '開啟相機掃描' }}
      </button>
    </div>

    <QrCodeScanner
      v-if="scannerOpen"
      @scan="acceptScan"
      @close="scannerOpen = false"
    />

    <form class="launch-code-form" @submit.prevent="redeem">
      <label for="patient-launch-code">一次性問診 code 或邀請連結</label>
      <div class="launch-code-row">
        <input
          id="patient-launch-code"
          v-model="code"
          type="text"
          minlength="32"
          maxlength="2048"
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          placeholder="貼上院方提供的 code 或完整連結"
          :aria-invalid="Boolean(normalizedCode) && !codeValid"
          :disabled="redeeming"
        />
        <button type="submit" :disabled="redeeming || !codeValid">
          {{ redeeming ? '驗證中…' : '驗證並開始' }}
        </button>
      </div>
    </form>
    <p v-if="error" class="launch-error" role="alert">{{ error }}</p>
    <small>code 僅使用一次且會自動過期；系統不會從 code 在瀏覽器端解析病人身分。</small>
  </section>
</template>

<style scoped>
.patient-launch-entry {
  display: grid;
  width: min(100%, 560px);
  gap: 12px;
  text-align: left;
}

.launch-entry-heading,
.launch-code-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}

.launch-entry-heading {
  align-items: center;
  justify-content: space-between;
}

.launch-eyebrow {
  color: var(--green);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.patient-launch-entry h2 {
  margin-top: 3px;
  font-size: 18px;
}

.scan-button,
.launch-code-row button {
  min-height: 42px;
  padding: 9px 13px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
}

.scan-button {
  border: 1px solid var(--green);
  background: transparent;
  color: var(--green);
}

.launch-code-form {
  display: grid;
  gap: 6px;
}

.launch-code-form label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.launch-code-row input {
  min-width: 0;
  min-height: 42px;
  flex: 1;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.launch-code-row button {
  border: 0;
  background: var(--green);
  color: white;
}

.scan-button:disabled,
.launch-code-row button:disabled,
.launch-code-row input:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.patient-launch-entry small {
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
}

.launch-error {
  margin: 0;
  color: var(--danger);
  font-size: 13px;
  white-space: pre-wrap;
}

@media (max-width: 560px) {
  .launch-entry-heading,
  .launch-code-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
