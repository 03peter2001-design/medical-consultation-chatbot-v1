<script setup>
import SourceTags from './SourceTags.vue'

defineProps({
  role: {
    type: String,
    required: true,
    validator: (value) => ['ai', 'user'].includes(value),
  },
  text: { type: String, required: true },
  sources: { type: Array, default: () => [] },
  aiLabel: { type: String, default: 'AI 助理' },
  userLabel: { type: String, default: '您' },
})
</script>

<template>
  <article class="chat-message" :class="role">
    <div class="message-author">
      {{ role === 'ai' ? aiLabel : userLabel }}
    </div>
    <div class="message-bubble">{{ text }}</div>
    <SourceTags :sources="sources" />
  </article>
</template>
