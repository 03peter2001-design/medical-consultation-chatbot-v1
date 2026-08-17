<script setup>
import { ref, watchEffect } from 'vue'

const props = defineProps({
  avatar: { type: Object, required: true },
})

const didVideoElement = ref(null)
const localVideoElement = ref(null)
const playbackBlocked = ref(false)

watchEffect(() => {
  if (didVideoElement.value) {
    didVideoElement.value.srcObject = props.avatar.isDid.value
      ? props.avatar.videoStream.value
      : null
  }
})

async function playLocalVideo() {
  const video = localVideoElement.value
  if (!video) return
  try {
    await video.play()
    playbackBlocked.value = false
  } catch {
    playbackBlocked.value = true
  }
}

function onLocalPlaybackStart() {
  playbackBlocked.value = false
  props.avatar.onPlaybackStart()
}

function onLocalPlaybackError() {
  playbackBlocked.value = true
  props.avatar.onPlaybackError()
}
</script>

<template>
  <section
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
        ref="didVideoElement"
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
        ref="localVideoElement"
        :src="avatar.videoUrl.value"
        autoplay
        playsinline
        controls
        class="visible"
        @loadedmetadata="playLocalVideo"
        @play="onLocalPlaybackStart"
        @pause="avatar.onPlaybackEnd"
        @ended="avatar.onPlaybackEnd"
        @error="onLocalPlaybackError"
      />
      <button
        v-if="avatar.isLocal.value && avatar.videoUrl.value && playbackBlocked"
        class="manual-play"
        type="button"
        @click="playLocalVideo"
      >
        ▶ 播放醫師語音
      </button>
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
              ? '影片生成中'
              : avatar.statusTone.value === 'error'
                ? 'Avatar 暫時不可用'
                : 'AI 醫師'
        }}
      </span>
      <p>
        {{
          avatar.isConnecting.value || avatar.statusTone.value === 'error'
            ? avatar.status.value
            : avatar.caption.value ||
              'Avatar 已準備完成；醫師的朗讀文字會顯示在這裡。'
        }}
      </p>
      <p v-if="playbackBlocked" class="playback-note">
        瀏覽器已阻擋自動播放；請按醫師影像上的「播放醫師語音」。
      </p>
    </div>
  </section>
</template>

<style scoped>
.avatar-stage {
  display: grid;
  grid-template-columns: minmax(220px, 320px) minmax(280px, 1fr);
  min-height: 270px;
  flex: 0 0 auto;
  align-items: center;
  gap: clamp(20px, 4vw, 44px);
  padding: 22px 28px;
  border-bottom: 1px solid var(--border);
  background:
    radial-gradient(circle at 22% 25%, rgb(10 146 126 / 12%), transparent 42%),
    linear-gradient(135deg, #f8fcfb, #f5f9fd);
}

.doctor-portrait {
  position: relative;
  width: min(100%, 320px);
  aspect-ratio: 4 / 3;
  justify-self: end;
  overflow: hidden;
  border: 2px solid rgb(10 146 126 / 24%);
  border-radius: 18px;
  background: #eaf2f5;
  box-shadow: 0 16px 34px rgb(37 67 91 / 16%);
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

.doctor-portrait video { opacity: 0; }
.doctor-portrait video.visible { opacity: 1; }
.doctor-portrait .hidden { display: none; }

.doctor-placeholder {
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
  color: var(--green);
  font-size: 44px;
  font-weight: 800;
}

.manual-play {
  position: absolute;
  z-index: 3;
  top: 12px;
  left: 50%;
  min-height: 42px;
  padding: 9px 14px;
  border: 1px solid rgb(255 255 255 / 78%);
  border-radius: 999px;
  background: rgb(17 42 59 / 88%);
  color: white;
  cursor: pointer;
  font-weight: 700;
  transform: translateX(-50%);
}

.manual-play:focus-visible {
  outline: 3px solid rgb(255 255 255 / 78%);
  outline-offset: 2px;
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

.avatar-caption .playback-note {
  margin-top: 10px;
  color: var(--danger);
  font-size: 12px;
  font-weight: 650;
  line-height: 1.5;
}

@keyframes avatar-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .loading-spinner {
    animation: none;
    border-color: white;
  }
}

@media (max-width: 760px) {
  .avatar-stage {
    grid-template-columns: 130px minmax(0, 1fr);
    min-height: 0;
    gap: 12px;
    padding: 12px;
  }

  .doctor-portrait {
    width: 130px;
    border-radius: 14px;
  }

  .avatar-caption { padding: 12px; }

  .avatar-caption p {
    display: -webkit-box;
    overflow: hidden;
    font-size: 14px;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 4;
  }

  .manual-play {
    top: 6px;
    min-height: 36px;
    padding: 7px 10px;
    font-size: 11px;
  }
}

@media (max-width: 420px) {
  .avatar-stage {
    grid-template-columns: 110px minmax(0, 1fr);
    gap: 8px;
    padding: 8px;
  }

  .doctor-portrait { width: 110px; }
}
</style>
