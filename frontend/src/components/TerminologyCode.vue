<script setup>
import { computed } from 'vue'

import { codingSystemLabel } from '../services/terminology.js'

const props = defineProps({
  coding: { type: Object, required: true },
})

const systemLabel = computed(() =>
  codingSystemLabel(props.coding.system),
)
const sourceLabel = computed(() =>
  props.coding.source === 'twcore-package'
    ? 'TW Core 官方套件'
    : 'FHIR 原始編碼',
)
</script>

<template>
  <span
    class="terminology-code"
    :title="`${coding.display || ''}｜${sourceLabel}`"
  >
    <b>{{ systemLabel }}</b>
    <code>{{ coding.code }}</code>
  </span>
</template>

<style scoped>
.terminology-code {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  overflow: hidden;
  border: 1px solid #b8ccdf;
  border-radius: 4px;
  background: #f5f9fd;
  color: #345d80;
  font-size: 10px;
  line-height: 1;
  vertical-align: middle;
}

.terminology-code b {
  padding: 4px 5px;
  background: #e5f0fa;
  font-size: 9px;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.terminology-code code {
  overflow: hidden;
  padding: 4px 6px;
  font-family: 'JetBrains Mono', monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
