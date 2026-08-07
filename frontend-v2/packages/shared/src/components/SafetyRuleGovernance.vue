<script setup>
import SafetyDraftAssistant from './safety-governance/SafetyDraftAssistant.vue'
import SafetyGroupPicker from './safety-governance/SafetyGroupPicker.vue'
import SafetyImplementationEditor from './safety-governance/SafetyImplementationEditor.vue'
import SafetyPublishPanel from './safety-governance/SafetyPublishPanel.vue'
import {
  SAFETY_CATEGORY_OPTIONS,
  useSafetyRuleGovernance,
} from '../composables/safetyRuleGovernance.js'

const props = defineProps({
  rulebook: { type: Object, required: true },
  authorized: { type: Boolean, default: false },
  adminToken: { type: String, default: '' },
  sessionId: { type: String, required: true },
})

const emit = defineEmits(['saved'])

const {
  activeCategory,
  activeFeatureCategory,
  activeGroup,
  activeGroupId,
  assistantBusy,
  assistantHistory,
  assistantMessage,
  beginEdit,
  canSave,
  cancelEdit,
  categoryCounts,
  changedGroups,
  changeNote,
  confirmation,
  editing,
  error,
  featureSearch,
  saving,
  searchText,
  selectGroup,
  success,
  validationError,
  visibleGroups,
  askAssistant,
  saveRules,
} = useSafetyRuleGovernance(props, emit)
</script>

<template>
  <section class="governance-section safety-governance">
    <header class="governance-heading">
      <div>
        <span>SAFETY RULE GOVERNANCE</span>
        <h2>組合與原文 Safety 規則</h2>
        <p>
          管理必須符合多個條件或特定原文才停止的進階規則；單一 Safety
          標籤請在上方勾選。
        </p>
      </div>
      <button
        v-if="authorized && !editing"
        type="button"
        class="primary-action"
        @click="beginEdit"
      >
        開始治理審查
      </button>
      <span v-else-if="!authorized" class="locked-badge">需先解鎖規則中心</span>
    </header>

    <ol class="governance-flow" aria-label="組合 Safety 規則治理流程">
      <li class="complete">
        <b>1</b>
        <span>選擇分類<br /><small>共通、路由、結構化</small></span>
      </li>
      <li :class="{ complete: activeGroup }">
        <b>2</b>
        <span>選擇規則群組<br /><small>一次檢視一組條件</small></span>
      </li>
      <li :class="{ complete: editing }">
        <b>3</b>
        <span>管理規則<br /><small>鑑別方向與觸發條件</small></span>
      </li>
      <li :class="{ complete: success }">
        <b>4</b>
        <span>簽署發布<br /><small>快照與版本稽核</small></span>
      </li>
    </ol>

    <div class="category-tabs" aria-label="組合 Safety 規則分類">
      <button
        v-for="category in SAFETY_CATEGORY_OPTIONS"
        :key="category.id"
        type="button"
        :class="{ active: activeCategory === category.id }"
        @click="activeCategory = category.id"
      >
        {{ category.label }}
        <small>{{ categoryCounts[category.id] }}</small>
      </button>
    </div>

    <div v-if="editing" class="draft-summary">
      <div>
        <small>目前 Safety 版本</small>
        <code>{{ rulebook.revision.slice(0, 12) }}</code>
      </div>
      <div>
        <small>本次草稿</small>
        <strong>{{ changedGroups.length }} 個規則群組有變更</strong>
      </div>
    </div>

    <div v-if="error" class="governance-note error">{{ error }}</div>
    <div v-if="success" class="governance-note success">{{ success }}</div>

    <div class="governance-workspace">
      <SafetyGroupPicker
        v-model:search-text="searchText"
        :groups="visibleGroups"
        :active-group-id="activeGroupId"
        :changed-groups="changedGroups"
        @select="selectGroup"
      />

      <SafetyImplementationEditor
        v-if="activeGroup"
        v-model:feature-category="activeFeatureCategory"
        v-model:feature-search="featureSearch"
        :group="activeGroup"
        :editing="editing"
        :fact-catalog="rulebook.fact_catalog || []"
      >
        <SafetyDraftAssistant
          v-if="editing"
          v-model:message="assistantMessage"
          :history="assistantHistory"
          :busy="assistantBusy"
          @submit="askAssistant"
        />
      </SafetyImplementationEditor>
    </div>

    <SafetyPublishPanel
      v-if="editing"
      v-model:change-note="changeNote"
      v-model:confirmation="confirmation"
      :changed-groups="changedGroups"
      :confirmation-text="rulebook.confirmation_text"
      :validation-error="validationError"
      :can-save="canSave"
      :saving="saving"
      @cancel="cancelEdit"
      @save="saveRules"
    />
  </section>
</template>

<style scoped>
.governance-section {
  margin-top: 22px;
  padding: 22px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface-1);
}

.governance-heading,
.draft-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.governance-heading h2 {
  margin: 4px 0 5px;
}

.governance-heading p {
  margin: 0;
  color: var(--muted);
}

.governance-heading > div > span {
  color: var(--blue);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.primary-action,
.category-tabs button {
  padding: 9px 13px;
  border-radius: 8px;
  cursor: pointer;
}

.primary-action {
  border: 0;
  background: var(--blue);
  color: #fff;
  font-weight: 700;
}

.locked-badge {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 8px;
  color: var(--muted);
  font-size: 11px;
}

.governance-flow {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin: 20px 0;
  padding: 0;
  list-style: none;
}

.governance-flow li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--muted);
}

.governance-flow li.complete {
  border-color: color-mix(in srgb, var(--blue) 48%, var(--border));
  color: var(--text);
}

.governance-flow b {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 50%;
  background: var(--blue-soft);
  color: var(--blue);
}

.governance-flow small {
  color: var(--muted);
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
  background: var(--surface-1);
  color: var(--text);
  font-size: 12px;
}

.category-tabs button.active {
  border-color: var(--blue);
  background: var(--blue-soft);
  color: var(--blue);
}

.draft-summary {
  margin: 12px 0;
  padding: 12px;
  border-radius: 10px;
  background: var(--surface-2);
}

.draft-summary > div {
  display: grid;
  gap: 3px;
}

.draft-summary small {
  color: var(--muted);
}

.governance-note {
  margin: 12px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--muted);
}

.governance-note.error {
  background: #fff0f1;
  color: var(--danger);
}

.governance-note.success {
  background: var(--green-soft);
  color: var(--green);
}

.governance-workspace {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}

@media (max-width: 900px) {
  .governance-workspace {
    grid-template-columns: 220px minmax(0, 1fr);
  }
}

@media (max-width: 720px) {
  .governance-section {
    padding: 14px;
  }

  .governance-heading,
  .draft-summary {
    align-items: stretch;
    flex-direction: column;
  }

  .governance-flow {
    grid-template-columns: 1fr 1fr;
  }

  .governance-workspace {
    grid-template-columns: 1fr;
  }
}
</style>
