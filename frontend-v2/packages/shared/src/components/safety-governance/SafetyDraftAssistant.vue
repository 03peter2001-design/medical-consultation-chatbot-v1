<script setup>
defineProps({
  history: { type: Array, required: true },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['submit'])
const message = defineModel('message', { type: String, default: '' })
</script>

<template>
  <section class="assistant-panel">
    <header>
      <div>
        <span>LLM DRAFT ASSISTANT</span>
        <h4>微調目前 Safety 規則群組</h4>
      </div>
      <small>只修改草稿，不會直接發布</small>
    </header>
    <div v-if="history.length" class="assistant-history">
      <p
        v-for="(historyMessage, index) in history"
        :key="index"
        :class="historyMessage.role"
      >
        <b>{{ historyMessage.role === 'user' ? '醫師' : '助理' }}</b>
        {{ historyMessage.content }}
      </p>
    </div>
    <form class="assistant-input" @submit.prevent="emit('submit')">
      <textarea
        v-model="message"
        rows="2"
        maxlength="1000"
        placeholder="例如：加入右眼與左眼視力模糊觸發詞"
      />
      <button class="primary-action" :disabled="!message.trim() || busy">
        {{ busy ? '產生草稿中…' : '送出微調要求' }}
      </button>
    </form>
  </section>
</template>

<style scoped>
.assistant-panel {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--blue) 35%, var(--border));
  border-radius: 9px;
  background: var(--blue-soft);
}

.assistant-panel > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.assistant-panel header span {
  color: var(--blue);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.assistant-panel h4 {
  margin-top: 3px;
}

.assistant-panel header small {
  color: var(--muted);
}

.assistant-history {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.assistant-history p {
  padding: 8px;
  border-radius: 7px;
  background: var(--surface-1);
  font-size: 12px;
}

.assistant-input {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  margin-top: 10px;
}

.assistant-input textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  padding: 8px 9px;
  font: inherit;
}

.primary-action {
  padding: 9px 13px;
  border: 0;
  border-radius: 8px;
  background: var(--blue);
  color: #fff;
  font-weight: 700;
  cursor: pointer;
}

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

@media (max-width: 720px) {
  .assistant-panel > header {
    align-items: stretch;
    flex-direction: column;
  }

  .assistant-input {
    grid-template-columns: 1fr;
  }
}
</style>
