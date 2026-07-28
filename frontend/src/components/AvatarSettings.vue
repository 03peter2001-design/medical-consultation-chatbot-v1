<script setup>
import { ref, watchEffect } from 'vue'

const props = defineProps({
  avatar: { type: Object, required: true },
  open: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'connect'])
const clientKey = defineModel('clientKey', { type: String, default: '' })
const agentId = defineModel('agentId', { type: String, default: '' })
const videoElement = ref(null)

watchEffect(() => {
  if (videoElement.value) {
    videoElement.value.srcObject = props.avatar.videoStream.value
  }
})
</script>

<template>
  <div
    v-if="open"
    class="drawer-backdrop"
    @click="emit('close')"
  />

  <aside
    id="avatar-settings"
    class="avatar-sidebar"
    :class="{ open }"
    role="dialog"
    aria-modal="true"
    aria-label="Avatar 設定"
    :aria-hidden="!open"
    :inert="!open"
  >
    <div class="avatar-preview">
      <div v-if="!avatar.videoStream.value" class="avatar-placeholder">
        <div class="avatar-symbol">👤</div>
        <div>Avatar 為選用功能<br />未連接也可正常問診</div>
      </div>
      <video
        ref="videoElement"
        autoplay
        playsinline
        :class="{ visible: avatar.videoStream.value }"
      />
      <div class="wave-overlay" :class="{ visible: avatar.talking.value }">
        <span /><span /><span /><span /><span />
      </div>
      <button
        class="drawer-close"
        type="button"
        aria-label="關閉 Avatar 設定"
        @click="emit('close')"
      >
        ✕
      </button>
    </div>

    <form
      class="avatar-config"
      @submit.prevent="emit('connect')"
    >
      <div class="config-title">D-ID Avatar（選用）</div>
      <label>
        <span>CLIENT KEY</span>
        <input
          v-model="clientKey"
          type="password"
          placeholder="ck_..."
          autocomplete="off"
        />
      </label>
      <label>
        <span>AGENT ID</span>
        <input
          v-model="agentId"
          type="text"
          placeholder="v2_agt_..."
          autocomplete="off"
        />
      </label>
      <button
        v-if="!avatar.isConnected.value"
        class="avatar-primary"
        type="submit"
        :disabled="avatar.isConnecting.value"
      >
        {{ avatar.isConnecting.value ? '連接中…' : '連接 Avatar' }}
      </button>
      <button
        v-else
        class="avatar-secondary"
        type="button"
        @click="avatar.disconnect"
      >
        中斷連線
      </button>
      <div
        class="config-status"
        :class="`tone-${avatar.statusTone.value}`"
      >
        {{ avatar.status.value }}
      </div>
      <hr />
      <div class="config-title">取得金鑰方式</div>
      <div class="config-hint">
        1. 前往
        <a
          href="https://studio.d-id.com"
          target="_blank"
          rel="noopener noreferrer"
        >
          studio.d-id.com
        </a>
        <br />
        2. 建立 Agent → Embed → 複製金鑰<br />
        3. 填入上方欄位後連接
      </div>
    </form>
  </aside>
</template>

<style scoped>
.avatar-sidebar {
  position: fixed;
  z-index: 120;
  top: var(--header-height);
  bottom: 0;
  left: 0;
  display: flex;
  width: min(340px, 90vw);
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--border);
  background: var(--surface-1);
  box-shadow: 18px 0 45px rgb(37 67 91 / 14%);
  transform: translateX(-102%);
  transition: transform 0.25s ease;
}

.avatar-sidebar.open {
  transform: translateX(0);
}

.avatar-preview {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 12;
  flex: 0 0 auto;
  overflow: hidden;
  background: var(--surface-2);
}

.avatar-preview video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
}

.avatar-preview video.visible {
  opacity: 1;
}

.avatar-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.6;
  text-align: center;
}

.avatar-symbol {
  font-size: 40px;
  opacity: 0.25;
}

.wave-overlay {
  position: absolute;
  bottom: 10px;
  left: 50%;
  display: none;
  height: 20px;
  align-items: flex-end;
  gap: 3px;
  transform: translateX(-50%);
}

.wave-overlay.visible {
  display: flex;
}

.wave-overlay span {
  width: 4px;
  height: 8px;
  border-radius: 3px;
  background: var(--blue);
  animation: wave 0.7s ease-in-out infinite;
}

.wave-overlay span:nth-child(2) {
  height: 16px;
  animation-delay: 0.1s;
}

.wave-overlay span:nth-child(3) {
  height: 10px;
  animation-delay: 0.2s;
}

.wave-overlay span:nth-child(4) {
  height: 18px;
  animation-delay: 0.3s;
}

.wave-overlay span:nth-child(5) {
  animation-delay: 0.4s;
}

.drawer-close {
  position: absolute;
  top: 12px;
  right: 12px;
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: rgb(255 255 255 / 92%);
  color: var(--text);
  cursor: pointer;
}

.avatar-config {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  padding: 16px;
}

.config-title,
.avatar-config label span {
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.avatar-config label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.avatar-config input {
  width: 100%;
  min-height: 44px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.avatar-primary,
.avatar-secondary {
  width: 100%;
  min-height: 44px;
  padding: 10px 12px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.avatar-primary {
  background: var(--green);
  color: white;
}

.avatar-secondary {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
}

.avatar-primary:disabled {
  cursor: wait;
  opacity: 0.4;
}

.config-status {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  text-align: center;
}

.config-status.tone-success {
  color: var(--green);
}

.config-status.tone-error {
  color: var(--danger);
}

.config-status.tone-waiting {
  color: var(--blue);
}

.avatar-config hr {
  border: 0;
  border-top: 1px solid var(--border);
}

.config-hint {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.75;
}

.config-hint a {
  color: var(--blue);
  text-decoration: none;
}

.drawer-backdrop {
  position: fixed;
  z-index: 110;
  inset: var(--header-height) 0 0;
  display: block;
  background: rgb(31 51 69 / 28%);
  backdrop-filter: blur(2px);
}

@keyframes wave {
  50% {
    transform: scaleY(0.3);
  }
}

@media (max-width: 760px) {
  .avatar-sidebar {
    width: min(320px, 88vw);
  }

  .drawer-backdrop {
    background: rgb(31 51 69 / 32%);
  }

  .drawer-close {
    top: 8px;
    right: 8px;
  }
}
</style>
