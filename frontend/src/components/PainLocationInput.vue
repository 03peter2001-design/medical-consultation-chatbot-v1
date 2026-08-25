<script setup>
import { formatPainRegions } from '../data/bodyPainRegions.js'
import BodyPainMap from './BodyPainMap.vue'

defineProps({
  preset: { type: Object, required: true },
  highlightedRegionIds: { type: Array, default: () => [] },
  sending: { type: Boolean, default: false },
  embedded: { type: Boolean, default: false },
  showRegionOptions: { type: Boolean, default: true },
})

const emit = defineEmits(['submit'])
const selectedIds = defineModel({
  type: Array,
  default: () => [],
})

function submit() {
  const text = formatPainRegions(selectedIds.value)
  if (!text) return
  emit('submit', text, selectedIds.value)
}
</script>

<template>
  <section class="pain-map-card" :class="{ embedded }">
    <div class="pain-map-heading">
      <div>
        <h3>{{ preset.title }}</h3>
        <p>{{ preset.instruction }}</p>
      </div>
      <span>{{ selectedIds.length }} 個位置</span>
    </div>
    <BodyPainMap
      v-model="selectedIds"
      :preset="preset"
      :highlighted-region-ids="highlightedRegionIds"
      :show-region-options="showRegionOptions"
    />
    <button
      v-if="!embedded"
      class="confirm-pain-button"
      type="button"
      :disabled="!selectedIds.length || sending"
      @click="submit"
    >
      {{ sending ? '傳送中…' : '確認疼痛位置' }}
    </button>
    <p v-if="!embedded" class="pain-map-alternative">
      疼痛不在圖示範圍內時，也可以在下方直接用文字描述。
    </p>
  </section>
</template>

<style scoped>
.pain-map-card {
  display: flex;
  width: min(100%, 460px);
  align-self: flex-start;
  flex-direction: column;
  gap: 10px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-1);
}

.pain-map-card.embedded {
  width: 100%;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.pain-map-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.pain-map-heading h3 {
  margin-bottom: 4px;
  font-size: 16px;
  font-weight: 600;
}

.pain-map-heading p,
.pain-map-alternative {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.65;
}

.pain-map-heading > span {
  flex: 0 0 auto;
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.confirm-pain-button {
  width: 100%;
  min-height: 48px;
  padding: 11px 14px;
  border-radius: 7px;
  background: var(--green);
  color: white;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
}

.confirm-pain-button:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}

.pain-map-alternative {
  text-align: center;
}
</style>
