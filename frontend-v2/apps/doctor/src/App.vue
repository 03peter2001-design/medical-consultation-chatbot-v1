<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'

import { doctorSession } from '@medical/shared/auth/doctorSession.js'

const ready = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    await doctorSession.start()
    ready.value = true
  } catch (requestError) {
    error.value = requestError.message
  }
})

onBeforeUnmount(() => doctorSession.stop())
</script>

<template>
  <RouterView v-if="ready" />
  <main v-else class="session-gate">
    <section class="session-panel" role="status" aria-live="polite">
      <h1>{{ error ? '無法開啟醫師工作台' : '正在驗證 UCC 身分' }}</h1>
      <p v-if="error">{{ error }}</p>
      <p v-else>正在建立短效、安全的工作階段…</p>
      <button v-if="error" type="button" @click="doctorSession.start().then(() => (ready = true)).catch((e) => (error = e.message))">
        重新驗證
      </button>
    </section>
  </main>
</template>

<style scoped>
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
