<script setup>
import { ref, watchEffect } from 'vue'

const props = defineProps({
  avatar: { type: Object, required: true },
})

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
    v-if="
      avatar.isConnected.value ||
      avatar.isConnecting.value
    "
    class="avatar-stage"
    aria-label="AI 醫師 Avatar"
    :aria-busy="avatar.isConnecting.value"
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
      <span class="presence-dot" aria-hidden="true" />
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
              : 'AI 醫師'
        }}
        <template v-if="avatar.isLocal.value">
          · {{ avatar.languageLabel.value }}
        </template>
      </span>
      <p>
        {{
          avatar.isConnecting.value
            ? avatar.status.value
            : avatar.caption.value ||
              'Avatar 已準備完成，接下來可直接使用語音回答。'
        }}
      </p>
    </div>
  </section>
</template>

<style scoped>
.avatar-stage {
  display: grid;
  grid-template-columns: minmax(180px, 260px) minmax(280px, 520px);
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: clamp(20px, 4vw, 48px);
  padding: 20px 28px;
  border-bottom: 1px solid var(--border);
  background:
    radial-gradient(circle at 22% 25%, rgb(10 146 126 / 12%), transparent 42%),
    linear-gradient(135deg, #f8fcfb, #f5f9fd);
}

.doctor-portrait {
  position: relative;
  width: min(100%, 260px);
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
    grid-template-columns: 112px minmax(0, 1fr);
    gap: 12px;
    padding: 12px;
  }

  .doctor-portrait {
    width: 112px;
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
}
</style>
