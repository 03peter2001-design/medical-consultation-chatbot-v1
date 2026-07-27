<script setup>
defineProps({
  queueNumber: { type: String, required: true },
})
</script>

<template>
  <section class="queue-card" aria-live="polite">
    <div class="queue-label">問診編號</div>
    <div class="queue-number">{{ queueNumber }}</div>
    <p>
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
  background: rgb(0 200 150 / 5%);
  text-align: center;
  animation: pop-in 0.3s ease;
}

.queue-label {
  margin-bottom: 10px;
  color: var(--muted);
  font-size: 12px;
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

p {
  color: var(--text);
  font-size: 13px;
  line-height: 1.8;
}
</style>
