<script setup>
import { computed } from 'vue'

const props = defineProps({
  level: { type: Number, default: 0 },
  received: { type: Boolean, default: false },
})

const barPattern = [0.52, 0.82, 1, 0.68, 0.92, 0.62, 0.78]
const normalizedLevel = computed(() =>
  Math.max(0, Math.min(1, Number(props.level) || 0)),
)
const barStyles = computed(() =>
  barPattern.map((weight, index) => {
    const variation = 0.82 + ((index * 7) % 5) * 0.06
    const scale = 0.16 + normalizedLevel.value * weight * variation
    return { transform: `scaleY(${scale.toFixed(3)})` }
  }),
)
const statusLabel = computed(() =>
  props.received ? '已收到聲音' : '正在聆聽',
)
</script>

<template>
  <div
    class="voice-waveform"
    role="status"
    aria-live="polite"
    :aria-label="statusLabel"
    :class="{ received }"
  >
    <span class="wave-bars" aria-hidden="true">
      <i
        v-for="(style, index) in barStyles"
        :key="index"
        :style="style"
      />
    </span>
    <span class="wave-label">{{ statusLabel }}</span>
  </div>
</template>

<style scoped>
.voice-waveform {
  display: inline-flex;
  min-width: 126px;
  height: 42px;
  flex: 0 0 auto;
  align-items: center;
  gap: 9px;
  padding: 0 11px;
  border: 1px solid rgb(41 87 128 / 22%);
  border-radius: 999px;
  background: var(--blue-soft);
  color: var(--blue);
  transition: border-color 0.2s ease, background 0.2s ease, color 0.2s ease;
}

.voice-waveform.received {
  border-color: rgb(10 146 126 / 36%);
  background: var(--green-soft);
  color: var(--green);
}

.wave-bars {
  display: flex;
  height: 24px;
  align-items: center;
  gap: 2px;
}

.wave-bars i {
  width: 3px;
  height: 22px;
  border-radius: 999px;
  background: currentcolor;
  transform-origin: center;
  transition: transform 80ms linear;
}

.wave-label {
  font-size: 12px;
  font-weight: 750;
  white-space: nowrap;
}

@media (max-width: 760px) {
  .voice-waveform {
    min-width: 78px;
    padding: 0 8px;
  }

  .wave-label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wave-bars i {
    transition: none;
  }
}
</style>
