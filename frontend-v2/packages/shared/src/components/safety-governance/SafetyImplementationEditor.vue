<script setup>
import { computed } from 'vue'

import {
  SAFETY_CATEGORY_OPTIONS,
  SAFETY_FEATURE_CATEGORY_OPTIONS,
  SAFETY_ROUTE_LABELS,
} from '../../composables/safetyRuleGovernance.js'

const props = defineProps({
  group: { type: Object, required: true },
  editing: { type: Boolean, default: false },
  factCatalog: { type: Array, default: () => [] },
})

const featureSearch = defineModel('featureSearch', {
  type: String,
  default: '',
})
const activeFeatureCategory = defineModel('featureCategory', {
  type: String,
  default: 'all',
})

const visibleFacts = computed(() => {
  const query = featureSearch.value.trim().toLowerCase()
  return props.factCatalog.filter((fact) => {
    const categoryMatch =
      activeFeatureCategory.value === 'all' ||
      fact.categories.includes(activeFeatureCategory.value)
    return (
      categoryMatch &&
      (!query ||
        `${fact.code} ${fact.description}`.toLowerCase().includes(query))
    )
  })
})

function scopeLabel(rule) {
  if (rule.kind === 'structured') return '結構化條件'
  if (rule.scope === 'universal') return '所有主訴'
  if (rule.scope === 'route') {
    return `${SAFETY_ROUTE_LABELS[rule.route] || rule.route}原文`
  }
  return '複合原文條件'
}

function categoryLabel(category) {
  return (
    SAFETY_CATEGORY_OPTIONS.find((item) => item.id === category)?.label ||
    category
  )
}

function factCategoryLabel(category) {
  return (
    SAFETY_FEATURE_CATEGORY_OPTIONS.find((item) => item.id === category)
      ?.label || category
  )
}
</script>

<template>
  <section class="rule-manager">
    <header class="selected-rule-heading">
      <div>
        <span>SELECTED SAFETY RULE GROUP</span>
        <h3>{{ group.label }}</h3>
        <div class="category-badges">
          <em v-for="category in group.categories" :key="category">
            {{ categoryLabel(category) }}
          </em>
        </div>
      </div>
      <strong>{{ group.rules.length }} 條規則</strong>
    </header>

    <div v-if="editing" class="group-fields">
      <label>
        規則群組名稱
        <input v-model="group.label" maxlength="80" />
      </label>
      <label>
        觸發後鑑別方向（一行一項）
        <textarea v-model="group.conditionsText" rows="4" />
      </label>
    </div>
    <ul v-else class="condition-tags">
      <li v-for="condition in group.possible_conditions" :key="condition">
        {{ condition }}
      </li>
    </ul>

    <div class="implementation-list">
      <article
        v-for="rule in group.rules"
        :key="rule.code"
        class="implementation-card"
      >
        <header>
          <div>
            <code>{{ rule.code }}</code>
            <strong>{{ scopeLabel(rule) }}</strong>
          </div>
          <span>{{ rule.kind }}</span>
        </header>

        <template v-if="editing">
          <label v-if="rule.kind === 'phrase'">
            觸發詞（一行一項）
            <textarea v-model="rule.termsText" rows="4" />
          </label>

          <div v-else-if="rule.kind === 'structured'" class="structured-editor">
            <div class="structured-heading">
              <label>
                判斷方式
                <select v-model="rule.featureMode">
                  <option value="any_findings">任一特徵成立</option>
                  <option value="all_findings">所有特徵皆成立</option>
                </select>
              </label>
              <span>已選 {{ rule.selectedFeatures.length }} 個特徵</span>
            </div>

            <label class="feature-search">
              搜尋語意特徵
              <input
                v-model="featureSearch"
                type="search"
                placeholder="例如：意識、視力、syncope"
              />
            </label>
            <div class="feature-tabs">
              <button
                v-for="category in SAFETY_FEATURE_CATEGORY_OPTIONS"
                :key="category.id"
                type="button"
                :class="{ active: activeFeatureCategory === category.id }"
                @click="activeFeatureCategory = category.id"
              >
                {{ category.label }}
              </button>
            </div>
            <div class="feature-grid">
              <label
                v-for="fact in visibleFacts"
                :key="fact.code"
                :class="{ selected: rule.selectedFeatures.includes(fact.code) }"
              >
                <input
                  v-model="rule.selectedFeatures"
                  type="checkbox"
                  :value="fact.code"
                />
                <span>
                  <code>{{ fact.code }}</code>
                  <b>{{ fact.description }}</b>
                  <small>
                    {{ fact.categories.map(factCategoryLabel).join(' · ') }}
                  </small>
                </span>
              </label>
            </div>
            <label>
              其他進階條件 JSON
              <textarea
                v-model="rule.conditionText"
                class="json-editor"
                rows="6"
              />
            </label>
          </div>

          <label v-else>
            複合原文條件 JSON
            <textarea
              v-model="rule.conditionText"
              class="json-editor"
              rows="8"
            />
          </label>
        </template>

        <p v-else>
          {{
            rule.kind === 'phrase'
              ? rule.terms.join('、')
              : JSON.stringify(rule.when || rule.all_term_groups)
          }}
        </p>
      </article>
    </div>

    <slot />
  </section>
</template>

<style scoped>
.rule-manager {
  min-width: 0;
  padding: 18px;
}

.selected-rule-heading,
.implementation-card > header,
.structured-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.selected-rule-heading h3 {
  margin: 4px 0 5px;
}

.selected-rule-heading > div > span {
  color: var(--blue);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.selected-rule-heading > strong {
  color: var(--blue);
  font-size: 12px;
}

.category-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 7px;
}

.category-badges em {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 8px;
  color: var(--muted);
  font-size: 11px;
  font-style: normal;
}

.group-fields {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  gap: 10px;
  margin-top: 16px;
}

.group-fields label,
.implementation-card label,
.feature-search,
.structured-heading label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.group-fields input,
.group-fields textarea,
.implementation-card textarea,
.implementation-card input,
.implementation-card select {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  padding: 8px 9px;
  font: inherit;
}

.condition-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}

.condition-tags li {
  padding: 5px 8px;
  border-radius: 999px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 11px;
}

.implementation-list {
  display: grid;
  gap: 9px;
  margin-top: 14px;
}

.implementation-card {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-2);
}

.implementation-card > header > div {
  display: grid;
  gap: 2px;
}

.implementation-card code {
  color: var(--blue);
  font-size: 11px;
}

.implementation-card > header span,
.structured-heading > span {
  color: var(--muted);
  font-size: 10px;
}

.implementation-card > p {
  margin-top: 9px;
  color: var(--muted);
  overflow-wrap: anywhere;
  font-size: 12px;
}

.implementation-card > label,
.structured-editor,
.feature-search {
  margin-top: 10px;
}

.feature-tabs {
  display: flex;
  gap: 6px;
  margin: 12px 0;
  padding-bottom: 4px;
  overflow-x: auto;
}

.feature-tabs button {
  display: flex;
  flex: 0 0 auto;
  gap: 7px;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
}

.feature-tabs button.active {
  border-color: var(--blue);
  background: var(--blue-soft);
  color: var(--blue);
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  max-height: 300px;
  margin: 8px 0 12px;
  overflow-y: auto;
}

.feature-grid > label {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
}

.feature-grid > label.selected {
  border-color: var(--blue);
  background: var(--blue-soft);
}

.feature-grid span {
  display: grid;
  gap: 2px;
}

.feature-grid small {
  color: var(--muted);
}

.json-editor {
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 11px !important;
}

@media (max-width: 900px) {
  .feature-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .selected-rule-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .group-fields {
    grid-template-columns: 1fr;
  }
}
</style>
