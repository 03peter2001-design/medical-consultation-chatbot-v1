import { computed, onScopeDispose, ref, watch } from 'vue'

import { api } from '../services/backend.js'
import {
  getRuleSaveChecks,
  getRuleSaveValidationError,
} from '../services/ruleEditor.js'

export const SAFETY_ROUTE_LABELS = {
  chest: '胸痛',
  headache: '頭痛',
  abdomen: '腹痛',
}

export const SAFETY_CATEGORY_OPTIONS = [
  { id: 'all', label: '全部群組' },
  { id: 'universal', label: '共通' },
  { id: 'chest', label: '胸痛' },
  { id: 'headache', label: '頭痛' },
  { id: 'abdomen', label: '腹痛' },
  { id: 'structured', label: '結構化' },
]

export const SAFETY_FEATURE_CATEGORY_OPTIONS = [
  { id: 'all', label: '全部特徵' },
  { id: 'safety', label: '直接停止' },
  { id: 'chest', label: '胸痛' },
  { id: 'headache', label: '頭痛' },
  { id: 'abdomen', label: '腹痛' },
  { id: 'common', label: '共通' },
]

export function nonemptySafetyLines(value) {
  return String(value || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function selectedSafetyFeatures(rule) {
  return rule.featureSelections?.[rule.featureMode] || []
}

export function hiddenSafetyFeatures(rule, visibleCodes) {
  const visible = visibleCodes instanceof Set ? visibleCodes : new Set(visibleCodes)
  return selectedSafetyFeatures(rule).filter((code) => !visible.has(code))
}

export function cloneSafetyGroups(groups) {
  return JSON.parse(JSON.stringify(groups || [])).map((group) => ({
    ...group,
    categories: group.categories || [],
    conditionsText: group.possible_conditions.join('\n'),
    rules: group.rules.map((rule) => {
      const when = rule.when || {}
      const featureMode = Object.hasOwn(when, 'all_findings')
        ? 'all_findings'
        : 'any_findings'
      const otherConditions = Object.fromEntries(
        Object.entries(when).filter(
          ([key]) => key !== 'any_findings' && key !== 'all_findings',
        ),
      )
      return {
        ...rule,
        termsText: (rule.terms || []).join('\n'),
        featureMode,
        featureSelections: {
          all_findings: [...(when.all_findings || [])],
          any_findings: [...(when.any_findings || [])],
        },
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

export function buildSafetyRule(rule) {
  const result = {
    code: rule.code,
    kind: rule.kind,
    scope: rule.scope,
    route: rule.route,
    level: rule.level,
  }
  if (rule.kind === 'phrase') {
    result.terms = nonemptySafetyLines(rule.termsText)
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
    for (const mode of ['all_findings', 'any_findings']) {
      const selected = rule.featureSelections?.[mode] || []
      if (selected.length) parsed[mode] = [...new Set(selected)]
    }
    result.when = parsed
  } else {
    result.all_term_groups = parsed
  }
  return result
}

export function buildSafetyGroup(group) {
  return {
    original_label: group.original_label,
    label: group.label.trim(),
    possible_conditions: nonemptySafetyLines(group.conditionsText),
    categories: group.categories,
    rules: group.rules.map(buildSafetyRule),
  }
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

export function getChangedSafetyGroups(drafts, deployedGroups) {
  const originals = new Map(
    (deployedGroups || []).map((group) => [group.original_label, group]),
  )
  return (drafts || []).filter((group) => {
    try {
      return (
        JSON.stringify(buildSafetyGroup(group)) !==
        JSON.stringify(originalComparable(originals.get(group.original_label)))
      )
    } catch {
      return true
    }
  })
}

export function buildSafetyPublishPayload({
  groups,
  sessionId,
  expectedRevision,
  confirmation,
  changeNote,
}) {
  return {
    session_id: sessionId,
    expected_revision: expectedRevision,
    confirmation: confirmation.trim(),
    change_note: changeNote.trim(),
    safety_groups: groups.map(buildSafetyGroup),
  }
}

export function useSafetyRuleGovernance(props, emit) {
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
  let assistantRequestSequence = 0
  let assistantAbortController = null

  function invalidateAssistantRequest() {
    assistantRequestSequence += 1
    assistantAbortController?.abort()
    assistantAbortController = null
    assistantBusy.value = false
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
        drafts.value = cloneSafetyGroups(rulebook.safety_groups)
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
      SAFETY_CATEGORY_OPTIONS.map((category) => [
        category.id,
        category.id === 'all'
          ? drafts.value.length
          : drafts.value.filter((group) =>
              group.categories.includes(category.id),
            ).length,
      ]),
    ),
  )

  const changedGroups = computed(() =>
    getChangedSafetyGroups(drafts.value, props.rulebook.safety_groups),
  )

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

  function buildPayloadGroups() {
    return drafts.value.map(buildSafetyGroup)
  }

  function selectGroup(groupId) {
    invalidateAssistantRequest()
    activeGroupId.value = groupId
    featureSearch.value = ''
    activeFeatureCategory.value = 'all'
    assistantHistory.value = []
    assistantMessage.value = ''
    error.value = ''
  }

  function resetDraftState() {
    changeNote.value = ''
    confirmation.value = ''
    validationError.value = ''
    assistantHistory.value = []
    assistantMessage.value = ''
    error.value = ''
  }

  function beginEdit() {
    if (!props.authorized || !activeGroup.value) return
    drafts.value = cloneSafetyGroups(props.rulebook.safety_groups)
    ensureActiveGroup()
    editing.value = true
    resetDraftState()
    success.value = ''
  }

  function cancelEdit() {
    invalidateAssistantRequest()
    drafts.value = cloneSafetyGroups(props.rulebook.safety_groups)
    editing.value = false
    resetDraftState()
    ensureActiveGroup()
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
    const requestId = ++assistantRequestSequence
    const requestedGroupId = activeGroup.value.original_label
    const controller = new AbortController()
    assistantAbortController = controller
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
        controller.signal,
      )
      if (
        requestId !== assistantRequestSequence ||
        !editing.value ||
        activeGroupId.value !== requestedGroupId
      ) {
        return
      }
      drafts.value = cloneSafetyGroups(result.safety_groups)
      assistantHistory.value.push({
        role: 'assistant',
        content: `${result.reply}（僅套用至草稿，尚未儲存）`,
      })
    } catch (requestError) {
      if (requestId === assistantRequestSequence) {
        assistantHistory.value.pop()
        if (requestError.name !== 'AbortError') error.value = requestError.message
      }
    } finally {
      if (requestId === assistantRequestSequence) {
        assistantAbortController = null
        assistantBusy.value = false
      }
    }
  }

  onScopeDispose(invalidateAssistantRequest)

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
        buildSafetyPublishPayload({
          groups: drafts.value,
          sessionId: props.sessionId,
          expectedRevision: props.rulebook.revision,
          confirmation: confirmation.value,
          changeNote: changeNote.value,
        }),
        props.adminToken,
      )
      drafts.value = cloneSafetyGroups(updated.safety_groups)
      editing.value = false
      resetDraftState()
      success.value = 'Safety 規則已建立稽核快照並發布。'
      emit('saved', updated)
    } catch (requestError) {
      error.value = requestError.message
    } finally {
      saving.value = false
    }
  }

  return {
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
    drafts,
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
  }
}
