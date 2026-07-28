<script setup>
defineProps({
  queueNumber: { type: String, required: true },
  triageLevel: { type: String, default: 'routine' },
})
</script>

<template>
  <section
    class="queue-card"
    :class="{ urgent: triageLevel === 'urgent' }"
    aria-live="polite"
  >
    <div class="queue-label">
      {{ triageLevel === 'urgent' ? '儘早就醫編號' : '問診編號' }}
    </div>
    <div class="queue-number">{{ queueNumber }}</div>
    <p v-if="triageLevel === 'urgent'">
      系統已停止繼續追問。<br />
      請持此三位數編號儘早由醫療人員評估。
    </p>
    <p v-else>
      感謝您的回答，問診已完成。<br />
      請您耐心等候叫號，輪到您的號碼時醫師會與您看診。<br />
      如果您感到非常不舒服，請立即告知現場護理師。
    </p>
  </section>
</template>

<style scoped>
.queue-card {
  align-self: stretch;
  padding: 24px 18px;
  border: 1px solid var(--green);
  border-radius: var(--radius);
  background: var(--green-soft);
  text-align: center;
  animation: pop-in 0.3s ease;
}

.queue-label {
  margin-bottom: 10px;
  color: var(--muted);
  font-size: 14px;
  letter-spacing: 0.1em;
}

.queue-number {
  margin-bottom: 14px;
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 42px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.queue-card.urgent {
  border-color: #cf8128;
  background: #fff5e7;
}

.queue-card.urgent .queue-number {
  color: #a66012;
}

p {
  color: var(--text);
  font-size: 15px;
  line-height: 1.75;
}
</style>
