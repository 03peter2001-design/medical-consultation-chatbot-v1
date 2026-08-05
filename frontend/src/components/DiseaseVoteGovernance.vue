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

const routeLabels = {
  chest: '胸痛',
  headache: '頭痛',
  abdomen: '腹痛',
}

const categoryOptions = [
  { id: 'all', label: '全部標籤' },
  { id: 'selected', label: '已加入' },
  { id: 'safety', label: 'Safety：直接停止' },
  { id: 'chest', label: '胸痛' },
  { id: 'headache', label: '頭痛' },
  { id: 'abdomen', label: '腹痛' },
  { id: 'common', label: '共通' },
]

const activeRoute = ref('chest')
const activeDiseaseId = ref('')
const drafts = ref([])
const editing = ref(false)
const saving = ref(false)
const reviewer = ref('')
const changeNote = ref('')
const confirmation = ref('')
const diseaseSearch = ref('')
const factSearch = ref('')
const safetySearch = ref('')
const activeCategory = ref('selected')
const activeManagerTab = ref('votes')
const error = ref('')
const success = ref('')

function cloneRoutes(rulebook) {
  return JSON.parse(JSON.stringify(rulebook?.routes || []))
}

function ensureSelectedDisease() {
  const profiles =
    drafts.value.find((item) => item.route === activeRoute.value)
      ?.profiles || []
  if (!profiles.some((profile) => profile.id === activeDiseaseId.value)) {
    activeDiseaseId.value = profiles[0]?.id || ''
  }
}

watch(
  () => props.rulebook,
  (rulebook) => {
    if (!editing.value) {
      drafts.value = cloneRoutes(rulebook)
      ensureSelectedDisease()
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

watch(factSearch, (value) => {
  if (value.trim()) activeCategory.value = 'all'
})

const activeDraft = computed(() =>
  drafts.value.find((item) => item.route === activeRoute.value),
)

const deployedRoute = computed(() =>
  props.rulebook.routes.find((item) => item.route === activeRoute.value),
)

const visibleDiseases = computed(() => {
  const query = diseaseSearch.value.trim().toLowerCase()
  const profiles = activeDraft.value?.profiles || []
  if (!query) return profiles
  return profiles.filter((profile) =>
    `${profile.name} ${profile.id}`.toLowerCase().includes(query),
  )
})

const activeProfile = computed(() =>
  activeDraft.value?.profiles.find(
    (profile) => profile.id === activeDiseaseId.value,
  ),
)

const selectedClues = computed(() =>
  new Map(
    (activeProfile.value?.clues || []).map((clue) => [clue.fact, clue]),
  ),
)

function safetyGroupCodes(group) {
  return group.rules.map((rule) => rule.code)
}

function hasSafetyGroup(profile, group) {
  const selected = new Set(profile?.safety_rule_codes || [])
  return safetyGroupCodes(group).every((code) => selected.has(code))
}

const visibleSafetyGroups = computed(() => {
  const query = safetySearch.value.trim().toLowerCase()
  return (props.rulebook.safety_groups || []).filter((group) => {
    if (!group.applicable_routes?.includes(activeRoute.value)) return false
    if (!query) return true
    return [
      group.label,
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

const activeSafetyGroupCount = computed(() =>
  (props.rulebook.safety_groups || []).filter((group) =>
    hasSafetyGroup(activeProfile.value, group),
  ).length,
)

const visibleFacts = computed(() => {
  const query = factSearch.value.trim().toLowerCase()
  return (props.rulebook.fact_catalog || []).filter((fact) => {
    const selected = selectedClues.value.has(fact.code)
    const categoryMatch =
      activeCategory.value === 'all' ||
      (activeCategory.value === 'selected' && selected) ||
      fact.categories.includes(activeCategory.value)
    if (!categoryMatch) return false
    return (
      !query ||
      `${fact.code} ${fact.description} ${fact.categories.join(' ')}`
        .toLowerCase()
        .includes(query)
    )
  })
})

const categoryCounts = computed(() =>
  Object.fromEntries(
    categoryOptions.map((category) => [
      category.id,
      category.id === 'all'
        ? props.rulebook.fact_catalog.length
        : category.id === 'selected'
          ? selectedClues.value.size
          : props.rulebook.fact_catalog.filter((fact) =>
              fact.categories.includes(category.id),
            ).length,
    ]),
  ),
)

function profileClueMap(profile) {
  return new Map((profile?.clues || []).map((clue) => [clue.fact, clue]))
}

const changes = computed(() => {
  const deployedProfiles = new Map(
    (deployedRoute.value?.profiles || []).map((profile) => [
      profile.id,
      profile,
    ]),
  )
  const result = []
  for (const profile of activeDraft.value?.profiles || []) {
    const previous = profileClueMap(deployedProfiles.get(profile.id))
    const next = profileClueMap(profile)
    const facts = new Set([...previous.keys(), ...next.keys()])
    for (const fact of facts) {
      const before = previous.get(fact)
      const after = next.get(fact)
      if (!before) {
        result.push({ action: 'added', profile, fact, before, after })
      } else if (!after) {
        result.push({ action: 'removed', profile, fact, before, after })
      } else if (
        ['status', 'direction', 'weight'].some(
          (key) => String(before[key]) !== String(after[key]),
        )
      ) {
        result.push({ action: 'updated', profile, fact, before, after })
      }
    }
    const deployedProfile = deployedProfiles.get(profile.id)
    for (const group of props.rulebook.safety_groups || []) {
      const before = hasSafetyGroup(deployedProfile, group)
      const after = hasSafetyGroup(profile, group)
      if (before !== after) {
        result.push({
          action: after ? 'safety_added' : 'safety_removed',
          profile,
          safetyGroup: group,
        })
      }
    }
  }
  return result
})

const invalidWeights = computed(() =>
  (activeDraft.value?.profiles || []).some((profile) =>
    profile.clues.some(
      (clue) =>
        !Number.isInteger(Number(clue.weight)) ||
        Number(clue.weight) < 1 ||
        Number(clue.weight) > props.rulebook.max_clue_weight,
    ),
  ),
)

const invalidSafetyLinks = computed(() =>
  (activeDraft.value?.profiles || []).some((profile) =>
    profile.must_not_miss
      ? !profile.safety_rule_codes?.length
      : Boolean(profile.safety_rule_codes?.length),
  ),
)

const canPublish = computed(
  () =>
    props.authorized &&
    editing.value &&
    changes.value.length > 0 &&
    !invalidWeights.value &&
    !invalidSafetyLinks.value &&
    reviewer.value.trim().length >= 2 &&
    changeNote.value.trim().length >= 4 &&
    confirmation.value.trim() ===
      props.rulebook.disease_confirmation_text,
)

function setActiveRoute(route) {
  if (editing.value) return
  activeRoute.value = route
  activeDiseaseId.value = ''
  diseaseSearch.value = ''
  factSearch.value = ''
  safetySearch.value = ''
  activeCategory.value = 'selected'
  activeManagerTab.value = 'votes'
  ensureSelectedDisease()
  error.value = ''
  success.value = ''
}

function selectDisease(profileId) {
  activeDiseaseId.value = profileId
  factSearch.value = ''
  safetySearch.value = ''
  activeCategory.value = 'selected'
  error.value = ''
}

function beginEdit() {
  if (!props.authorized) return
  drafts.value = cloneRoutes(props.rulebook)
  ensureSelectedDisease()
  editing.value = true
  reviewer.value = ''
  changeNote.value = ''
  confirmation.value = ''
  error.value = ''
  success.value = ''
}

function cancelEdit() {
  drafts.value = cloneRoutes(props.rulebook)
  editing.value = false
  reviewer.value = ''
  changeNote.value = ''
  confirmation.value = ''
  error.value = ''
  ensureSelectedDisease()
}

function toggleFact(fact) {
  if (!editing.value || !activeProfile.value) return
  const index = activeProfile.value.clues.findIndex(
    (clue) => clue.fact === fact.code,
  )
  if (index >= 0) {
    if (activeProfile.value.clues.length === 1) {
      error.value = '每個疾病至少需要保留一個標籤。'
      return
    }
    activeProfile.value.clues.splice(index, 1)
  } else {
    activeProfile.value.clues.push({
      fact: fact.code,
      status: 'present',
      direction: 'support',
      weight: 1,
    })
  }
  error.value = ''
}

function normalizeWeight(clue) {
  const value = Number(clue.weight)
  if (!Number.isFinite(value)) return
  clue.weight = Math.min(
    props.rulebook.max_clue_weight,
    Math.max(1, Math.round(value)),
  )
}

function toggleSafetyGroup(group) {
  if (!editing.value || !activeProfile.value) return
  if (!activeProfile.value.must_not_miss) {
    error.value = '只有「不能漏診」疾病可以綁定 Safety 觸發器。'
    return
  }
  const groupCodes = safetyGroupCodes(group)
  const selected = new Set(activeProfile.value.safety_rule_codes || [])
  const removing = groupCodes.every((code) => selected.has(code))
  if (removing) {
    groupCodes.forEach((code) => selected.delete(code))
    if (!selected.size) {
      error.value = '不能漏診疾病至少需要一組 Safety 觸發器。'
      return
    }
  } else {
    groupCodes.forEach((code) => selected.add(code))
  }
  const order = new Map(
    (props.rulebook.safety_groups || [])
      .flatMap((item) => safetyGroupCodes(item))
      .map((code, index) => [code, index]),
  )
  activeProfile.value.safety_rule_codes = [...selected].sort(
    (left, right) => (order.get(left) ?? 999) - (order.get(right) ?? 999),
  )
  error.value = ''
}

function buildProfiles() {
  return activeDraft.value.profiles.map((profile) => ({
    id: profile.id,
    safety_rule_codes: [...(profile.safety_rule_codes || [])],
    clues: profile.clues.map((clue) => ({
      fact: clue.fact,
      status: clue.status,
      direction: clue.direction,
      weight: Number(clue.weight),
    })),
  }))
}

function actionLabel(change) {
  if (change.action === 'safety_added') return '綁定觸發'
  if (change.action === 'safety_removed') return '移除觸發'
  if (change.action === 'added') return '新增'
  if (change.action === 'removed') return '移除'
  return '調整'
}

function changeDetail(change) {
  if (change.safetyGroup) {
    return `${change.safetyGroup.label}（${safetyGroupCodes(change.safetyGroup).length} 條固定規則）`
  }
  if (change.action === 'added') {
    return `${change.after.direction === 'support' ? '支持' : '反對'} ${change.after.weight} 票`
  }
  if (change.action === 'removed') {
    return `原 ${change.before.weight} 票`
  }
  return `${change.before.weight} → ${change.after.weight} 票`
}

async function publish() {
  if (!canPublish.value || saving.value) return
  if (
    !window.confirm(
      `${routeLabels[activeRoute.value]}疾病標籤、票數與 Safety 綁定更新後會立即套用至所有新問診。確定發布嗎？`,
    )
  ) {
    return
  }
  saving.value = true
  error.value = ''
  success.value = ''
  try {
    const updated = await api.updateDiseaseProfile(
      activeRoute.value,
      {
        session_id: props.sessionId,
        expected_revision: deployedRoute.value.profile_revision,
        confirmation: confirmation.value.trim(),
        change_note: changeNote.value.trim(),
        reviewer: reviewer.value.trim(),
        profiles: buildProfiles(),
      },
      props.adminToken,
    )
    drafts.value = cloneRoutes(updated)
    editing.value = false
    reviewer.value = ''
    changeNote.value = ''
    confirmation.value = ''
    success.value = `${routeLabels[activeRoute.value]}疾病治理規則已建立稽核快照並發布。`
    emit('saved', updated)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    saving.value = false
  }
}
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
      <li class="complete"><b>1</b><span>選擇路由<br /><small>胸痛、頭痛、腹痛</small></span></li>
      <li :class="{ complete: activeProfile }"><b>2</b><span>選擇疾病<br /><small>一次檢視一種疾病</small></span></li>
      <li :class="{ complete: editing }"><b>3</b><span>管理規則<br /><small>票數標籤、緊急觸發</small></span></li>
      <li :class="{ complete: success }"><b>4</b><span>簽署發布<br /><small>快照與版本稽核</small></span></li>
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
        {{ routeLabels[route.route] }}
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
      <aside class="disease-picker">
        <label>
          搜尋疾病
          <input v-model="diseaseSearch" type="search" placeholder="疾病名稱或代碼" />
        </label>
        <div class="disease-options">
          <button
            v-for="profile in visibleDiseases"
            :key="profile.id"
            type="button"
            :class="{ active: activeDiseaseId === profile.id }"
            @click="selectDisease(profile.id)"
          >
            <span>
              <strong>{{ profile.name }}</strong>
              <code>{{ profile.id }}</code>
            </span>
            <small>{{ profile.clues.length }} 標籤</small>
          </button>
        </div>
        <p v-if="!visibleDiseases.length" class="empty-state">找不到疾病。</p>
      </aside>

      <section v-if="activeProfile" class="label-manager">
        <header class="selected-disease-heading">
          <div>
            <span>SELECTED DISEASE</span>
            <h3>{{ activeProfile.name }}</h3>
            <code>{{ activeProfile.id }}</code>
          </div>
          <div class="disease-badges">
            <span v-if="activeProfile.must_not_miss" class="critical">不能漏診</span>
            <span :class="{ reviewed: activeProfile.review_status === 'reviewed' }">
              {{ activeProfile.review_status === 'reviewed' ? '已審查' : '待校準' }}
            </span>
            <strong>{{ activeProfile.clues.length }} 個已加入標籤</strong>
            <strong v-if="activeProfile.must_not_miss">
              {{ activeSafetyGroupCount }} 組緊急觸發
            </strong>
          </div>
        </header>

        <div class="manager-tabs" aria-label="疾病規則類型">
          <button
            type="button"
            :class="{ active: activeManagerTab === 'votes' }"
            @click="activeManagerTab = 'votes'"
          >
            投票標籤
            <small>{{ activeProfile.clues.length }}</small>
          </button>
          <button
            type="button"
            :class="{ active: activeManagerTab === 'safety' }"
            @click="activeManagerTab = 'safety'"
          >
            Safety 緊急觸發
            <small>{{ activeSafetyGroupCount }}</small>
          </button>
        </div>

        <template v-if="activeManagerTab === 'votes'">
        <div class="fact-toolbar">
          <label>
            搜尋標籤
            <input
              v-model="factSearch"
              type="search"
              placeholder="例如：暈厥、胸悶、syncope"
            />
          </label>
          <small>顯示 {{ visibleFacts.length }} / {{ rulebook.fact_catalog.length }} 個標籤</small>
        </div>

        <div class="category-tabs" aria-label="疾病標籤分類">
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

        <div class="fact-grid">
          <article
            v-for="fact in visibleFacts"
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
                @click="toggleFact(fact)"
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
                {{ categoryOptions.find((item) => item.id === category)?.label || category }}
              </span>
            </div>

            <div
              v-if="selectedClues.has(fact.code) && editing"
              class="vote-controls"
            >
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
                    :max="rulebook.max_clue_weight"
                    step="1"
                    :disabled="!editing"
                    :aria-label="`${activeProfile.name} ${fact.code} 票數`"
                    @blur="normalizeWeight(selectedClues.get(fact.code))"
                  />
                  票
                </span>
              </label>
            </div>
            <div
              v-else-if="selectedClues.has(fact.code)"
              class="vote-summary"
            >
              <span>
                {{ selectedClues.get(fact.code).status === 'present' ? '存在' : '不存在' }}
              </span>
              <span>
                {{ selectedClues.get(fact.code).direction === 'support' ? '支持票' : '反對票' }}
              </span>
              <strong>{{ selectedClues.get(fact.code).weight }} 票</strong>
            </div>
          </article>
        </div>
        <p v-if="!visibleFacts.length" class="empty-state">找不到符合搜尋或分類的標籤。</p>
        <p class="source-note">
          新增標籤會沿用此疾病既有的來源集合；發布前仍須由審查醫師確認臨床依據。
        </p>
        </template>

        <section v-else class="safety-link-manager">
          <div v-if="!activeProfile.must_not_miss" class="governance-note">
            此疾病未標記為「不能漏診」，因此不會綁定自動 urgent 觸發器。普通標籤仍只影響疾病票數。
          </div>
          <template v-else>
            <div class="safety-link-intro">
              <div>
                <strong>緊急觸發器</strong>
                <p>命中下列核准條件時，會先於疾病投票將問診標記為 urgent。</p>
              </div>
              <label>
                搜尋觸發器
                <input
                  v-model="safetySearch"
                  type="search"
                  placeholder="例如：昏厥、呼吸困難、semantic"
                />
              </label>
            </div>

            <div class="safety-trigger-grid">
              <article
                v-for="group in visibleSafetyGroups"
                :key="group.original_label"
                :class="{ selected: hasSafetyGroup(activeProfile, group) }"
              >
                <header>
                  <button
                    type="button"
                    class="safety-toggle"
                    :disabled="!editing"
                    :aria-pressed="hasSafetyGroup(activeProfile, group)"
                    @click="toggleSafetyGroup(group)"
                  >
                    {{ hasSafetyGroup(activeProfile, group) ? '✓ 已綁定' : '+ 綁定' }}
                  </button>
                  <div>
                    <strong>{{ group.label }}</strong>
                    <small>{{ group.rules.length }} 條固定規則</small>
                  </div>
                </header>
                <div class="trigger-rule-codes">
                  <code v-for="rule in group.rules" :key="rule.code">
                    {{ rule.code }}
                  </code>
                </div>
                <p>{{ group.possible_conditions.join('、') }}</p>
              </article>
            </div>
            <p v-if="!visibleSafetyGroups.length" class="empty-state">找不到緊急觸發器。</p>
            <p class="source-note">
              Safety 綁定使用穩定 rule code，不會因疾病或顯示標籤改名而斷開。
            </p>
          </template>
        </section>
      </section>
    </div>

    <form v-if="editing" class="publish-panel" @submit.prevent="publish">
      <header>
        <div>
          <span>CLINICAL SIGN-OFF</span>
          <h3>覆核並發布 {{ routeLabels[activeRoute] }}疾病表</h3>
        </div>
        <button type="button" class="secondary-action" @click="cancelEdit">放棄草稿</button>
      </header>

      <div v-if="changes.length" class="change-preview">
        <strong>本次變更（{{ changes.length }}）</strong>
        <ul>
          <li
            v-for="change in changes"
            :key="`${change.profile.id}-${change.fact || change.safetyGroup?.original_label}-${change.action}`"
          >
            <b :class="`action-${change.action}`">{{ actionLabel(change) }}</b>
            {{ change.profile.name }}
            <template v-if="change.fact"> · <code>{{ change.fact }}</code></template>
            ：{{ changeDetail(change) }}
          </li>
        </ul>
      </div>
      <p v-else class="governance-note">尚未新增、移除或調整任何標籤。</p>

      <div class="signoff-grid">
        <label>
          審查醫師姓名
          <input v-model="reviewer" maxlength="80" placeholder="例如：王大明醫師" />
        </label>
        <label>
          變更理由與依據
          <textarea
            v-model="changeNote"
            rows="3"
            maxlength="500"
            placeholder="例如：依急診科共識調整暈厥票數與高風險觸發綁定"
          />
        </label>
        <label>
          輸入「{{ rulebook.disease_confirmation_text }}」確認
          <input v-model="confirmation" :placeholder="rulebook.disease_confirmation_text" />
        </label>
      </div>

      <div class="publish-actions">
        <p>發布後將保存前版、投票差異與 Safety 綁定變更，並產生新疾病表版本。</p>
        <button type="submit" class="primary-action" :disabled="!canPublish || saving">
          {{ saving ? '驗證與發布中…' : '簽署並發布疾病規則' }}
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
.profile-summary,
.selected-disease-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.governance-heading h2,
.selected-disease-heading h3,
.publish-panel h3 {
  margin: 4px 0 5px;
}

.governance-heading p,
.publish-actions p {
  margin: 0;
  color: var(--muted);
}

.governance-heading > div > span,
.selected-disease-heading > div > span,
.publish-panel header span {
  color: var(--green);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.primary-action,
.secondary-action,
.route-tabs button,
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

.primary-action:disabled,
.fact-toggle:disabled,
.safety-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.secondary-action,
.route-tabs button,
.category-tabs button {
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text);
}

.locked-badge,
.disease-badges span,
.fact-categories span {
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

.route-tabs button.active,
.category-tabs button.active {
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

.warning,
.critical,
.action-removed {
  color: var(--warning) !important;
}

.reviewed,
.action-added,
.action-safety_added {
  color: var(--green) !important;
}

.action-safety_removed {
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

.disease-picker {
  padding: 14px;
  border-right: 1px solid var(--border);
  background: var(--surface-2);
}

.disease-picker > label,
.fact-toolbar > label,
.safety-link-intro > label,
.signoff-grid label,
.vote-controls label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.disease-picker input,
.fact-toolbar input,
.safety-link-intro input,
.signoff-grid input,
.signoff-grid textarea,
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

.disease-options code,
.selected-disease-heading code,
.fact-card code,
.change-preview code {
  color: var(--green);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.disease-options small {
  color: var(--muted);
}

.label-manager {
  min-width: 0;
  padding: 18px;
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

.disease-badges,
.fact-categories {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.disease-badges strong {
  color: var(--green);
  font-size: 12px;
}

.fact-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
}

.fact-toolbar label {
  flex: 1;
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
  font-size: 12px;
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

.fact-card.selected .fact-toggle {
  border-color: var(--green);
  background: var(--green);
  color: #fff;
}

.fact-categories {
  margin-top: 9px;
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

.safety-link-manager {
  margin-top: 14px;
}

.safety-link-intro {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.safety-link-intro p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
}

.safety-link-intro > label {
  flex: 0 1 360px;
}

.safety-trigger-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  max-height: 520px;
  padding-right: 3px;
  overflow-y: auto;
}

.safety-trigger-grid article {
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-1);
}

.safety-trigger-grid article.selected {
  border-color: color-mix(in srgb, var(--danger) 38%, var(--border));
  background: color-mix(in srgb, #fff0f1 42%, var(--surface-1));
}

.safety-trigger-grid article > header {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}

.safety-trigger-grid article > header > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.safety-trigger-grid article small,
.safety-trigger-grid article > p {
  color: var(--muted);
  font-size: 11px;
}

.safety-trigger-grid article > p {
  margin-top: 8px;
}

.safety-toggle {
  flex: 0 0 auto;
  min-width: 70px;
  padding: 6px 7px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--muted);
  cursor: pointer;
  font-size: 11px;
}

.safety-trigger-grid article.selected .safety-toggle {
  border-color: var(--danger);
  background: var(--danger);
  color: #fff;
}

.trigger-rule-codes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 9px;
}

.trigger-rule-codes code {
  max-width: 100%;
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--blue);
  overflow-wrap: anywhere;
  font-size: 9px;
}

.publish-panel {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid color-mix(in srgb, var(--green) 45%, var(--border));
  border-radius: 12px;
  background: color-mix(in srgb, var(--green-soft) 24%, var(--surface-1));
}

.change-preview {
  margin: 14px 0;
  padding: 12px;
  border-radius: 8px;
  background: var(--surface-1);
}

.change-preview ul {
  max-height: 180px;
  margin: 8px 0 0;
  padding-left: 20px;
  overflow: auto;
}

.change-preview li b {
  display: inline-block;
  min-width: 32px;
  margin-right: 4px;
}

.signoff-grid {
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
  gap: 12px;
}

.publish-actions {
  margin-top: 15px;
}

.empty-state {
  padding: 18px;
  text-align: center;
  color: var(--muted);
}

@media (max-width: 980px) {
  .governance-workspace {
    grid-template-columns: 210px minmax(0, 1fr);
  }

  .fact-grid {
    grid-template-columns: 1fr;
  }

  .safety-trigger-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .governance-section {
    padding: 14px;
  }

  .governance-heading,
  .profile-summary,
  .publish-actions,
  .publish-panel > header,
  .selected-disease-heading,
  .fact-toolbar,
  .safety-link-intro {
    align-items: stretch;
    flex-direction: column;
  }

  .safety-link-intro > label {
    flex-basis: auto;
  }

  .governance-flow {
    grid-template-columns: 1fr 1fr;
  }

  .route-tabs,
  .signoff-grid,
  .manager-tabs {
    grid-template-columns: 1fr;
  }

  .governance-workspace {
    grid-template-columns: 1fr;
  }

  .disease-picker {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }

  .disease-options {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-height: 220px;
  }

  .vote-controls {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
