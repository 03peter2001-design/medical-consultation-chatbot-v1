<script setup>
import { DISEASE_CATEGORY_OPTIONS } from '../../composables/diseaseGovernance.js'

defineProps({
  activeCategory: { type: String, required: true },
  categoryCounts: { type: Object, required: true },
  editing: { type: Boolean, required: true },
  facts: { type: Array, default: () => [] },
  factSearch: { type: String, default: '' },
  maxClueWeight: { type: Number, required: true },
  profile: { type: Object, required: true },
  selectedClues: { type: Map, required: true },
  totalFactCount: { type: Number, required: true },
})

const emit = defineEmits([
  'normalize-weight',
  'toggle-fact',
  'update:activeCategory',
  'update:factSearch',
])
</script>

<template>
  <div class="vote-editor">
    <div class="fact-toolbar">
      <label>
        搜尋標籤
        <input
          :value="factSearch"
          type="search"
          placeholder="例如：暈厥、胸悶、syncope"
          @input="emit('update:factSearch', $event.target.value)"
        />
      </label>
      <small>顯示 {{ facts.length }} / {{ totalFactCount }} 個標籤</small>
    </div>

    <div class="category-tabs" aria-label="疾病標籤分類">
      <button
        v-for="category in DISEASE_CATEGORY_OPTIONS"
        :key="category.id"
        type="button"
        :class="{ active: activeCategory === category.id }"
        @click="emit('update:activeCategory', category.id)"
      >
        {{ category.label }}
        <small>{{ categoryCounts[category.id] }}</small>
      </button>
    </div>

    <div class="fact-grid">
      <article
        v-for="fact in facts"
        :key="fact.code"
        class="fact-card"
        :class="{ selected: selectedClues.has(fact.code) }"
      >
        <header>
          <button
            type="button"
            class="fact-toggle"
            :disabled="!editing"
            :aria-pressed="selectedClues.has(fact.code)"
            @click="emit('toggle-fact', fact)"
          >
            {{ selectedClues.has(fact.code) ? '✓ 已加入' : '+ 新增' }}
          </button>
          <div>
            <code>{{ fact.code }}</code>
            <strong>{{ fact.description }}</strong>
          </div>
        </header>
        <div class="fact-categories">
          <span v-for="category in fact.categories" :key="category">
            {{ DISEASE_CATEGORY_OPTIONS.find((item) => item.id === category)?.label || category }}
          </span>
        </div>

        <div v-if="selectedClues.has(fact.code) && editing" class="vote-controls">
          <label>
            病人條件
            <select v-model="selectedClues.get(fact.code).status" :disabled="!editing">
              <option value="present">存在</option>
              <option value="absent">不存在</option>
            </select>
          </label>
          <label>
            投票方向
            <select v-model="selectedClues.get(fact.code).direction" :disabled="!editing">
              <option value="support">支持票</option>
              <option value="oppose">反對票</option>
            </select>
          </label>
          <label>
            權重
            <span class="weight-control">
              <input
                v-model.number="selectedClues.get(fact.code).weight"
                type="number"
                min="1"
                :max="maxClueWeight"
                step="1"
                :disabled="!editing"
                :aria-label="`${profile.name} ${fact.code} 票數`"
                @blur="emit('normalize-weight', selectedClues.get(fact.code))"
              />
              票
            </span>
          </label>
        </div>
        <div v-else-if="selectedClues.has(fact.code)" class="vote-summary">
          <span>{{ selectedClues.get(fact.code).status === 'present' ? '存在' : '不存在' }}</span>
          <span>{{ selectedClues.get(fact.code).direction === 'support' ? '支持票' : '反對票' }}</span>
          <strong>{{ selectedClues.get(fact.code).weight }} 票</strong>
        </div>
      </article>
    </div>
    <p v-if="!facts.length" class="empty-state">找不到符合搜尋或分類的標籤。</p>
    <p class="source-note">
      新增標籤會沿用此疾病既有的來源集合；發布前仍須由審查醫師確認臨床依據。
    </p>
  </div>
</template>

<style scoped>
.fact-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
}

.fact-toolbar label,
.vote-controls label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.fact-toolbar label {
  flex: 1;
}

.fact-toolbar input,
.vote-controls input,
.vote-controls select {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  padding: 8px 9px;
  font: inherit;
}

.fact-toolbar small,
.source-note {
  color: var(--muted);
  font-size: 11px;
}

.category-tabs {
  display: flex;
  gap: 6px;
  margin: 12px 0;
  padding-bottom: 4px;
  overflow-x: auto;
}

.category-tabs button {
  display: flex;
  flex: 0 0 auto;
  gap: 7px;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text);
  cursor: pointer;
  font-size: 12px;
}

.category-tabs button.active {
  border-color: var(--green);
  background: var(--green-soft);
  color: var(--green);
}

.fact-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  max-height: 500px;
  padding-right: 3px;
  overflow-y: auto;
}

.fact-card {
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-1);
}

.fact-card.selected {
  border-color: color-mix(in srgb, var(--green) 48%, var(--border));
  background: color-mix(in srgb, var(--green-soft) 45%, var(--surface-1));
}

.fact-card > header {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}

.fact-card:not(.selected) > header {
  align-items: center;
}

.fact-card > header > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.fact-card code {
  color: var(--green);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.fact-toggle {
  flex: 0 0 auto;
  min-width: 62px;
  padding: 6px 7px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--muted);
  cursor: pointer;
  font-size: 11px;
}

.fact-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.fact-card.selected .fact-toggle {
  border-color: var(--green);
  background: var(--green);
  color: #fff;
}

.fact-categories {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 9px;
}

.fact-categories span {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 8px;
  color: var(--muted);
  font-size: 11px;
}

.vote-controls {
  display: grid;
  grid-template-columns: 1fr 1fr 80px;
  gap: 7px;
  margin-top: 11px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.vote-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 11px;
}

.vote-summary strong {
  margin-left: auto;
  color: var(--green);
}

.weight-control {
  display: flex;
  align-items: center;
  gap: 5px;
}

.source-note {
  margin: 12px 0 0;
}

.empty-state {
  padding: 18px;
  text-align: center;
  color: var(--muted);
}

@media (max-width: 980px) {
  .fact-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .fact-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .vote-controls {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
