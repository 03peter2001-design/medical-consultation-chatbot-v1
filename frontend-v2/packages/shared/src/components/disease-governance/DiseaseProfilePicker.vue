<script setup>
defineProps({
  activeDiseaseId: { type: String, default: '' },
  profiles: { type: Array, default: () => [] },
  search: { type: String, default: '' },
})

const emit = defineEmits(['select', 'update:search'])
</script>

<template>
  <aside class="disease-picker">
    <label>
      搜尋疾病
      <input
        :value="search"
        type="search"
        placeholder="疾病名稱或代碼"
        @input="emit('update:search', $event.target.value)"
      />
    </label>
    <div class="disease-options">
      <button
        v-for="profile in profiles"
        :key="profile.id"
        type="button"
        :class="{ active: activeDiseaseId === profile.id }"
        @click="emit('select', profile.id)"
      >
        <span>
          <strong>{{ profile.name }}</strong>
          <code>{{ profile.id }}</code>
        </span>
        <small>{{ profile.clues.length }} 標籤</small>
      </button>
    </div>
    <p v-if="!profiles.length" class="empty-state">找不到疾病。</p>
  </aside>
</template>

<style scoped>
.disease-picker {
  padding: 14px;
  border-right: 1px solid var(--border);
  background: var(--surface-2);
}

.disease-picker > label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.disease-picker input {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  padding: 8px 9px;
  font: inherit;
}

.disease-options {
  display: grid;
  gap: 6px;
  max-height: 570px;
  margin-top: 12px;
  overflow-y: auto;
}

.disease-options button {
  display: grid;
  gap: 5px;
  min-width: 0;
  width: 100%;
  padding: 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.disease-options button.active {
  border-color: color-mix(in srgb, var(--green) 40%, var(--border));
  background: var(--green-soft);
}

.disease-options button span {
  display: grid;
  min-width: 0;
}

.disease-options code {
  color: var(--green);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.disease-options small {
  color: var(--muted);
}

.empty-state {
  padding: 18px;
  text-align: center;
  color: var(--muted);
}

@media (max-width: 720px) {
  .disease-picker {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }

  .disease-options {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-height: 220px;
  }
}
</style>
