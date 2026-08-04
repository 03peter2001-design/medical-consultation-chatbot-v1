<script setup>
import { computed, ref, watch } from 'vue'

import { api } from '../services/backend.js'

const props = defineProps({
  rulebook: { type: Object, required: true },
  authorized: { type: Boolean, default: false },
  adminToken: { type: String, default: '' },
  sessionId: { type: String, required: true },
})

const emit = defineEmits(['saved'])

const categoryOptions = [
  { id: 'all', label: '全部標籤' },
  { id: 'safety', label: 'Safety：直接停止' },
  { id: 'chest', label: '胸痛' },
  { id: 'headache', label: '頭痛' },
  { id: 'abdomen', label: '腹痛' },
  { id: 'common', label: '共通' },
]

const categoryLabels = Object.fromEntries(
  categoryOptions.map((item) => [item.id, item.label]),
)

const drafts = ref([])
const activeCode = ref('')
const activeCategory = ref('all')
const searchText = ref('')
const editing = ref(false)
const saving = ref(false)
const changeNote = ref('')
const confirmation = ref('')
const error = ref('')
const success = ref('')

function cloneLabels(labels) {
  return JSON.parse(JSON.stringify(labels || []))
}

function ensureActiveLabel() {
  if (!drafts.value.some((item) => item.code === activeCode.value)) {
    activeCode.value = drafts.value[0]?.code || ''
  }
}

watch(
  () => props.rulebook,
  (rulebook) => {
    if (!editing.value) {
      drafts.value = cloneLabels(rulebook.fact_catalog)
      ensureActiveLabel()
    }
  },
  { immediate: true },
)

watch(
  () => props.authorized,
  (authorized) => {
    if (!authorized && editing.value) cancelEdit()
  },
)

const visibleLabels = computed(() => {
  const query = searchText.value.trim().toLowerCase()
  return drafts.value.filter((item) => {
    const categoryMatch =
      activeCategory.value === 'all' ||
      (activeCategory.value === 'safety'
        ? item.is_safety
        : item.categories.includes(activeCategory.value))
    return (
      categoryMatch &&
      (!query ||
        `${item.code} ${item.description} ${item.categories.join(' ')}`
          .toLowerCase()
          .includes(query))
    )
  })
})

const activeLabel = computed(() =>
  drafts.value.find((item) => item.code === activeCode.value),
)

const categoryCounts = computed(() =>
  Object.fromEntries(
    categoryOptions.map((category) => [
      category.id,
      category.id === 'all'
        ? drafts.value.length
        : drafts.value.filter((item) =>
            category.id === 'safety'
              ? item.is_safety
              : item.categories.includes(category.id),
          ).length,
    ]),
  ),
)

const originalLabels = computed(() =>
  new Map(
    (props.rulebook.fact_catalog || []).map((item) => [
      item.code,
      item,
    ]),
  ),
)

const changedLabels = computed(() =>
  drafts.value.filter(
    (item) =>
      item.description.trim() !==
        originalLabels.value.get(item.code)?.description ||
      item.is_safety !== originalLabels.value.get(item.code)?.is_safety,
  ),
)

const invalidDescriptions = computed(() =>
  drafts.value.some(
    (item) =>
      !item.description.trim() || item.description.trim().length > 300,
  ),
)

const activeUsage = computed(() => {
  if (!activeLabel.value) return { diseases: 0, safetyRules: 0 }
  const code = activeLabel.value.code
  const diseases = (props.rulebook.routes || []).reduce(
    (count, route) =>
      count +
      route.profiles.filter((profile) =>
        profile.clues.some((clue) => clue.fact === code),
      ).length,
    0,
  )
  const safetyRules = activeLabel.value.conditional_safety_rule_count || 0
  return { diseases, safetyRules }
})

const canSave = computed(
  () =>
    props.authorized &&
    editing.value &&
    changedLabels.value.length > 0 &&
    !invalidDescriptions.value &&
    changeNote.value.trim().length >= 4 &&
    confirmation.value.trim() === props.rulebook.fact_confirmation_text,
)

function selectLabel(code) {
  activeCode.value = code
  error.value = ''
}

function beginEdit() {
  if (!props.authorized || !activeLabel.value) return
  drafts.value = cloneLabels(props.rulebook.fact_catalog)
  ensureActiveLabel()
  editing.value = true
  changeNote.value = ''
  confirmation.value = ''
  error.value = ''
  success.value = ''
}

function cancelEdit() {
  drafts.value = cloneLabels(props.rulebook.fact_catalog)
  editing.value = false
  changeNote.value = ''
  confirmation.value = ''
  error.value = ''
  ensureActiveLabel()
}

async function saveLabels() {
  if (!canSave.value || saving.value) return
  if (!window.confirm('標籤說明與 Safety 行為更新後會套用至後續問診。確定發布嗎？')) {
    return
  }
  saving.value = true
  error.value = ''
  success.value = ''
  try {
    const updated = await api.updateFactLabels(
      {
        session_id: props.sessionId,
        expected_revision: props.rulebook.revision,
        confirmation: confirmation.value.trim(),
        change_note: changeNote.value.trim(),
        fact_labels: drafts.value.map((item) => ({
          code: item.code,
          description: item.description.trim(),
          is_safety: item.is_safety,
        })),
      },
      props.adminToken,
    )
    drafts.value = cloneLabels(updated.fact_catalog)
    editing.value = false
    changeNote.value = ''
    confirmation.value = ''
    success.value = 'ClinicalFact 標籤設定已建立稽核快照並發布。'
    emit('saved', updated)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="fact-label-governance">
    <header class="governance-heading">
      <div>
        <span>CLINICAL FACT GOVERNANCE</span>
        <h2>ClinicalFact 標籤治理</h2>
        <p>所有標籤預設只參與疾病投票；勾選 Safety 後，命中該標籤會立即停止問診並轉為 urgent。</p>
      </div>
      <button
        v-if="authorized && !editing"
        type="button"
        class="primary-action"
        @click="beginEdit"
      >
        開始治理標籤
      </button>
      <span v-else-if="!authorized" class="locked-badge">需先解鎖規則中心</span>
    </header>

    <div class="category-tabs" aria-label="ClinicalFact 標籤分類">
      <button
        v-for="category in categoryOptions"
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
        <small>目前規則版本</small>
        <code>{{ rulebook.revision.slice(0, 12) }}</code>
      </div>
      <strong>{{ changedLabels.length }} 個標籤有變更</strong>
    </div>

    <div v-if="error" class="governance-note error">{{ error }}</div>
    <div v-if="success" class="governance-note success">{{ success }}</div>

    <div class="governance-workspace">
      <aside class="label-picker">
        <label>
          搜尋 ClinicalFact 標籤
          <input
            v-model="searchText"
            type="search"
            placeholder="名稱、說明或 ClinicalFact code"
          />
        </label>
        <div class="label-options">
          <button
            v-for="item in visibleLabels"
            :key="item.code"
            type="button"
            :class="{
              active: activeCode === item.code,
              changed: changedLabels.includes(item),
            }"
            @click="selectLabel(item.code)"
          >
            <strong>{{ item.description }}</strong>
            <code>{{ item.code }}</code>
            <small>{{ item.categories.map((category) => categoryLabels[category] || category).join(' · ') }}</small>
          </button>
        </div>
        <p v-if="!visibleLabels.length" class="empty-state">找不到 ClinicalFact 標籤。</p>
      </aside>

      <section v-if="activeLabel" class="label-manager">
        <header class="selected-label-heading">
          <div>
            <span>SELECTED CLINICAL FACT</span>
            <h3>{{ activeLabel.description }}</h3>
            <code>{{ activeLabel.code }}</code>
            <span
              class="triage-badge"
              :class="activeLabel.is_safety ? 'safety' : 'vote'"
            >
              {{ activeLabel.is_safety ? 'Safety：命中即停止' : '一般：只參與投票' }}
            </span>
          </div>
          <div class="usage-summary">
            <strong>{{ activeUsage.diseases }}</strong><small>個疾病使用</small>
            <strong>{{ activeUsage.safetyRules }}</strong><small>條 Safety 規則使用</small>
          </div>
        </header>

        <div class="category-badges">
          <em v-for="category in activeLabel.categories" :key="category">
            {{ categoryLabels[category] || category }}
          </em>
        </div>

        <label class="safety-toggle-card" :class="{ selected: activeLabel.is_safety }">
          <input
            v-model="activeLabel.is_safety"
            type="checkbox"
            :disabled="!editing"
          />
          <span>
            <strong>設為 Safety 標籤</strong>
            <small>
              勾選後，只要此 ClinicalFact 以 present 命中，就會立即標記 urgent、停止一般問診與投票流程。
            </small>
          </span>
        </label>

        <div
          v-if="activeLabel.conditional_safety_rule_count"
          class="conditional-rule-note"
        >
          <strong>另被 {{ activeLabel.conditional_safety_rule_count }} 條組合 Safety 規則引用</strong>
          <p>這些規則必須符合完整組合條件才會停止；不等同於上方「單一標籤命中即停止」。</p>
        </div>

        <label v-if="editing" class="description-editor">
          標準名稱與臨床說明
          <textarea
            v-model="activeLabel.description"
            rows="6"
            maxlength="300"
          />
          <small>{{ activeLabel.description.trim().length }} / 300 字</small>
        </label>
        <div v-else class="description-preview">
          <small>目前標準說明</small>
          <p>{{ activeLabel.description }}</p>
        </div>

        <div class="immutability-note">
          <strong>穩定識別碼不會改變</strong>
          <p>ClinicalFact code 會被疾病票數、問卷與 Safety 規則引用，因此不可在此重新命名或刪除。</p>
        </div>
      </section>
    </div>

    <form v-if="editing" class="publish-panel" @submit.prevent="saveLabels">
      <header>
        <div>
          <span>CLINICAL SIGN-OFF</span>
          <h3>覆核並發布標籤定義與 Safety 狀態</h3>
        </div>
        <button type="button" class="secondary-action" @click="cancelEdit">放棄草稿</button>
      </header>

      <div v-if="changedLabels.length" class="change-preview">
        <strong>本次變更（{{ changedLabels.length }}）</strong>
        <ul>
          <li v-for="item in changedLabels" :key="item.code">
            <code>{{ item.code }}</code>
            {{ originalLabels.get(item.code)?.description }} → {{ item.description.trim() }}
            <b v-if="item.is_safety !== originalLabels.get(item.code)?.is_safety">
              （{{ item.is_safety ? '設為 Safety：命中即停止' : '改為一般投票標籤' }}）
            </b>
          </li>
        </ul>
      </div>
      <p v-else class="governance-note">尚未修改任何 ClinicalFact 標籤。</p>

      <div class="signoff-grid">
        <label>
          變更理由
          <textarea
            v-model="changeNote"
            rows="3"
            maxlength="500"
            placeholder="例如：依臨床會議統一標籤描述"
          />
        </label>
        <label>
          輸入「{{ rulebook.fact_confirmation_text }}」確認
          <input
            v-model="confirmation"
            :placeholder="rulebook.fact_confirmation_text"
          />
        </label>
      </div>

      <div class="publish-actions">
        <p>發布前會檢查完整 99 個 code、版本衝突並保存前版快照。</p>
        <button type="submit" class="primary-action" :disabled="!canSave || saving">
          {{ saving ? '驗證與發布中…' : '簽署並發布標籤設定' }}
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.fact-label-governance {
  padding: 22px;
  background: var(--surface-1);
}

.governance-heading,
.selected-label-heading,
.draft-summary,
.publish-panel > header,
.publish-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.governance-heading h2,
.selected-label-heading h3,
.publish-panel h3 {
  margin: 4px 0 5px;
}

.governance-heading p,
.publish-actions p,
.immutability-note p {
  margin: 0;
  color: var(--muted);
}

.governance-heading > div > span,
.selected-label-heading > div > span,
.publish-panel header span {
  color: var(--green);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.primary-action,
.secondary-action,
.category-tabs button {
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

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.secondary-action,
.category-tabs button {
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text);
}

.locked-badge,
.category-badges em {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 8px;
  color: var(--muted);
  font-size: 11px;
  font-style: normal;
}

.triage-badge {
  display: inline-flex;
  width: fit-content;
  margin-top: 8px;
  padding: 5px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.triage-badge.vote {
  background: var(--green-soft);
  color: var(--green);
}

.triage-badge.safety {
  background: #fff0f1;
  color: var(--danger);
}

.category-tabs {
  display: flex;
  gap: 6px;
  margin: 18px 0 12px;
  padding-bottom: 4px;
  overflow-x: auto;
}

.category-tabs button {
  display: flex;
  flex: 0 0 auto;
  gap: 7px;
  padding: 7px 10px;
  font-size: 12px;
}

.category-tabs button.active {
  border-color: var(--green);
  background: var(--green-soft);
  color: var(--green);
}

.draft-summary,
.governance-note,
.immutability-note {
  margin: 12px 0;
  padding: 12px;
  border-radius: 10px;
  background: var(--surface-2);
}

.draft-summary small,
.description-preview small,
.description-editor small {
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
  grid-template-columns: 300px minmax(0, 1fr);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}

.label-picker {
  padding: 14px;
  border-right: 1px solid var(--border);
  background: var(--surface-2);
}

.label-picker > label,
.description-editor,
.signoff-grid label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.label-picker input,
.description-editor textarea,
.signoff-grid input,
.signoff-grid textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  padding: 8px 9px;
  font: inherit;
}

.label-options {
  display: grid;
  gap: 6px;
  max-height: 570px;
  margin-top: 12px;
  overflow-y: auto;
}

.label-options button {
  display: grid;
  min-width: 0;
  gap: 3px;
  width: 100%;
  padding: 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.label-options button.active {
  border-color: color-mix(in srgb, var(--green) 40%, var(--border));
  background: var(--green-soft);
}

.label-options button.changed {
  box-shadow: inset 3px 0 var(--warning);
}

.label-options code,
.selected-label-heading code,
.change-preview code {
  color: var(--green);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.label-options small {
  color: var(--muted);
  font-size: 10px;
}

.label-manager {
  min-width: 0;
  padding: 20px;
}

.usage-summary {
  display: grid;
  flex: 0 0 auto;
  grid-template-columns: auto minmax(110px, auto);
  align-items: baseline;
  gap: 2px 7px;
  min-width: 155px;
  color: var(--muted);
  text-align: right;
}

.usage-summary strong {
  color: var(--green);
}

.usage-summary small {
  white-space: nowrap;
}

.category-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 12px;
}

.safety-toggle-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 16px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-2);
}

.safety-toggle-card.selected {
  border-color: color-mix(in srgb, var(--danger) 42%, var(--border));
  background: color-mix(in srgb, #fff0f1 48%, var(--surface-1));
}

.safety-toggle-card input {
  width: 18px;
  height: 18px;
  margin-top: 1px;
  accent-color: var(--danger);
}

.safety-toggle-card span {
  display: grid;
  gap: 4px;
}

.safety-toggle-card small,
.conditional-rule-note p {
  color: var(--muted);
  line-height: 1.55;
}

.conditional-rule-note {
  margin-top: 10px;
  padding: 12px;
  border-left: 3px solid var(--warning);
  border-radius: 8px;
  background: var(--warning-soft);
}

.conditional-rule-note p {
  margin: 4px 0 0;
  font-size: 12px;
}

.description-editor,
.description-preview {
  margin-top: 18px;
}

.description-editor small {
  text-align: right;
}

.description-preview {
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
}

.description-preview p {
  margin: 7px 0 0;
  line-height: 1.7;
}

.immutability-note {
  margin-top: 16px;
}

.immutability-note p {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
}

.publish-panel {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid color-mix(in srgb, var(--green) 45%, var(--border));
  border-radius: 12px;
  background: color-mix(in srgb, var(--green-soft) 35%, var(--surface-1));
}

.change-preview {
  margin: 14px 0;
  padding: 12px;
  border-radius: 8px;
  background: var(--surface-1);
}

.change-preview ul {
  display: grid;
  gap: 6px;
  margin: 8px 0 0;
  padding-left: 18px;
}

.signoff-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 12px;
}

.publish-actions {
  margin-top: 15px;
}

.empty-state {
  padding: 18px;
  color: var(--muted);
  text-align: center;
}

@media (max-width: 720px) {
  .fact-label-governance {
    padding: 14px;
  }

  .governance-heading,
  .selected-label-heading,
  .draft-summary,
  .publish-panel > header,
  .publish-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .governance-workspace,
  .signoff-grid {
    grid-template-columns: 1fr;
  }

  .label-picker {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }

  .label-options {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-height: 240px;
  }

  .usage-summary {
    min-width: 0;
    text-align: left;
  }
}
</style>
