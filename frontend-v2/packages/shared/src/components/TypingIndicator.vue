<script setup>
defineProps({
  label: { type: String, default: 'AI 助理' },
})
</script>

<template>
  <div class="chat-message ai" aria-live="polite" aria-label="AI 正在輸入">
    <div class="message-author">{{ label }}</div>
    <div class="typing-indicator" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  </div>
</template>
