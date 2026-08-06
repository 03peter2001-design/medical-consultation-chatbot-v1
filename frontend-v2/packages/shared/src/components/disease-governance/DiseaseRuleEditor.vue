<script setup>
import DiseaseSafetyEditor from './DiseaseSafetyEditor.vue'
import DiseaseVoteEditor from './DiseaseVoteEditor.vue'

defineProps({
  activeCategory: { type: String, required: true },
  activeTab: { type: String, required: true },
  categoryCounts: { type: Object, required: true },
  editing: { type: Boolean, required: true },
  facts: { type: Array, default: () => [] },
  factSearch: { type: String, default: '' },
  profile: { type: Object, required: true },
  rulebook: { type: Object, required: true },
  safetyGroupCount: { type: Number, required: true },
  safetyGroups: { type: Array, default: () => [] },
  safetySearch: { type: String, default: '' },
  selectedClues: { type: Map, required: true },
})

const emit = defineEmits([
  'normalize-weight',
  'toggle-fact',
  'toggle-safety-group',
  'update:activeCategory',
  'update:activeTab',
  'update:factSearch',
  'update:safetySearch',
])
</script>

<template>
  <section class="label-manager">
    <header class="selected-disease-heading">
      <div>
        <span>SELECTED DISEASE</span>
        <h3>{{ profile.name }}</h3>
        <code>{{ profile.id }}</code>
      </div>
      <div class="disease-badges">
        <span v-if="profile.must_not_miss" class="critical">不能漏診</span>
        <span :class="{ reviewed: profile.review_status === 'reviewed' }">
          {{ profile.review_status === 'reviewed' ? '已審查' : '待校準' }}
        </span>
        <strong>{{ profile.clues.length }} 個已加入標籤</strong>
        <strong v-if="profile.must_not_miss">{{ safetyGroupCount }} 組緊急觸發</strong>
      </div>
    </header>

    <div class="manager-tabs" aria-label="疾病規則類型">
      <button
        type="button"
        :class="{ active: activeTab === 'votes' }"
        @click="emit('update:activeTab', 'votes')"
      >
        投票標籤
        <small>{{ profile.clues.length }}</small>
      </button>
      <button
        type="button"
        :class="{ active: activeTab === 'safety' }"
        @click="emit('update:activeTab', 'safety')"
      >
        Safety 緊急觸發
        <small>{{ safetyGroupCount }}</small>
      </button>
    </div>

    <DiseaseVoteEditor
      v-if="activeTab === 'votes'"
      :active-category="activeCategory"
      :category-counts="categoryCounts"
      :editing="editing"
      :facts="facts"
      :fact-search="factSearch"
      :max-clue-weight="rulebook.max_clue_weight"
      :profile="profile"
      :selected-clues="selectedClues"
      :total-fact-count="rulebook.fact_catalog.length"
      @normalize-weight="emit('normalize-weight', $event)"
      @toggle-fact="emit('toggle-fact', $event)"
      @update:active-category="emit('update:activeCategory', $event)"
      @update:fact-search="emit('update:factSearch', $event)"
    />
    <DiseaseSafetyEditor
      v-else
      :editing="editing"
      :groups="safetyGroups"
      :profile="profile"
      :search="safetySearch"
      @toggle-group="emit('toggle-safety-group', $event)"
      @update:search="emit('update:safetySearch', $event)"
    />
  </section>
</template>

<style scoped>
.label-manager {
  min-width: 0;
  padding: 18px;
}

.selected-disease-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.selected-disease-heading h3 {
  margin: 4px 0 5px;
}

.selected-disease-heading > div > span {
  color: var(--green);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.selected-disease-heading code {
  color: var(--green);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.disease-badges {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.disease-badges span {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 8px;
  color: var(--muted);
  font-size: 11px;
}

.disease-badges strong {
  color: var(--green);
  font-size: 12px;
}

.critical {
  color: var(--warning) !important;
}

.reviewed {
  color: var(--green) !important;
}

.manager-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 16px;
  padding: 5px;
  border-radius: 10px;
  background: var(--surface-2);
}

.manager-tabs button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-weight: 700;
}

.manager-tabs button.active {
  border-color: var(--border);
  background: var(--surface-1);
  color: var(--green);
  box-shadow: 0 2px 6px rgb(32 51 69 / 6%);
}

.manager-tabs small {
  display: grid;
  min-width: 22px;
  height: 22px;
  place-items: center;
  border-radius: 999px;
  background: var(--green-soft);
  font-size: 10px;
}

@media (max-width: 720px) {
  .selected-disease-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .manager-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
