<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import AppHeader from '../components/AppHeader.vue'
import { api, connectionError } from '../services/backend.js'
import {
  getRuleSaveChecks,
  getRuleSaveValidationError,
} from '../services/ruleEditor.js'

const sessionId = `rule_admin_${Date.now()}`
const rulebook = ref(null)
const draftGroups = ref([])
const loading = ref(true)
const authorized = ref(false)
const authorizing = ref(false)
const editing = ref(false)
const saving = ref(false)
const assistantBusy = ref(false)
const error = ref('')
const success = ref('')
const saveSucceeded = ref(false)
const adminToken = ref('')
const searchText = ref('')
const activeCategory = ref('all')
const selectedLabels = ref([])
const changeNote = ref('')
const confirmation = ref('')
const saveValidationError = ref('')
const assistantMessage = ref('')
const assistantHistory = ref([])
const featureSearch = ref('')
const activeFeatureCategory = ref('all')

const routeLabels = {
  chest: '胸痛',
  headache: '頭痛',
  abdomen: '腹痛',
}

const categoryOptions = [
  { id: 'all', label: '全部' },
  { id: 'universal', label: '共通' },
  { id: 'chest', label: '胸痛' },
  { id: 'headache', label: '頭痛' },
  { id: 'abdomen', label: '腹痛' },
  { id: 'structured', label: '結構化' },
]

const featureCategoryOptions = [
  { id: 'all', label: '全部特徵' },
  { id: 'safety', label: 'Safety' },
  { id: 'chest', label: '胸痛' },
  { id: 'headache', label: '頭痛' },
  { id: 'abdomen', label: '腹痛' },
  { id: 'common', label: '共通' },
]

const visibleGroups = computed(() => {
  const query = searchText.value.trim().toLowerCase()
  return draftGroups.value.filter((group) => {
    const categoryMatch =
      activeCategory.value === 'all' ||
      group.categories.includes(activeCategory.value)
    if (!categoryMatch) return false
    if (!query) return true
    const haystack = [
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
    return haystack.includes(query)
  })
})

const selectedGroups = computed(() =>
  draftGroups.value.filter((group) =>
    selectedLabels.value.includes(group.original_label),
  ),
)

const visibleFacts = computed(() => {
  const query = featureSearch.value.trim().toLowerCase()
  return (rulebook.value?.fact_catalog || []).filter((fact) => {
    const categoryMatch =
      activeFeatureCategory.value === 'all' ||
      fact.categories.includes(activeFeatureCategory.value)
    if (!categoryMatch) return false
    return (
      !query ||
      `${fact.code} ${fact.description}`.toLowerCase().includes(query)
    )
  })
})

const saveChecks = computed(() =>
  getRuleSaveChecks({
    authorized: authorized.value,
    editing: editing.value,
    selectedCount: selectedLabels.value.length,
    changeNote: changeNote.value,
    confirmation: confirmation.value,
    confirmationText: rulebook.value?.confirmation_text,
  }),
)

const canSave = computed(() =>
  saveChecks.value.every((check) => check.complete),
)

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
        selectedFeatures: [
          ...(when[featureMode] || []),
        ],
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

function nonemptyLines(value) {
  return String(value || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
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

function buildPayloadGroups() {
  return draftGroups.value.map((group) => ({
    original_label: group.original_label,
    label: group.label.trim(),
    possible_conditions: nonemptyLines(group.conditionsText),
    categories: group.categories,
    rules: group.rules.map((rule) => {
      const result = {
        code: rule.code,
        kind: rule.kind,
        scope: rule.scope,
        route: rule.route,
        level: rule.level,
      }
      if (rule.kind === 'phrase') {
        result.terms = nonemptyLines(rule.termsText)
      } else {
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
            parsed[rule.featureMode] = [
              ...new Set(rule.selectedFeatures),
            ]
          }
          result.when = parsed
        } else result.all_term_groups = parsed
      }
      return result
    }),
  }))
}

async function loadRules() {
  loading.value = true
  error.value = ''
  try {
    rulebook.value = await api.loadRuleCenter()
    draftGroups.value = cloneGroups(rulebook.value.safety_groups)
  } catch (requestError) {
    error.value = connectionError(requestError)
  } finally {
    loading.value = false
  }
}

async function unlockEditing() {
  if (!adminToken.value.trim() || authorizing.value) return
  authorizing.value = true
  error.value = ''
  try {
    await api.authorizeRuleEditor(adminToken.value)
    authorized.value = true
    success.value = '權杖驗證成功，可以勾選要調整的標籤。'
  } catch (requestError) {
    authorized.value = false
    error.value = requestError.message
  } finally {
    authorizing.value = false
  }
}

function lockEditing() {
  authorized.value = false
  editing.value = false
  selectedLabels.value = []
  adminToken.value = ''
  assistantHistory.value = []
}

function beginEdit() {
  if (!authorized.value || selectedLabels.value.length === 0) return
  changeNote.value = ''
  confirmation.value = ''
  success.value = ''
  saveSucceeded.value = false
  error.value = ''
  saveValidationError.value = ''
  editing.value = true
}

async function openGroupEditor(originalLabel, event) {
  if (!authorized.value || editing.value) return
  event?.preventDefault()
  selectedLabels.value = [originalLabel]
  beginEdit()
  await nextTick()
  document
    .querySelector('.editor-workspace')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function cancelEdit() {
  draftGroups.value = cloneGroups(rulebook.value.safety_groups)
  editing.value = false
  assistantHistory.value = []
  error.value = ''
  saveValidationError.value = ''
}

function toggleVisible() {
  const visible = visibleGroups.value.map((group) => group.original_label)
  const allSelected = visible.every((label) =>
    selectedLabels.value.includes(label),
  )
  selectedLabels.value = allSelected
    ? selectedLabels.value.filter((label) => !visible.includes(label))
    : [...new Set([...selectedLabels.value, ...visible])]
}

async function askAssistant() {
  const message = assistantMessage.value.trim()
  if (
    !authorized.value ||
    !message ||
    selectedLabels.value.length === 0 ||
    selectedLabels.value.length > 5 ||
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
        selected_labels: selectedLabels.value,
        safety_groups: buildPayloadGroups(),
        history: assistantHistory.value.slice(0, -1),
      },
      adminToken.value,
    )
    draftGroups.value = cloneGroups(result.safety_groups)
    assistantHistory.value.push({
      role: 'assistant',
      content: `${result.reply}（僅套用至草稿，尚未儲存）`,
    })
    editing.value = true
  } catch (requestError) {
    assistantHistory.value.pop()
    error.value = requestError.message
  } finally {
    assistantBusy.value = false
  }
}

async function saveRules() {
  if (saving.value) return
  saveValidationError.value = getRuleSaveValidationError(
    saveChecks.value,
  )
  if (!canSave.value) return
  if (
    !window.confirm(
      'Safety 規則更新後會立即套用至所有新問診。確定要繼續嗎？',
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
        session_id: sessionId,
        expected_revision: rulebook.value.revision,
        confirmation: confirmation.value.trim(),
        change_note: changeNote.value.trim(),
        safety_groups: buildPayloadGroups(),
      },
      adminToken.value,
    )
    rulebook.value = updated
    draftGroups.value = cloneGroups(updated.safety_groups)
    editing.value = false
    selectedLabels.value = []
    confirmation.value = ''
    changeNote.value = ''
    saveValidationError.value = ''
    assistantHistory.value = []
    success.value = 'Safety 規則已驗證、建立快照並立即更新。'
    saveSucceeded.value = true
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    saving.value = false
  }
}

onMounted(loadRules)
</script>

<template>
  <div class="app-shell rule-center-app">
    <AppHeader
      icon="⚙"
      title="醫師端規則中心"
      subtitle="全局決策邏輯 / Safety / 疾病表版本"
      :status="
        loading
          ? '載入中…'
          : authorized
            ? '已同步 · 已解鎖'
            : rulebook?.edit_enabled
              ? '已同步 · 已鎖定'
            : '唯讀檢視已同步'
      "
      status-tone="online"
    >
      <RouterLink class="nav-link" to="/doctor">← 返回醫師工作區</RouterLink>
      <RouterLink class="nav-link" to="/doctor/terminology/snomed">
        SNOMED CT
      </RouterLink>
      <RouterLink class="nav-link" to="/">病患問診端</RouterLink>
    </AppHeader>

    <div
      v-if="saveSucceeded"
      class="save-success-toast"
      role="status"
      aria-live="assertive"
    >
      <div>
        <strong>Safety 規則更新成功</strong>
        <span>新版本已保存並立即套用至後續問診。</span>
      </div>
      <button
        type="button"
        aria-label="關閉更新成功提示"
        @click="saveSucceeded = false"
      >
        ×
      </button>
    </div>

    <main class="rule-center">
      <div v-if="loading" class="state-card">正在載入規則…</div>
      <div v-else-if="!rulebook" class="state-card error">{{ error }}</div>

      <template v-else>
        <section class="page-heading">
          <div>
            <span>GLOBAL LOGIC</span>
            <h1>問診決策全貌</h1>
            <p>
              此處呈現實際執行中的確定性規則；Safety 永遠優先於疾病投票。
            </p>
          </div>
          <div class="revision">
            <small>目前版本</small>
            <code>{{ rulebook.revision.slice(0, 12) }}</code>
          </div>
        </section>

        <section class="flow-grid" aria-label="全局決策流程">
          <article v-for="item in rulebook.flow" :key="item.step">
            <b>{{ item.step }}</b>
            <div>
              <h2>{{ item.name }}</h2>
              <p>{{ item.description }}</p>
            </div>
          </article>
        </section>

        <section class="rule-section">
          <div class="section-heading">
            <div>
              <span>ROUTE PROFILES</span>
              <h2>三路由投票政策</h2>
            </div>
            <strong>{{ rulebook.fact_count }} 個 ClinicalFact</strong>
          </div>
          <div class="route-grid">
            <article v-for="route in rulebook.routes" :key="route.route">
              <header>
                <h3>{{ routeLabels[route.route] }}</h3>
                <span v-if="route.provisional">未經醫師校準</span>
              </header>
              <dl>
                <div>
                  <dt>疾病表</dt>
                  <dd>{{ route.profile_version }}</dd>
                </div>
                <div>
                  <dt>疾病方向</dt>
                  <dd>{{ route.profile_count }} 項</dd>
                </div>
                <div>
                  <dt>不能漏診</dt>
                  <dd>{{ route.must_not_miss_count }} 項</dd>
                </div>
                <div>
                  <dt>完整度門檻</dt>
                  <dd>{{ route.policy.coverage_threshold * 100 }}%</dd>
                </div>
                <div>
                  <dt>最多輪數</dt>
                  <dd>{{ route.policy.max_turns }}</dd>
                </div>
              </dl>
            </article>
          </div>
        </section>

        <section class="rule-section safety-section">
          <div class="section-heading">
            <div>
              <span>SAFETY RULEBOOK</span>
              <h2>安全規則與鑑別標籤</h2>
              <p>搜尋、分類並勾選要調整的標籤；未通過權杖驗證前只能查看。</p>
            </div>
            <strong>{{ draftGroups.length }} 個標籤</strong>
          </div>

          <div v-if="!rulebook.edit_enabled" class="readonly-note">
            目前為唯讀。請由系統管理員在後端設定
            <code>SAFETY_RULE_ADMIN_TOKEN</code> 後重新啟動。
          </div>
          <form
            v-else-if="!authorized"
            class="unlock-panel"
            @submit.prevent="unlockEditing"
          >
            <div>
              <strong>先驗證管理權杖</strong>
              <p>驗證成功後才會顯示勾選、手動編輯與 LLM 草稿功能。</p>
            </div>
            <input
              v-model="adminToken"
              type="password"
              autocomplete="off"
              placeholder="SAFETY_RULE_ADMIN_TOKEN"
              aria-label="規則管理權杖"
            />
            <button
              class="primary-action"
              :disabled="!adminToken.trim() || authorizing"
            >
              {{ authorizing ? '驗證中…' : '解鎖編輯' }}
            </button>
          </form>
          <div v-else class="authorized-bar">
            <div>
              <span class="authorized-dot" />
              <strong>權杖已驗證</strong>
              <small>已勾選 {{ selectedLabels.length }} 個標籤</small>
            </div>
            <button class="secondary-action" @click="lockEditing">
              鎖定並清除權杖
            </button>
          </div>
          <div v-if="success" class="success-note">{{ success }}</div>
          <div v-if="error" class="error-note">{{ error }}</div>

          <div class="rule-toolbar">
            <label class="search-field">
              搜尋標籤、規則代碼、觸發詞或鑑別方向
              <input
                v-model="searchText"
                type="search"
                placeholder="例如：視力、頭痛、semantic_vision_loss"
              />
            </label>
            <div class="category-tabs" aria-label="Safety 規則分類">
              <button
                v-for="category in categoryOptions"
                :key="category.id"
                :class="{ active: activeCategory === category.id }"
                @click="activeCategory = category.id"
              >
                {{ category.label }}
              </button>
            </div>
            <div class="result-meta">
              <span>顯示 {{ visibleGroups.length }} 個標籤</span>
              <button
                v-if="authorized && !editing && visibleGroups.length"
                class="text-action"
                @click="toggleVisible"
              >
                全選／取消目前結果
              </button>
            </div>
          </div>

          <div v-if="!visibleGroups.length" class="empty-result">
            找不到符合目前搜尋與分類的 Safety 標籤。
          </div>

          <div v-else class="safety-list">
            <details
              v-for="group in visibleGroups"
              :key="group.original_label"
              class="safety-card"
              :class="{
                selected: selectedLabels.includes(group.original_label),
              }"
            >
              <summary
                @click="
                  openGroupEditor(group.original_label, $event)
                "
              >
                <label
                  v-if="authorized"
                  class="select-rule"
                  @click.stop
                >
                  <input
                    v-model="selectedLabels"
                    type="checkbox"
                    :value="group.original_label"
                    :disabled="editing"
                  />
                  <span>選取</span>
                </label>
                <div>
                  <strong>{{ group.label }}</strong>
                  <small>
                    {{ group.rules.length }} 條實作 ·
                    {{ group.possible_conditions.length }} 個鑑別方向
                  </small>
                  <div class="category-badges">
                    <span
                      v-for="category in group.categories"
                      :key="category"
                    >
                      {{ categoryLabel(category) }}
                    </span>
                  </div>
                </div>
                <span>{{ authorized ? '點擊編輯' : '展開' }}</span>
              </summary>

              <ul class="condition-tags">
                <li
                  v-for="condition in group.possible_conditions"
                  :key="condition"
                >
                  {{ condition }}
                </li>
              </ul>

              <article
                v-for="rule in group.rules"
                :key="rule.code"
                class="implementation"
              >
                <header>
                  <code>{{ rule.code }}</code>
                  <span>{{ scopeLabel(rule) }}</span>
                </header>
                <p>
                  {{
                    rule.kind === 'phrase'
                      ? rule.terms.join('、')
                      : JSON.stringify(
                          rule.when || rule.all_term_groups,
                        )
                  }}
                </p>
              </article>
            </details>
          </div>

          <section
            v-if="authorized && selectedLabels.length"
            class="assistant-panel"
          >
            <header>
              <div>
                <span>LLM DRAFT ASSISTANT</span>
                <h3>用對話微調已勾選標籤</h3>
                <p>
                  每次最多 5 個。助理只能修改草稿；正式 JSON 必須由醫師再次確認儲存。
                </p>
              </div>
              <button
                v-if="!editing"
                class="secondary-action"
                @click="beginEdit"
              >
                直接手動編輯
              </button>
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
                placeholder="例如：加入「右眼視力模糊」與「左眼視力模糊」觸發詞，不要改其他條件"
              />
              <button
                class="primary-action"
                :disabled="
                  !assistantMessage.trim() ||
                  selectedLabels.length > 5 ||
                  assistantBusy
                "
              >
                {{ assistantBusy ? '產生並驗證草稿中…' : '送出微調要求' }}
              </button>
            </form>
            <p v-if="selectedLabels.length > 5" class="selection-warning">
              LLM 微調每次最多處理 5 個標籤，請取消部分勾選；手動編輯不受此限制。
            </p>
          </section>

          <section v-if="editing" class="editor-workspace">
            <header>
              <div>
                <span>REVIEW DRAFT</span>
                <h3>檢視並編輯已勾選標籤</h3>
              </div>
              <button class="secondary-action" @click="cancelEdit">
                放棄草稿
              </button>
            </header>
            <article
              v-for="group in selectedGroups"
              :key="group.original_label"
              class="selected-editor"
            >
              <div class="edit-grid">
                <label>
                  Safety 標籤
                  <input v-model="group.label" maxlength="80" />
                </label>
                <label>
                  觸發後鑑別方向（一行一項）
                  <textarea v-model="group.conditionsText" rows="4" />
                </label>
              </div>
              <div
                v-for="rule in group.rules"
                :key="rule.code"
                class="implementation"
              >
                <header>
                  <code>{{ rule.code }}</code>
                  <span>{{ scopeLabel(rule) }}</span>
                </header>
                <label v-if="rule.kind === 'phrase'">
                  觸發詞（一行一項）
                  <textarea v-model="rule.termsText" rows="4" />
                </label>
                <div
                  v-else-if="rule.kind === 'structured'"
                  class="semantic-feature-editor"
                >
                  <header class="feature-heading">
                    <div>
                      <strong>語意特徵條件</strong>
                      <small>
                        已選 {{ rule.selectedFeatures.length }} 個
                      </small>
                    </div>
                    <label>
                      判斷方式
                      <select v-model="rule.featureMode">
                        <option value="any_findings">
                          任一特徵成立
                        </option>
                        <option value="all_findings">
                          所有特徵皆成立
                        </option>
                      </select>
                    </label>
                  </header>

                  <div class="feature-toolbar">
                    <label>
                      搜尋語意特徵
                      <input
                        v-model="featureSearch"
                        type="search"
                        placeholder="例如：意識、視力、altered_consciousness"
                      />
                    </label>
                    <div
                      class="category-tabs feature-tabs"
                      aria-label="語意特徵分類"
                    >
                      <button
                        v-for="category in featureCategoryOptions"
                        :key="category.id"
                        :class="{
                          active:
                            activeFeatureCategory === category.id,
                        }"
                        @click="
                          activeFeatureCategory = category.id
                        "
                      >
                        {{ category.label }}
                      </button>
                    </div>
                    <small>
                      顯示 {{ visibleFacts.length }} /
                      {{ rulebook.fact_catalog.length }} 個特徵
                    </small>
                  </div>

                  <div class="feature-grid">
                    <label
                      v-for="fact in visibleFacts"
                      :key="fact.code"
                      class="feature-option"
                      :class="{
                        selected:
                          rule.selectedFeatures.includes(fact.code),
                      }"
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
                          {{
                            fact.categories
                              .map(factCategoryLabel)
                              .join(' · ')
                          }}
                        </small>
                      </span>
                    </label>
                  </div>
                  <div
                    v-if="!visibleFacts.length"
                    class="empty-result compact"
                  >
                    找不到符合條件的語意特徵。
                  </div>

                  <label class="advanced-condition">
                    其他進階條件 JSON
                    <small>
                      primary、severity、onset、risk 等條件會保留於此；
                      語意特徵請使用上方勾選器。
                    </small>
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
              </div>
            </article>
          </section>

          <form v-if="editing" class="save-panel" @submit.prevent="saveRules">
            <label>
              變更理由
              <textarea
                v-model="changeNote"
                rows="2"
                maxlength="500"
                placeholder="例如：依 2026-07 急診科會議調整頭痛警訊用語"
                @input="saveValidationError = ''"
              />
            </label>
            <label>
              輸入「{{ rulebook.confirmation_text }}」確認
              <input
                v-model="confirmation"
                :placeholder="rulebook.confirmation_text"
                @input="saveValidationError = ''"
              />
            </label>
            <div class="save-readiness" aria-live="polite">
              <strong>更新前檢查</strong>
              <ul>
                <li
                  v-for="check in saveChecks"
                  :key="check.id"
                  :class="{ complete: check.complete }"
                >
                  <span aria-hidden="true">
                    {{ check.complete ? '✓' : '○' }}
                  </span>
                  {{ check.label }}
                </li>
              </ul>
              <p v-if="saveValidationError">
                {{ saveValidationError }}
              </p>
            </div>
            <button
              type="submit"
              class="primary-action"
              :disabled="saving"
            >
              {{ saving ? '驗證與更新中…' : '驗證並更新 Safety 規則' }}
            </button>
          </form>
        </section>
      </template>
    </main>
  </div>
</template>

<style scoped>
.rule-center-app {
  min-height: 100dvh;
  background: var(--bg);
}

.rule-center {
  flex: 1;
  min-height: 0;
  width: min(1240px, 100%);
  margin: 0 auto;
  padding: 28px;
  overflow-y: auto;
}

.save-success-toast {
  position: fixed;
  z-index: 100;
  top: calc(var(--header-height) + 14px);
  right: 20px;
  display: flex;
  align-items: flex-start;
  width: min(390px, calc(100vw - 40px));
  padding: 14px 16px;
  border: 1px solid rgb(8 127 109 / 35%);
  border-radius: 9px;
  background: var(--green-soft);
  box-shadow: 0 12px 30px rgb(32 51 69 / 18%);
  color: var(--green);
}

.save-success-toast > div {
  display: grid;
  flex: 1;
  gap: 2px;
}

.save-success-toast span {
  font-size: 12px;
}

.save-success-toast button {
  padding: 0 0 0 12px;
  background: transparent;
  color: var(--green);
  cursor: pointer;
  font-size: 20px;
  line-height: 1;
}

.page-heading,
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.page-heading span,
.section-heading span {
  color: var(--blue);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.page-heading h1 {
  margin: 4px 0;
  font-size: 28px;
}

.page-heading p,
.section-heading p {
  color: var(--muted);
  line-height: 1.6;
}

.revision {
  display: grid;
  gap: 4px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
}

.revision small {
  color: var(--muted);
}

.flow-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-top: 22px;
}

.flow-grid article {
  display: flex;
  gap: 12px;
  min-height: 126px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-1);
}

.flow-grid article > b {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  place-items: center;
  border-radius: 50%;
  background: var(--blue-soft);
  color: var(--blue);
}

.flow-grid h2 {
  margin: 2px 0 7px;
  font-size: 15px;
}

.flow-grid p {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}

.rule-section {
  margin-top: 20px;
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-1);
}

.section-heading h2 {
  margin-top: 3px;
  font-size: 20px;
}

.section-heading > strong {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.route-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 16px;
}

.route-grid article {
  padding: 15px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
}

.route-grid header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.route-grid header span {
  padding: 3px 6px;
  border-radius: 999px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 10px;
}

.route-grid dl {
  display: grid;
  gap: 8px;
  margin-top: 13px;
}

.route-grid dl div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
}

.route-grid dt {
  color: var(--muted);
}

.route-grid dd {
  overflow-wrap: anywhere;
  text-align: right;
}

.primary-action,
.secondary-action {
  min-height: 42px;
  padding: 9px 15px;
  border-radius: 7px;
  cursor: pointer;
  font-weight: 700;
}

.primary-action {
  background: var(--blue);
  color: white;
}

.secondary-action {
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text);
}

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.readonly-note,
.success-note,
.error-note {
  margin-top: 14px;
  padding: 11px 13px;
  border-radius: 7px;
  font-size: 13px;
  line-height: 1.55;
}

.readonly-note {
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--muted);
}

.unlock-panel,
.authorized-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
}

.unlock-panel > div {
  flex: 1;
}

.unlock-panel p,
.authorized-bar small {
  color: var(--muted);
  font-size: 11px;
}

.unlock-panel input {
  max-width: 340px;
}

.authorized-bar {
  justify-content: space-between;
  border-color: rgb(8 127 109 / 35%);
  background: var(--green-soft);
}

.authorized-bar > div {
  display: flex;
  align-items: center;
  gap: 8px;
}

.authorized-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
}

.success-note {
  border: 1px solid rgb(10 146 126 / 35%);
  background: var(--green-soft);
  color: var(--green);
}

.error-note,
.state-card.error {
  border: 1px solid rgb(190 45 45 / 35%);
  background: #fff5f5;
  color: var(--danger);
}

.rule-toolbar {
  display: grid;
  gap: 11px;
  margin-top: 16px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
}

.search-field {
  max-width: 620px;
}

.category-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.category-tabs button {
  padding: 6px 11px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-1);
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
}

.category-tabs button.active {
  border-color: var(--blue);
  background: var(--blue-soft);
  color: var(--blue);
  font-weight: 700;
}

.result-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--muted);
  font-size: 11px;
}

.text-action {
  background: transparent;
  color: var(--blue);
  cursor: pointer;
  font-weight: 700;
}

.empty-result {
  margin-top: 14px;
  padding: 22px;
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  color: var(--muted);
  text-align: center;
}

.safety-list {
  display: grid;
  gap: 9px;
  margin-top: 14px;
}

.safety-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
}

.safety-card.selected {
  border-color: var(--blue);
  box-shadow: 0 0 0 1px rgb(37 104 178 / 10%);
}

.safety-card summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 15px;
  cursor: pointer;
  list-style: none;
}

.select-rule {
  display: flex;
  flex: 0 0 auto;
  grid-template-columns: auto auto;
  align-items: center;
  gap: 5px;
  color: var(--blue);
  cursor: pointer;
}

.select-rule input {
  width: 17px;
  height: 17px;
}

.safety-card summary div {
  display: grid;
  gap: 3px;
}

.category-badges {
  display: flex !important;
  flex-direction: row;
  flex-wrap: wrap;
  gap: 4px !important;
}

.category-badges span {
  padding: 2px 5px;
  border-radius: 999px;
  background: var(--blue-soft);
  color: var(--blue);
  font-size: 9px;
  font-weight: 700;
}

.safety-card summary small,
.safety-card summary > span {
  color: var(--muted);
  font-size: 11px;
}

.condition-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 15px 13px;
  list-style: none;
}

.condition-tags li {
  padding: 4px 7px;
  border-radius: 999px;
  background: #fde7e7;
  color: #8f2525;
  font-size: 11px;
  font-weight: 700;
}

.implementation {
  margin: 0 15px 10px;
  padding: 11px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-1);
}

.implementation header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.implementation header span,
.implementation p {
  color: var(--muted);
  font-size: 11px;
}

.implementation p {
  margin-top: 8px;
  line-height: 1.6;
}

.edit-grid,
.save-panel {
  display: grid;
  gap: 12px;
  padding: 0 15px 14px;
}

.edit-grid {
  grid-template-columns: 1fr 1.5fr;
}

label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

input,
textarea,
select {
  width: 100%;
  padding: 9px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text);
  font: inherit;
  font-weight: 400;
  line-height: 1.5;
}

.semantic-feature-editor {
  display: grid;
  gap: 12px;
  margin-top: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-2);
}

.feature-heading {
  align-items: flex-end;
}

.feature-heading > div {
  display: grid;
  gap: 2px;
}

.feature-heading small,
.feature-toolbar > small,
.advanced-condition small {
  color: var(--muted);
  font-size: 10px;
}

.feature-heading label {
  width: min(240px, 100%);
}

.feature-toolbar {
  display: grid;
  gap: 8px;
}

.feature-toolbar > label {
  max-width: 560px;
}

.feature-tabs button {
  padding: 5px 9px;
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  max-height: 390px;
  padding: 2px;
  overflow-y: auto;
}

.feature-option {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: start;
  gap: 8px;
  padding: 9px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  cursor: pointer;
}

.feature-option.selected {
  border-color: var(--blue);
  background: var(--blue-soft);
}

.feature-option input {
  width: 17px;
  height: 17px;
  margin-top: 2px;
}

.feature-option > span {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.feature-option code {
  overflow: hidden;
  color: var(--blue);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feature-option b {
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.45;
}

.feature-option small {
  color: var(--muted);
  font-size: 9px;
}

.empty-result.compact {
  margin-top: 0;
  padding: 12px;
}

.advanced-condition {
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.json-editor {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.assistant-panel,
.editor-workspace {
  margin-top: 16px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-2);
}

.assistant-panel > header,
.editor-workspace > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.assistant-panel header > div > span,
.editor-workspace header span {
  color: var(--blue);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.assistant-panel h3,
.editor-workspace h3 {
  margin-top: 2px;
  font-size: 17px;
}

.assistant-panel header p {
  color: var(--muted);
  font-size: 11px;
}

.assistant-history {
  display: grid;
  gap: 7px;
  max-height: 260px;
  margin-top: 12px;
  overflow-y: auto;
}

.assistant-history p {
  width: fit-content;
  max-width: 85%;
  padding: 8px 10px;
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  font-size: 12px;
}

.assistant-history p.user {
  justify-self: end;
  background: var(--blue-soft);
}

.assistant-history b {
  display: block;
  color: var(--muted);
  font-size: 9px;
}

.assistant-input {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  gap: 9px;
  margin-top: 12px;
}

.selection-warning {
  margin-top: 8px;
  color: var(--warning);
  font-size: 11px;
}

.selected-editor {
  margin-top: 12px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
}

.selected-editor .implementation {
  margin: 10px 0 0;
}

.save-panel {
  margin-top: 16px;
  padding: 16px;
  border: 1px solid var(--blue);
  border-radius: 8px;
  background: var(--blue-soft);
}

.save-panel .primary-action {
  justify-self: start;
}

.save-readiness {
  display: grid;
  gap: 7px;
  padding: 11px 12px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--muted);
  font-size: 12px;
}

.save-readiness ul {
  display: grid;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.save-readiness li {
  display: flex;
  gap: 7px;
  align-items: center;
}

.save-readiness li.complete {
  color: var(--green);
}

.save-readiness p {
  margin: 2px 0 0;
  color: var(--danger);
  font-weight: 700;
}

.state-card {
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-1);
}

@media (max-width: 900px) {
  .flow-grid {
    grid-template-columns: 1fr 1fr;
  }

  .route-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 620px) {
  .save-success-toast {
    right: 12px;
    left: 12px;
    width: auto;
  }

  .rule-center {
    padding: 16px 12px;
  }

  .rule-section {
    padding: 12px;
  }

  .page-heading,
  .section-heading {
    display: grid;
  }

  .flow-grid,
  .edit-grid {
    grid-template-columns: 1fr;
  }

  .unlock-panel,
  .authorized-bar,
  .assistant-panel > header,
  .editor-workspace > header {
    align-items: stretch;
    flex-direction: column;
  }

  .unlock-panel input {
    max-width: none;
  }

  .assistant-input {
    grid-template-columns: 1fr;
  }

  .assistant-panel,
  .editor-workspace {
    padding: 10px;
  }

  .selected-editor,
  .semantic-feature-editor {
    padding: 8px;
  }

  .feature-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .feature-grid {
    grid-template-columns: 1fr;
  }
}
</style>
