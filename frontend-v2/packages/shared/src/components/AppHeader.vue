<script setup>
defineProps({
  icon: { type: String, required: true },
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  status: { type: String, default: '' },
  statusTone: { type: String, default: 'idle' },
})
</script>

<template>
  <header class="app-header">
    <div class="app-logo" aria-hidden="true">
      <slot name="icon">{{ icon }}</slot>
    </div>
    <h1 class="app-title">{{ title }}</h1>
    <span v-if="subtitle" class="app-subtitle">{{ subtitle }}</span>
    <div class="header-actions">
      <div v-if="status" class="connection-status" role="status">
        <span
          class="status-dot"
          :class="{
            online: statusTone === 'online',
            talking: statusTone === 'talking',
          }"
        />
        <span class="status-text">{{ status }}</span>
      </div>
      <slot />
    </div>
  </header>
</template>
