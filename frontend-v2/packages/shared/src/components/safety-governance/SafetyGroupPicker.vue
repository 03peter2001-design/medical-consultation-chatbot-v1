<script setup>
const props = defineProps({
  groups: { type: Array, required: true },
  activeGroupId: { type: String, default: '' },
  changedGroups: { type: Array, required: true },
})

const emit = defineEmits(['select'])
const searchText = defineModel('searchText', { type: String, default: '' })

function isChanged(group) {
  return props.changedGroups.includes(group)
}
</script>

<template>
  <aside class="group-picker">
    <label>
      搜尋 Safety 規則群組
      <input
        v-model="searchText"
        type="search"
        placeholder="標籤、rule code、觸發詞"
      />
    </label>
    <div class="group-options">
      <button
        v-for="group in groups"
        :key="group.original_label"
        type="button"
        :class="{
          active: activeGroupId === group.original_label,
          changed: isChanged(group),
        }"
        @click="emit('select', group.original_label)"
      >
        <span>
          <strong>{{ group.label }}</strong>
          <small>
            {{ group.rules.length }} 條規則 ·
            {{ group.possible_conditions.length }} 個方向
          </small>
        </span>
        <i v-if="isChanged(group)">已修改</i>
      </button>
    </div>
    <p v-if="!groups.length" class="empty-state">找不到 Safety 規則群組。</p>
  </aside>
</template>

<style scoped>
.group-picker {
  padding: 14px;
  border-right: 1px solid var(--border);
  background: var(--surface-2);
}

.group-picker > label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.group-picker input {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  padding: 8px 9px;
  font: inherit;
}

.group-options {
  display: grid;
  gap: 6px;
  max-height: 620px;
  margin-top: 12px;
  overflow-y: auto;
}

.group-options button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.group-options button span {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.group-options button.active {
  border-color: color-mix(in srgb, var(--blue) 40%, var(--border));
  background: var(--blue-soft);
}

.group-options button.changed {
  box-shadow: inset 3px 0 var(--warning);
}

.group-options small,
.group-options i {
  color: var(--muted);
  font-size: 10px;
  font-style: normal;
}

.empty-state {
  padding: 18px;
  color: var(--muted);
  text-align: center;
}

@media (max-width: 720px) {
  .group-picker {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }

  .group-options {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-height: 240px;
  }
}
</style>
