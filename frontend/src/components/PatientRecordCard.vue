<script setup>
import { computed } from 'vue'

import BodyPainMap from './BodyPainMap.vue'

const props = defineProps({
  record: { type: Object, required: true },
})

const painLocationIds = computed(() =>
  (props.record.pain_locations || [])
    .map((location) =>
      typeof location === 'string' ? location : location.id,
    )
    .filter(Boolean),
)
</script>

<template>
  <section class="patient-record">
    <div class="record-label">
      📋 問診編號 {{ record.queue_number }} — 問卷摘要
    </div>
    <div class="record-overview">
      <p>{{ record.summary }}</p>
      <div v-if="painLocationIds.length" class="pain-location-panel">
        <div class="pain-location-title">
          <span>疼痛位置圖</span>
          <small>病人自述標記</small>
        </div>
        <BodyPainMap
          :model-value="painLocationIds"
          readonly
          compact
        />
      </div>
    </div>
    <div class="record-label report-label">🩺 AI 初步評估</div>
    <p>{{ record.report }}</p>
  </section>
</template>

<style scoped>
.patient-record {
  max-width: 100%;
  padding: 16px 18px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background: var(--surface-2);
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.record-label {
  margin-bottom: 8px;
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.record-overview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 18px;
  align-items: start;
}

.pain-location-panel {
  white-space: normal;
}

.pain-location-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 7px;
  color: var(--text);
  font-size: 12px;
}

.pain-location-title small {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
}

.report-label {
  margin-top: 14px;
}

@media (max-width: 720px) {
  .record-overview {
    grid-template-columns: 1fr;
  }

  .pain-location-panel :deep(.body-map) {
    width: min(100%, 330px);
  }
}
</style>
