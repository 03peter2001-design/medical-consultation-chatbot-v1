<script setup>
import { computed } from 'vue'

const props = defineProps({
  sources: { type: Array, default: () => [] },
})

const uniqueSources = computed(() => {
  const seen = new Set()
  return props.sources.filter((source) => {
    const key = source.title || source.url || source.source
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
})
</script>

<template>
  <div v-if="uniqueSources.length" class="source-list">
    <component
      :is="source.url ? 'a' : 'span'"
      v-for="source in uniqueSources"
      :key="source.title || source.url || source.source"
      class="source-tag"
      :href="source.url || undefined"
      :target="source.url ? '_blank' : undefined"
      :rel="source.url ? 'noopener noreferrer' : undefined"
    >
      📄 {{ source.title || source.source }}
    </component>
  </div>
</template>
