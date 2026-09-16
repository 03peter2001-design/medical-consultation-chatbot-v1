<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'

import { doctorSession } from '@medical/shared/auth/doctorSession.js'
import { hasSmartLaunchContext } from '@medical/shared/services/smart.js'
import { completeDoctorSmartAuthorization } from './services/smartDoctorSession.js'

const ready = ref(false)
const error = ref('')
const smartStatus = ref('')

async function startApplication() {
  error.value = ''
  smartStatus.value = ''
  try {
    const uccContext = await doctorSession.start()
    if (hasSmartLaunchContext()) {
      const smartContext = await completeDoctorSmartAuthorization({ uccContext })
      smartStatus.value = smartContext.bindingVerified
        ? 'SMART 授權已完成，Patient 與 Encounter 已和 UCC context 核對。'
        : 'SMART 授權已完成；UCC 尚未提供可核對的 FHIR Patient／Encounter，因此 SMART context 不會用於邀請或臨床寫入。'
    }
    ready.value = true
  } catch (requestError) {
    error.value = requestError.message
  }
}

onMounted(startApplication)

onBeforeUnmount(() => doctorSession.stop())
</script>

<template>
  <div v-if="ready" class="application-shell">
    <aside v-if="smartStatus" class="smart-status" role="status">
      {{ smartStatus }}
    </aside>
    <RouterView />
  </div>
  <main v-else class="session-gate">
    <section class="session-panel" role="status" aria-live="polite">
      <h1>{{ error ? '無法開啟醫師工作台' : '正在驗證 UCC 身分' }}</h1>
      <p v-if="error">{{ error }}</p>
      <p v-else>正在建立短效、安全的工作階段…</p>
      <button v-if="error" type="button" @click="startApplication">
        重新驗證
      </button>
    </section>
  </main>
</template>

<style scoped>
.application-shell { min-height: 100dvh; }

.smart-status {
  padding: 9px 18px;
  border-bottom: 1px solid #b9d8cc;
  color: #174c3a;
  background: #e8f5ef;
  font-size: 14px;
  text-align: center;
}

.session-gate {
  display: grid;
  min-height: 100dvh;
  padding: 24px;
  place-items: center;
  background: var(--bg);
}

.session-panel {
  width: min(480px, 100%);
  padding: 28px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-1);
  box-shadow: 0 12px 34px rgb(32 51 69 / 9%);
}

.session-panel h1 { margin-bottom: 8px; font-size: 22px; }
.session-panel p { color: var(--muted); }
.session-panel button { margin-top: 20px; padding: 10px 16px; border-radius: 6px; color: white; background: var(--blue); cursor: pointer; }
</style>
