<script setup>
import { computed } from 'vue'

import { splitStructuredNote } from '../services/structuredNote.js'
import SourceTags from './SourceTags.vue'

const props = defineProps({
  text: { type: String, required: true },
  sources: { type: Array, default: () => [] },
  hideEmr: { type: Boolean, default: false },
})

const displayText = computed(() => {
  if (!props.hideEmr) return props.text
  return (
    splitStructuredNote(props.text).clinicalDecision ||
    '目前沒有其他臨床決策內容。'
  )
})
</script>

<template>
  <section class="structured-report">
    <div class="report-title">🩺 結構化病歷分析（EMR + 臨床決策）</div>
    <pre>{{ displayText }}</pre>
    <SourceTags :sources="sources" />
  </section>
</template>

<style scoped>
.structured-report {
  align-self: stretch;
  padding: 18px 20px;
  border: 1px solid var(--green);
  border-radius: var(--radius);
  background: var(--green-soft);
  animation: pop-in 0.3s ease;
}

.report-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

pre {
  color: var(--text);
  font-family: 'Noto Sans TC', sans-serif;
  font-size: 15px;
  line-height: 1.75;
  white-space: pre-wrap;
}

:deep(.source-list) {
  margin-top: 12px;
}
</style>
