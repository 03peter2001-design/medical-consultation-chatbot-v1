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
    videoElement.value.srcObject = props.avatar.isDid.value
      ? props.avatar.videoStream.value
      : null
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
      <div
        v-if="avatar.isDid.value && !avatar.videoStream.value"
        class="avatar-placeholder"
      >
        <div class="avatar-symbol">👤</div>
        <div>D-ID Avatar 為選用功能<br />未連接也可正常問診</div>
      </div>
      <video
        v-if="avatar.isDid.value"
        ref="videoElement"
        autoplay
        playsinline
        muted
        :class="{ visible: avatar.videoStream.value }"
      />
      <img
        v-if="avatar.isLocal.value"
        class="avatar-image"
        :class="{ hidden: avatar.videoUrl.value }"
        :src="avatar.imageUrl.value"
        alt="本地 AI 醫師 Avatar"
      />
      <video
        v-if="avatar.isLocal.value && avatar.videoUrl.value"
        :src="avatar.videoUrl.value"
        playsinline
        muted
        controls
        preload="metadata"
        class="visible"
      />
      <div class="wave-overlay" :class="{ visible: avatar.talking.value }">
        <span /><span /><span /><span /><span />
      </div>
      <div
        v-if="avatar.isConnecting.value && !avatar.talking.value"
        class="model-loading-overlay"
        role="status"
        aria-live="polite"
      >
        <span class="model-spinner" aria-hidden="true" />
        <strong>模型載入／生成中</strong>
        <span>{{ avatar.status.value }}</span>
        <small>第一次啟用可能需要較長時間，請保持此頁開啟。</small>
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

    <form class="avatar-config" @submit.prevent="emit('connect')">
      <div class="config-title">Avatar Provider</div>
      <label>
        <span>提供者</span>
        <select
          :value="avatar.provider.value"
          :disabled="avatar.isConnecting.value"
          @change="avatar.setProvider($event.target.value)"
        >
          <option value="local">本地（CosyVoice3 + MuseTalk）</option>
          <option value="did">D-ID 雲端 Avatar</option>
        </select>
      </label>

      <label v-if="avatar.isLocal.value">
        <span>醫生說話語言</span>
        <select
          :value="avatar.language.value"
          :disabled="avatar.isConnecting.value"
          @change="avatar.setLanguage($event.target.value)"
        >
          <option value="mandarin">國語</option>
          <option value="minnan">閩南語</option>
        </select>
      </label>

      <div v-if="avatar.isLocal.value" class="model-card">
        <span>語音</span>
        <strong>{{ avatar.speechModel.value }}</strong>
        <span>唇形動畫</span>
        <strong>{{ avatar.animationModel.value }}</strong>
      </div>
      <template v-else>
        <label>
          <span>CLIENT KEY</span>
          <input
            v-model="clientKey"
            type="password"
            placeholder="ck_..."
            autocomplete="off"
            spellcheck="false"
          />
        </label>
        <label>
          <span>AGENT ID</span>
          <input
            v-model="agentId"
            type="text"
            placeholder="v2_agt_..."
            autocomplete="off"
            spellcheck="false"
          />
        </label>
      </template>
      <button
        v-if="!avatar.isConnected.value"
        class="avatar-primary"
        type="submit"
        :disabled="avatar.isConnecting.value"
      >
        {{ avatar.isConnecting.value ? '連線中…' : `啟用 ${avatar.providerLabel.value}` }}
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
      <div v-if="avatar.isLocal.value" class="config-hint">
        語音與影片都在院內主機產生，不需要 D-ID 或其他雲端 Avatar 金鑰。
        第一次使用會下載並載入模型，因此等候時間較長。
      </div>
      <div v-else class="config-hint">
        D-ID 會把要朗讀的文字傳送至其雲端服務。介面輸入的 Client Key 僅保存在
        此頁記憶體；若以 <code>VITE_DID_CLIENT_KEY</code> 設定，金鑰會被編入公開的
        JavaScript，任何訪客都能查看。請只使用限制網域的瀏覽器／Embed Key，切勿
        放入伺服器私鑰。可至
        <a href="https://studio.d-id.com" target="_blank" rel="noopener noreferrer">
          D-ID Studio
        </a>
        建立 Agent。
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

.avatar-image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: opacity 0.2s ease;
}

.avatar-image.hidden {
  display: none;
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

.model-loading-overlay {
  position: absolute;
  z-index: 2;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  background: rgb(17 42 59 / 78%);
  color: white;
  text-align: center;
}

.model-loading-overlay strong {
  font-size: 16px;
}

.model-loading-overlay > span:not(.model-spinner) {
  font-size: 13px;
  font-weight: 650;
}

.model-loading-overlay small {
  color: rgb(255 255 255 / 78%);
  font-size: 12px;
  line-height: 1.5;
}

.model-spinner {
  width: 34px;
  height: 34px;
  border: 3px solid rgb(255 255 255 / 32%);
  border-top-color: white;
  border-radius: 50%;
  animation: model-spin 0.8s linear infinite;
}

.drawer-close {
  position: absolute;
  z-index: 3;
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

.model-card {
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  gap: 8px 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  font-size: 12px;
}

.model-card span { color: var(--muted); }
.model-card strong { overflow-wrap: anywhere; color: var(--text); }

.avatar-config label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.avatar-config input,
.avatar-config select {
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

@keyframes model-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .model-spinner {
    animation: none;
    border-color: white;
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
