<script setup>
import DiseaseProfilePicker from './disease-governance/DiseaseProfilePicker.vue'
import DiseasePublishPanel from './disease-governance/DiseasePublishPanel.vue'
import DiseaseRuleEditor from './disease-governance/DiseaseRuleEditor.vue'
import {
  DISEASE_ROUTE_LABELS,
  useDiseaseGovernance,
} from '../composables/diseaseGovernance.js'

const props = defineProps({
  rulebook: { type: Object, required: true },
  authorized: { type: Boolean, default: false },
  adminToken: { type: String, default: '' },
  sessionId: { type: String, required: true },
})

const emit = defineEmits(['saved'])

const {
  activeCategory,
  activeDiseaseId,
  activeDraft,
  activeManagerTab,
  activeProfile,
  activeRoute,
  activeSafetyGroupCount,
  beginEdit,
  cancelEdit,
  canPublish,
  categoryCounts,
  changeNote,
  changes,
  confirmation,
  diseaseSearch,
  drafts,
  editing,
  error,
  factSearch,
  normalizeWeight,
  publish,
  reviewer,
  safetySearch,
  saving,
  selectDisease,
  selectedClues,
  setActiveRoute,
  success,
  toggleFact,
  toggleSafetyGroup,
  visibleDiseases,
  visibleFacts,
  visibleSafetyGroups,
} = useDiseaseGovernance(props, emit)
</script>

<template>
  <section class="governance-section">
    <header class="governance-heading">
      <div>
        <span>DISEASE RULE GOVERNANCE</span>
        <h2>疾病標籤、票數與 Safety 治理</h2>
        <p>以疾病為中心管理投票標籤；不能漏診疾病另外綁定明確的緊急觸發器。</p>
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

    <ol class="governance-flow" aria-label="疾病標籤治理流程">
      <li class="complete">
        <b>1</b><span>選擇路由<br /><small>胸痛、頭痛、腹痛</small></span>
      </li>
      <li :class="{ complete: activeProfile }">
        <b>2</b><span>選擇疾病<br /><small>一次檢視一種疾病</small></span>
      </li>
      <li :class="{ complete: editing }">
        <b>3</b><span>管理規則<br /><small>票數標籤、緊急觸發</small></span>
      </li>
      <li :class="{ complete: success }">
        <b>4</b><span>簽署發布<br /><small>快照與版本稽核</small></span>
      </li>
    </ol>

    <div class="route-tabs" aria-label="疾病表路由">
      <button
        v-for="route in drafts"
        :key="route.route"
        type="button"
        :class="{ active: activeRoute === route.route }"
        :disabled="editing && activeRoute !== route.route"
        @click="setActiveRoute(route.route)"
      >
        {{ DISEASE_ROUTE_LABELS[route.route] }}
        <small>{{ route.profile_count }} 種疾病</small>
      </button>
    </div>

    <div v-if="activeDraft" class="profile-summary">
      <div>
        <small>目前版本</small>
        <code>{{ activeDraft.profile_version }}</code>
      </div>
      <div>
        <small>治理狀態</small>
        <strong :class="{ warning: activeDraft.provisional }">
          {{ activeDraft.provisional ? '仍有未校準疾病' : '已完成醫師校準' }}
        </strong>
      </div>
      <div v-if="editing" class="draft-count">
        <small>本次草稿</small>
        <strong>{{ changes.length }} 項變更</strong>
      </div>
    </div>

    <div v-if="error" class="governance-note error">{{ error }}</div>
    <div v-if="success" class="governance-note success">{{ success }}</div>

    <div class="governance-workspace">
      <DiseaseProfilePicker
        :active-disease-id="activeDiseaseId"
        :profiles="visibleDiseases"
        :search="diseaseSearch"
        @select="selectDisease"
        @update:search="diseaseSearch = $event"
      />
      <DiseaseRuleEditor
        v-if="activeProfile"
        :active-category="activeCategory"
        :active-tab="activeManagerTab"
        :category-counts="categoryCounts"
        :editing="editing"
        :facts="visibleFacts"
        :fact-search="factSearch"
        :profile="activeProfile"
        :rulebook="rulebook"
        :safety-group-count="activeSafetyGroupCount"
        :safety-groups="visibleSafetyGroups"
        :safety-search="safetySearch"
        :selected-clues="selectedClues"
        @normalize-weight="normalizeWeight"
        @toggle-fact="toggleFact"
        @toggle-safety-group="toggleSafetyGroup"
        @update:active-category="activeCategory = $event"
        @update:active-tab="activeManagerTab = $event"
        @update:fact-search="factSearch = $event"
        @update:safety-search="safetySearch = $event"
      />
    </div>

    <DiseasePublishPanel
      v-if="editing"
      :can-publish="canPublish"
      :change-note="changeNote"
      :changes="changes"
      :confirmation="confirmation"
      :confirmation-text="rulebook.disease_confirmation_text"
      :reviewer="reviewer"
      :route-label="DISEASE_ROUTE_LABELS[activeRoute]"
      :saving="saving"
      @cancel="cancelEdit"
      @publish="publish"
      @update:change-note="changeNote = $event"
      @update:confirmation="confirmation = $event"
      @update:reviewer="reviewer = $event"
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
.profile-summary {
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
  color: var(--green);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.primary-action,
.route-tabs button {
  border-radius: 8px;
  padding: 9px 13px;
  cursor: pointer;
}

.primary-action {
  border: 0;
  background: var(--green);
  color: #fff;
  font-weight: 700;
}

.route-tabs button {
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text);
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
  border-color: color-mix(in srgb, var(--green) 48%, var(--border));
  color: var(--text);
}

.governance-flow b {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 50%;
  background: var(--green-soft);
  color: var(--green);
}

.governance-flow small,
.route-tabs small,
.profile-summary small {
  color: var(--muted);
}

.route-tabs {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.route-tabs button {
  display: flex;
  justify-content: space-between;
}

.route-tabs button.active {
  border-color: var(--green);
  background: var(--green-soft);
  color: var(--green);
}

.route-tabs button:disabled:not(.active) {
  cursor: not-allowed;
  opacity: 0.4;
}

.profile-summary {
  margin: 14px 0;
  padding: 12px;
  border-radius: 10px;
  background: var(--surface-2);
}

.profile-summary > div {
  display: grid;
  gap: 3px;
}

.warning {
  color: var(--warning) !important;
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
  grid-template-columns: 245px minmax(0, 1fr);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}

@media (max-width: 980px) {
  .governance-workspace {
    grid-template-columns: 210px minmax(0, 1fr);
  }
}

@media (max-width: 720px) {
  .governance-section {
    padding: 14px;
  }

  .governance-heading,
  .profile-summary {
    align-items: stretch;
    flex-direction: column;
  }

  .governance-flow {
    grid-template-columns: 1fr 1fr;
  }

  .route-tabs,
  .governance-workspace {
    grid-template-columns: 1fr;
  }
}
</style>
