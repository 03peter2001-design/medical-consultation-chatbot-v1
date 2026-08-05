<script setup>
import { computed, ref, watch } from 'vue'

import { api } from '../services/backend.js'
import {
  getRuleSaveChecks,
  getRuleSaveValidationError,
} from '../services/ruleEditor.js'

const props = defineProps({
  rulebook: { type: Object, required: true },
  authorized: { type: Boolean, default: false },
  adminToken: { type: String, default: '' },
  sessionId: { type: String, required: true },
})

const emit = defineEmits(['saved'])

const routeLabels = {
  chest: '胸痛',
  headache: '頭痛',
  abdomen: '腹痛',
}

const categoryOptions = [
  { id: 'all', label: '全部群組' },
  { id: 'universal', label: '共通' },
  { id: 'chest', label: '胸痛' },
  { id: 'headache', label: '頭痛' },
  { id: 'abdomen', label: '腹痛' },
  { id: 'structured', label: '結構化' },
]

const featureCategoryOptions = [
  { id: 'all', label: '全部特徵' },
  { id: 'safety', label: '直接停止' },
  { id: 'chest', label: '胸痛' },
  { id: 'headache', label: '頭痛' },
  { id: 'abdomen', label: '腹痛' },
  { id: 'common', label: '共通' },
]

const drafts = ref([])
const activeGroupId = ref('')
const activeCategory = ref('all')
const searchText = ref('')
const editing = ref(false)
const saving = ref(false)
const assistantBusy = ref(false)
const assistantMessage = ref('')
const assistantHistory = ref([])
const featureSearch = ref('')
const activeFeatureCategory = ref('all')
const changeNote = ref('')
const confirmation = ref('')
const validationError = ref('')
const error = ref('')
const success = ref('')

function nonemptyLines(value) {
  return String(value || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function cloneGroups(groups) {
  return JSON.parse(JSON.stringify(groups || [])).map((group) => ({
    ...group,
    categories: group.categories || [],
    conditionsText: group.possible_conditions.join('\n'),
    rules: group.rules.map((rule) => {
      const when = rule.when || {}
      const featureMode = when.all_findings
        ? 'all_findings'
        : 'any_findings'
      const otherConditions = Object.fromEntries(
        Object.entries(when).filter(
          ([key]) =>
            key !== 'any_findings' && key !== 'all_findings',
        ),
      )
      return {
        ...rule,
        termsText: (rule.terms || []).join('\n'),
        featureMode,
        selectedFeatures: [...(when[featureMode] || [])],
        conditionText: JSON.stringify(
          rule.kind === 'structured'
            ? otherConditions
            : rule.all_term_groups || {},
          null,
          2,
        ),
      }
    }),
  }))
}

function ensureActiveGroup() {
  if (
    !drafts.value.some(
      (group) => group.original_label === activeGroupId.value,
    )
  ) {
    activeGroupId.value = drafts.value[0]?.original_label || ''
  }
}

watch(
  () => props.rulebook,
  (rulebook) => {
    if (!editing.value) {
      drafts.value = cloneGroups(rulebook.safety_groups)
      ensureActiveGroup()
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

const visibleGroups = computed(() => {
  const query = searchText.value.trim().toLowerCase()
  return drafts.value.filter((group) => {
    const categoryMatch =
      activeCategory.value === 'all' ||
      group.categories.includes(activeCategory.value)
    if (!categoryMatch) return false
    if (!query) return true
    return [
      group.label,
      group.original_label,
      ...group.possible_conditions,
      ...group.rules.flatMap((rule) => [
        rule.code,
        ...(rule.terms || []),
        JSON.stringify(rule.when || rule.all_term_groups || {}),
      ]),
    ]
      .join(' ')
      .toLowerCase()
      .includes(query)
  })
})

const activeGroup = computed(() =>
  drafts.value.find(
    (group) => group.original_label === activeGroupId.value,
  ),
)

const categoryCounts = computed(() =>
  Object.fromEntries(
    categoryOptions.map((category) => [
      category.id,
      category.id === 'all'
        ? drafts.value.length
        : drafts.value.filter((group) =>
            group.categories.includes(category.id),
          ).length,
    ]),
  ),
)

const visibleFacts = computed(() => {
  const query = featureSearch.value.trim().toLowerCase()
  return (props.rulebook.fact_catalog || []).filter((fact) => {
    const categoryMatch =
      activeFeatureCategory.value === 'all' ||
      fact.categories.includes(activeFeatureCategory.value)
    return (
      categoryMatch &&
      (!query ||
        `${fact.code} ${fact.description}`
          .toLowerCase()
          .includes(query))
    )
  })
})

function buildRule(rule) {
  const result = {
    code: rule.code,
    kind: rule.kind,
    scope: rule.scope,
    route: rule.route,
    level: rule.level,
  }
  if (rule.kind === 'phrase') {
    result.terms = nonemptyLines(rule.termsText)
    return result
  }
  let parsed
  try {
    parsed = JSON.parse(rule.conditionText)
  } catch {
    throw new Error(`${rule.code} 的 JSON 條件格式錯誤`)
  }
  if (rule.kind === 'structured') {
    delete parsed.any_findings
    delete parsed.all_findings
    if (rule.selectedFeatures.length) {
      parsed[rule.featureMode] = [...new Set(rule.selectedFeatures)]
    }
    result.when = parsed
  } else {
    result.all_term_groups = parsed
  }
  return result
}

function buildGroup(group) {
  return {
    original_label: group.original_label,
    label: group.label.trim(),
    possible_conditions: nonemptyLines(group.conditionsText),
    categories: group.categories,
    rules: group.rules.map(buildRule),
  }
}

function buildPayloadGroups() {
  return drafts.value.map(buildGroup)
}

function originalComparable(group) {
  return {
    original_label: group.original_label,
    label: group.label,
    possible_conditions: group.possible_conditions,
    categories: group.categories,
    rules: group.rules,
  }
}

const changedGroups = computed(() => {
  const originals = new Map(
    props.rulebook.safety_groups.map((group) => [
      group.original_label,
      group,
    ]),
  )
  return drafts.value.filter((group) => {
    try {
      return (
        JSON.stringify(buildGroup(group)) !==
        JSON.stringify(originalComparable(originals.get(group.original_label)))
      )
    } catch {
      return true
    }
  })
})

const saveChecks = computed(() =>
  getRuleSaveChecks({
    authorized: props.authorized,
    editing: editing.value,
    selectedCount: activeGroup.value ? 1 : 0,
    changeNote: changeNote.value,
    confirmation: confirmation.value,
    confirmationText: props.rulebook.confirmation_text,
  }),
)

const canSave = computed(
  () =>
    changedGroups.value.length > 0 &&
    saveChecks.value.every((check) => check.complete),
)

function selectGroup(groupId) {
  activeGroupId.value = groupId
  featureSearch.value = ''
  activeFeatureCategory.value = 'all'
  error.value = ''
}

function beginEdit() {
  if (!props.authorized || !activeGroup.value) return
  drafts.value = cloneGroups(props.rulebook.safety_groups)
  ensureActiveGroup()
  editing.value = true
  changeNote.value = ''
  confirmation.value = ''
  validationError.value = ''
  assistantHistory.value = []
  error.value = ''
  success.value = ''
}

function cancelEdit() {
  drafts.value = cloneGroups(props.rulebook.safety_groups)
  editing.value = false
  changeNote.value = ''
  confirmation.value = ''
  validationError.value = ''
  assistantHistory.value = []
  error.value = ''
  ensureActiveGroup()
}

function scopeLabel(rule) {
  if (rule.kind === 'structured') return '結構化條件'
  if (rule.scope === 'universal') return '所有主訴'
  if (rule.scope === 'route') {
    return `${routeLabels[rule.route] || rule.route}原文`
  }
  return '複合原文條件'
}

function categoryLabel(category) {
  return (
    categoryOptions.find((item) => item.id === category)?.label ||
    category
  )
}

function factCategoryLabel(category) {
  return (
    featureCategoryOptions.find((item) => item.id === category)
      ?.label || category
  )
}

async function askAssistant() {
  const message = assistantMessage.value.trim()
  if (
    !props.authorized ||
    !editing.value ||
    !activeGroup.value ||
    !message ||
    assistantBusy.value
  ) {
    return
  }
  assistantBusy.value = true
  error.value = ''
  assistantHistory.value.push({ role: 'user', content: message })
  assistantMessage.value = ''
  try {
    const result = await api.suggestRuleEdits(
      {
        message,
        selected_labels: [activeGroup.value.original_label],
        safety_groups: buildPayloadGroups(),
        history: assistantHistory.value.slice(0, -1),
      },
      props.adminToken,
    )
    drafts.value = cloneGroups(result.safety_groups)
    assistantHistory.value.push({
      role: 'assistant',
      content: `${result.reply}（僅套用至草稿，尚未儲存）`,
    })
  } catch (requestError) {
    assistantHistory.value.pop()
    error.value = requestError.message
  } finally {
    assistantBusy.value = false
  }
}

async function saveRules() {
  if (saving.value) return
  validationError.value = getRuleSaveValidationError(saveChecks.value)
  if (!changedGroups.value.length) {
    validationError.value = '尚未修改任何 Safety 規則。'
  }
  if (!canSave.value) return
  if (
    !window.confirm(
      'Safety 規則更新後會立即套用至所有新問診。確定發布嗎？',
    )
  ) {
    return
  }
  saving.value = true
  error.value = ''
  success.value = ''
  try {
    const updated = await api.updateSafetyRules(
      {
        session_id: props.sessionId,
        expected_revision: props.rulebook.revision,
        confirmation: confirmation.value.trim(),
        change_note: changeNote.value.trim(),
        safety_groups: buildPayloadGroups(),
      },
      props.adminToken,
    )
    drafts.value = cloneGroups(updated.safety_groups)
    editing.value = false
    changeNote.value = ''
    confirmation.value = ''
    validationError.value = ''
    assistantHistory.value = []
    success.value = 'Safety 規則已建立稽核快照並發布。'
    emit('saved', updated)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="governance-section safety-governance">
    <header class="governance-heading">
      <div>
        <span>SAFETY RULE GOVERNANCE</span>
        <h2>組合與原文 Safety 規則</h2>
        <p>管理必須符合多個條件或特定原文才停止的進階規則；單一 Safety 標籤請在上方勾選。</p>
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
      <li class="complete"><b>1</b><span>選擇分類<br /><small>共通、路由、結構化</small></span></li>
      <li :class="{ complete: activeGroup }"><b>2</b><span>選擇規則群組<br /><small>一次檢視一組條件</small></span></li>
      <li :class="{ complete: editing }"><b>3</b><span>管理規則<br /><small>鑑別方向與觸發條件</small></span></li>
      <li :class="{ complete: success }"><b>4</b><span>簽署發布<br /><small>快照與版本稽核</small></span></li>
    </ol>

    <div class="category-tabs" aria-label="組合 Safety 規則分類">
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
            v-for="group in visibleGroups"
            :key="group.original_label"
            type="button"
            :class="{
              active: activeGroupId === group.original_label,
              changed: changedGroups.includes(group),
            }"
            @click="selectGroup(group.original_label)"
          >
            <span>
              <strong>{{ group.label }}</strong>
              <small>{{ group.rules.length }} 條規則 · {{ group.possible_conditions.length }} 個方向</small>
            </span>
            <i v-if="changedGroups.includes(group)">已修改</i>
          </button>
        </div>
        <p v-if="!visibleGroups.length" class="empty-state">找不到 Safety 規則群組。</p>
      </aside>

      <section v-if="activeGroup" class="rule-manager">
        <header class="selected-rule-heading">
          <div>
            <span>SELECTED SAFETY RULE GROUP</span>
            <h3>{{ activeGroup.label }}</h3>
            <div class="category-badges">
              <em v-for="category in activeGroup.categories" :key="category">
                {{ categoryLabel(category) }}
              </em>
            </div>
          </div>
          <strong>{{ activeGroup.rules.length }} 條規則</strong>
        </header>

        <template v-if="editing">
          <div class="group-fields">
            <label>
              規則群組名稱
              <input v-model="activeGroup.label" maxlength="80" />
            </label>
            <label>
              觸發後鑑別方向（一行一項）
              <textarea v-model="activeGroup.conditionsText" rows="4" />
            </label>
          </div>
        </template>
        <ul v-else class="condition-tags">
          <li
            v-for="condition in activeGroup.possible_conditions"
            :key="condition"
          >
            {{ condition }}
          </li>
        </ul>

        <div class="implementation-list">
          <article
            v-for="rule in activeGroup.rules"
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
                    v-for="category in featureCategoryOptions"
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
                      <small>{{ fact.categories.map(factCategoryLabel).join(' · ') }}</small>
                    </span>
                  </label>
                </div>
                <label>
                  其他進階條件 JSON
                  <textarea v-model="rule.conditionText" class="json-editor" rows="6" />
                </label>
              </div>

              <label v-else>
                複合原文條件 JSON
                <textarea v-model="rule.conditionText" class="json-editor" rows="8" />
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

        <section v-if="editing" class="assistant-panel">
          <header>
            <div>
              <span>LLM DRAFT ASSISTANT</span>
              <h4>微調目前 Safety 規則群組</h4>
            </div>
            <small>只修改草稿，不會直接發布</small>
          </header>
          <div v-if="assistantHistory.length" class="assistant-history">
            <p
              v-for="(message, index) in assistantHistory"
              :key="index"
              :class="message.role"
            >
              <b>{{ message.role === 'user' ? '醫師' : '助理' }}</b>
              {{ message.content }}
            </p>
          </div>
          <form class="assistant-input" @submit.prevent="askAssistant">
            <textarea
              v-model="assistantMessage"
              rows="2"
              maxlength="1000"
              placeholder="例如：加入右眼與左眼視力模糊觸發詞"
            />
            <button
              class="primary-action"
              :disabled="!assistantMessage.trim() || assistantBusy"
            >
              {{ assistantBusy ? '產生草稿中…' : '送出微調要求' }}
            </button>
          </form>
        </section>
      </section>
    </div>

    <form v-if="editing" class="publish-panel" @submit.prevent="saveRules">
      <header>
        <div>
          <span>CLINICAL SIGN-OFF</span>
          <h3>覆核並發布 Safety 規則</h3>
        </div>
        <button type="button" class="secondary-action" @click="cancelEdit">放棄草稿</button>
      </header>

      <div v-if="changedGroups.length" class="change-preview">
        <strong>本次變更（{{ changedGroups.length }}）</strong>
        <ul>
          <li v-for="group in changedGroups" :key="group.original_label">
            {{ group.original_label }} → {{ group.label }}
          </li>
        </ul>
      </div>
      <p v-else class="governance-note">尚未修改任何 Safety 規則。</p>

      <div class="signoff-grid">
        <label>
          變更理由
          <textarea
            v-model="changeNote"
            rows="3"
            maxlength="500"
            placeholder="例如：依急診科會議調整視力警訊用語"
          />
        </label>
        <label>
          輸入「{{ rulebook.confirmation_text }}」確認
          <input v-model="confirmation" :placeholder="rulebook.confirmation_text" />
        </label>
      </div>

      <p v-if="validationError" class="validation-error">{{ validationError }}</p>
      <div class="publish-actions">
        <p>發布後會保存前版快照、檢查版本衝突，並立即套用至後續新問診。</p>
        <button type="submit" class="primary-action" :disabled="!canSave || saving">
          {{ saving ? '驗證與發布中…' : '簽署並發布 Safety 規則' }}
        </button>
      </div>
    </form>
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
.publish-panel > header,
.publish-actions,
.selected-rule-heading,
.draft-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.governance-heading h2,
.selected-rule-heading h3,
.publish-panel h3 {
  margin: 4px 0 5px;
}

.governance-heading p,
.publish-actions p {
  margin: 0;
  color: var(--muted);
}

.governance-heading > div > span,
.selected-rule-heading > div > span,
.publish-panel header span,
.assistant-panel header span {
  color: var(--blue);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.primary-action,
.secondary-action,
.category-tabs button,
.feature-tabs button {
  border-radius: 8px;
  padding: 9px 13px;
  cursor: pointer;
}

.primary-action {
  border: 0;
  background: var(--blue);
  color: #fff;
  font-weight: 700;
}

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.secondary-action,
.category-tabs button,
.feature-tabs button {
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

.category-tabs,
.feature-tabs {
  display: flex;
  gap: 6px;
  margin: 12px 0;
  padding-bottom: 4px;
  overflow-x: auto;
}

.category-tabs button,
.feature-tabs button {
  display: flex;
  flex: 0 0 auto;
  gap: 7px;
  padding: 7px 10px;
  font-size: 12px;
}

.category-tabs button.active,
.feature-tabs button.active {
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

.governance-note,
.validation-error {
  margin: 12px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--muted);
}

.governance-note.error,
.validation-error {
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

.group-picker {
  padding: 14px;
  border-right: 1px solid var(--border);
  background: var(--surface-2);
}

.group-picker > label,
.group-fields label,
.implementation-card label,
.feature-search,
.signoff-grid label,
.structured-heading label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.group-picker input,
.group-fields input,
.group-fields textarea,
.implementation-card textarea,
.implementation-card input,
.implementation-card select,
.signoff-grid input,
.signoff-grid textarea,
.assistant-input textarea {
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

.rule-manager {
  min-width: 0;
  padding: 18px;
}

.category-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 7px;
}

.selected-rule-heading > strong {
  color: var(--blue);
  font-size: 12px;
}

.group-fields {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  gap: 10px;
  margin-top: 16px;
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

.implementation-card > header,
.structured-heading,
.assistant-panel > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.implementation-card > header > div {
  display: grid;
  gap: 2px;
}

.implementation-card code,
.change-preview code {
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
.structured-editor {
  margin-top: 10px;
}

.feature-search {
  margin-top: 10px;
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

.assistant-panel {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--blue) 35%, var(--border));
  border-radius: 9px;
  background: var(--blue-soft);
}

.assistant-panel h4 {
  margin-top: 3px;
}

.assistant-panel header small {
  color: var(--muted);
}

.assistant-history {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.assistant-history p {
  padding: 8px;
  border-radius: 7px;
  background: var(--surface-1);
  font-size: 12px;
}

.assistant-input {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  margin-top: 10px;
}

.publish-panel {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid color-mix(in srgb, var(--blue) 45%, var(--border));
  border-radius: 12px;
  background: color-mix(in srgb, var(--blue-soft) 35%, var(--surface-1));
}

.change-preview {
  margin: 14px 0;
  padding: 12px;
  border-radius: 8px;
  background: var(--surface-1);
}

.change-preview ul {
  max-height: 150px;
  margin: 8px 0 0;
  padding-left: 20px;
  overflow: auto;
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

@media (max-width: 900px) {
  .governance-workspace {
    grid-template-columns: 220px minmax(0, 1fr);
  }

  .feature-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .governance-section {
    padding: 14px;
  }

  .governance-heading,
  .publish-actions,
  .publish-panel > header,
  .selected-rule-heading,
  .draft-summary,
  .assistant-panel > header {
    align-items: stretch;
    flex-direction: column;
  }

  .governance-flow {
    grid-template-columns: 1fr 1fr;
  }

  .governance-workspace {
    grid-template-columns: 1fr;
  }

  .group-picker {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }

  .group-options {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-height: 240px;
  }

  .group-fields,
  .signoff-grid,
  .assistant-input {
    grid-template-columns: 1fr;
  }
}
</style>
