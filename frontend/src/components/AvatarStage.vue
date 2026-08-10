<script setup>
import { ref, watchEffect } from 'vue'

const props = defineProps({
  avatar: { type: Object, required: true },
})
const emit = defineEmits(['connect'])

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
  <section
    class="avatar-stage"
    aria-label="AI 醫師 Avatar"
    :aria-busy="avatar.isConnecting.value || avatar.rendering.value"
  >
    <div
      class="doctor-portrait"
      :class="{
        talking: avatar.talking.value,
        loading: avatar.isConnecting.value && !avatar.talking.value,
      }"
    >
      <div
        v-if="avatar.isDid.value && !avatar.videoStream.value"
        class="doctor-placeholder"
      >
        AI
      </div>
      <video
        v-if="avatar.isDid.value"
        ref="videoElement"
        autoplay
        playsinline
        :class="{ visible: avatar.videoStream.value }"
      />
      <img
        v-if="avatar.isLocal.value"
        :class="{ hidden: avatar.videoUrl.value }"
        :src="avatar.imageUrl.value"
        alt="本地 AI 醫師"
      />
      <video
        v-if="avatar.isLocal.value && avatar.videoUrl.value"
        :src="avatar.videoUrl.value"
        autoplay
        playsinline
        class="visible"
        @play="avatar.onPlaybackStart"
        @pause="avatar.onPlaybackEnd"
        @ended="avatar.onPlaybackEnd"
        @error="avatar.onPlaybackError"
      />
      <span
        v-if="avatar.isConnected.value"
        class="presence-dot"
        aria-hidden="true"
      />
      <div
        v-if="avatar.isConnecting.value && !avatar.talking.value"
        class="stage-loading"
        role="status"
        aria-live="polite"
      >
        <span class="loading-spinner" aria-hidden="true" />
        <strong>AI 醫師準備中</strong>
      </div>
    </div>

    <div class="avatar-caption" aria-live="polite">
      <span class="caption-label">
        {{
          avatar.talking.value
            ? 'AI 醫師正在說話'
            : avatar.isConnecting.value
              ? '模型載入／生成中'
            : avatar.rendering.value
              ? '下一題已就緒 · Avatar 背景生成中'
            : avatar.statusTone.value === 'error'
              ? 'Avatar 暫時不可用'
              : avatar.isConnected.value
                ? 'AI 醫師'
                : 'AI 醫師準備啟用'
        }}
        <template v-if="avatar.isLocal.value">
          · {{ avatar.languageLabel.value }}
        </template>
      </span>
      <p>
        {{
          avatar.isConnecting.value
            ? avatar.status.value
            : avatar.rendering.value
              ? avatar.caption.value
            : avatar.statusTone.value === 'error'
              ? avatar.status.value
              : avatar.isConnected.value
                ? avatar.caption.value ||
                  'Avatar 已準備完成，接下來可直接使用語音回答。'
                : '正在自動啟用院內 AI 醫師 Avatar。'
        }}
      </p>
      <p v-if="avatar.rendering.value" class="rendering-note">
        問題已顯示，可立即作答，不必等待影片完成。
      </p>
      <div
        v-if="!avatar.isConnected.value && !avatar.isConnecting.value"
        class="avatar-fallback"
      >
        <span>Avatar 不影響問診；您仍可使用下方文字輸入。</span>
        <button type="button" @click="emit('connect')">
          重新啟用 Avatar
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.avatar-stage {
  display: grid;
  grid-template-columns: minmax(260px, 360px) minmax(320px, 540px);
  min-height: 320px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: clamp(24px, 4vw, 56px);
  padding: 26px 32px;
  border-bottom: 1px solid var(--border);
  background:
    radial-gradient(circle at 22% 25%, rgb(10 146 126 / 12%), transparent 42%),
    linear-gradient(135deg, #f8fcfb, #f5f9fd);
}

.doctor-portrait {
  position: relative;
  width: min(100%, 360px);
  aspect-ratio: 4 / 3;
  justify-self: end;
  overflow: hidden;
  border: 2px solid rgb(10 146 126 / 24%);
  border-radius: 18px;
  background: #eaf2f5;
  box-shadow: 0 16px 34px rgb(37 67 91 / 16%);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.doctor-portrait.talking {
  border-color: var(--green);
  box-shadow: 0 16px 38px rgb(10 146 126 / 24%);
}

.doctor-portrait.loading img,
.doctor-portrait.loading video {
  filter: saturate(0.72) brightness(0.72);
}

.doctor-portrait img,
.doctor-portrait video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 24%;
}

.doctor-portrait video {
  opacity: 0;
}

.doctor-portrait video.visible {
  opacity: 1;
}

.doctor-portrait .hidden {
  display: none;
}

.doctor-placeholder {
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
  color: var(--green);
  font-size: 44px;
  font-weight: 800;
}

.presence-dot {
  position: absolute;
  right: 12px;
  bottom: 12px;
  width: 12px;
  height: 12px;
  border: 2px solid white;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 0 5px rgb(10 146 126 / 15%);
}

.stage-loading {
  position: absolute;
  z-index: 2;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgb(17 42 59 / 28%);
  color: white;
  text-align: center;
}

.stage-loading strong {
  font-size: 14px;
  letter-spacing: 0.04em;
  text-shadow: 0 1px 8px rgb(0 0 0 / 32%);
}

.loading-spinner {
  width: 30px;
  height: 30px;
  border: 3px solid rgb(255 255 255 / 38%);
  border-top-color: white;
  border-radius: 50%;
  animation: avatar-spin 0.8s linear infinite;
}

.avatar-caption {
  min-width: 0;
  padding: 18px 20px;
  border: 1px solid rgb(41 87 128 / 16%);
  border-radius: 14px;
  background: rgb(255 255 255 / 88%);
  box-shadow: 0 10px 26px rgb(37 67 91 / 8%);
}

.caption-label {
  display: inline-flex;
  margin-bottom: 8px;
  color: var(--green);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.avatar-caption p {
  margin: 0;
  color: var(--text);
  font-size: clamp(16px, 1.8vw, 20px);
  font-weight: 650;
  line-height: 1.65;
}

.avatar-caption .rendering-note {
  margin-top: 10px;
  color: var(--green);
  font-size: 12px;
  font-weight: 650;
  line-height: 1.5;
}

.avatar-fallback {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
}

.avatar-fallback button {
  min-height: 42px;
  padding: 9px 14px;
  border: 1px solid var(--green);
  border-radius: 8px;
  background: var(--green);
  color: white;
  cursor: pointer;
  font-weight: 700;
}

@keyframes avatar-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .loading-spinner {
    animation: none;
    border-color: white;
  }
}

@media (max-width: 760px) {
  .avatar-stage {
    grid-template-columns: 140px minmax(0, 1fr);
    min-height: 0;
    gap: 14px;
    padding: 14px;
  }

  .doctor-portrait {
    width: 140px;
    border-radius: 14px;
  }

  .avatar-caption {
    padding: 12px;
  }

  .avatar-caption p {
    display: -webkit-box;
    overflow: hidden;
    font-size: 14px;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 4;
  }

  .avatar-fallback {
    margin-top: 10px;
    padding-top: 10px;
  }

  .avatar-fallback button {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .avatar-stage {
    grid-template-columns: 118px minmax(0, 1fr);
    gap: 10px;
    padding: 10px;
  }

  .doctor-portrait {
    width: 118px;
  }

  .avatar-fallback span {
    display: none;
  }
}
</style>
