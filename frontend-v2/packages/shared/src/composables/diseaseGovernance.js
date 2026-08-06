import { computed, ref, watch } from 'vue'

import { api } from '../services/backend.js'

export const DISEASE_ROUTE_LABELS = {
  chest: '胸痛',
  headache: '頭痛',
  abdomen: '腹痛',
}

export const DISEASE_CATEGORY_OPTIONS = [
  { id: 'all', label: '全部標籤' },
  { id: 'selected', label: '已加入' },
  { id: 'safety', label: 'Safety：直接停止' },
  { id: 'chest', label: '胸痛' },
  { id: 'headache', label: '頭痛' },
  { id: 'abdomen', label: '腹痛' },
  { id: 'common', label: '共通' },
]

export function cloneDiseaseRoutes(rulebook) {
  return JSON.parse(JSON.stringify(rulebook?.routes || []))
}

export function safetyGroupCodes(group) {
  return group.rules.map((rule) => rule.code)
}

export function hasSafetyGroup(profile, group) {
  const selected = new Set(profile?.safety_rule_codes || [])
  return safetyGroupCodes(group).every((code) => selected.has(code))
}

function profileClueMap(profile) {
  return new Map((profile?.clues || []).map((clue) => [clue.fact, clue]))
}

export function getDiseaseChanges(draftRoute, deployedRoute, safetyGroups = []) {
  const deployedProfiles = new Map(
    (deployedRoute?.profiles || []).map((profile) => [profile.id, profile]),
  )
  const result = []
  for (const profile of draftRoute?.profiles || []) {
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
    for (const group of safetyGroups) {
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
}

export function hasInvalidWeights(route, maxClueWeight) {
  return (route?.profiles || []).some((profile) =>
    profile.clues.some(
      (clue) =>
        !Number.isInteger(Number(clue.weight)) ||
        Number(clue.weight) < 1 ||
        Number(clue.weight) > maxClueWeight,
    ),
  )
}

export function hasInvalidSafetyLinks(route) {
  return (route?.profiles || []).some((profile) =>
    profile.must_not_miss
      ? !profile.safety_rule_codes?.length
      : Boolean(profile.safety_rule_codes?.length),
  )
}

export function buildDiseaseProfiles(route) {
  return route.profiles.map((profile) => ({
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

export function buildDiseasePayload({
  route,
  sessionId,
  expectedRevision,
  confirmation,
  changeNote,
  reviewer,
}) {
  return {
    session_id: sessionId,
    expected_revision: expectedRevision,
    confirmation: confirmation.trim(),
    change_note: changeNote.trim(),
    reviewer: reviewer.trim(),
    profiles: buildDiseaseProfiles(route),
  }
}

export function actionLabel(change) {
  if (change.action === 'safety_added') return '綁定觸發'
  if (change.action === 'safety_removed') return '移除觸發'
  if (change.action === 'added') return '新增'
  if (change.action === 'removed') return '移除'
  return '調整'
}

export function changeDetail(change) {
  if (change.safetyGroup) {
    return `${change.safetyGroup.label}（${safetyGroupCodes(change.safetyGroup).length} 條固定規則）`
  }
  if (change.action === 'added') {
    return `${change.after.direction === 'support' ? '支持' : '反對'} ${change.after.weight} 票`
  }
  if (change.action === 'removed') return `原 ${change.before.weight} 票`
  return `${change.before.weight} → ${change.after.weight} 票`
}

export function useDiseaseGovernance(props, emit) {
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

  const activeDraft = computed(() =>
    drafts.value.find((item) => item.route === activeRoute.value),
  )
  const deployedRoute = computed(() =>
    props.rulebook.routes.find((item) => item.route === activeRoute.value),
  )
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

  function ensureSelectedDisease() {
    const profiles = activeDraft.value?.profiles || []
    if (!profiles.some((profile) => profile.id === activeDiseaseId.value)) {
      activeDiseaseId.value = profiles[0]?.id || ''
    }
  }

  watch(
    () => props.rulebook,
    (rulebook) => {
      if (!editing.value) {
        drafts.value = cloneDiseaseRoutes(rulebook)
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

  const visibleDiseases = computed(() => {
    const query = diseaseSearch.value.trim().toLowerCase()
    const profiles = activeDraft.value?.profiles || []
    if (!query) return profiles
    return profiles.filter((profile) =>
      `${profile.name} ${profile.id}`.toLowerCase().includes(query),
    )
  })
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
      DISEASE_CATEGORY_OPTIONS.map((category) => [
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
  const changes = computed(() =>
    getDiseaseChanges(
      activeDraft.value,
      deployedRoute.value,
      props.rulebook.safety_groups,
    ),
  )
  const invalidWeights = computed(() =>
    hasInvalidWeights(activeDraft.value, props.rulebook.max_clue_weight),
  )
  const invalidSafetyLinks = computed(() =>
    hasInvalidSafetyLinks(activeDraft.value),
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
      confirmation.value.trim() === props.rulebook.disease_confirmation_text,
  )

  function resetEditorFields() {
    reviewer.value = ''
    changeNote.value = ''
    confirmation.value = ''
    error.value = ''
  }

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
    drafts.value = cloneDiseaseRoutes(props.rulebook)
    ensureSelectedDisease()
    editing.value = true
    resetEditorFields()
    success.value = ''
  }

  function cancelEdit() {
    drafts.value = cloneDiseaseRoutes(props.rulebook)
    editing.value = false
    resetEditorFields()
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

  async function publish() {
    if (!canPublish.value || saving.value) return
    if (
      !window.confirm(
        `${DISEASE_ROUTE_LABELS[activeRoute.value]}疾病標籤、票數與 Safety 綁定更新後會立即套用至所有新問診。確定發布嗎？`,
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
        buildDiseasePayload({
          route: activeDraft.value,
          sessionId: props.sessionId,
          expectedRevision: deployedRoute.value.profile_revision,
          confirmation: confirmation.value,
          changeNote: changeNote.value,
          reviewer: reviewer.value,
        }),
        props.adminToken,
      )
      drafts.value = cloneDiseaseRoutes(updated)
      editing.value = false
      resetEditorFields()
      success.value = `${DISEASE_ROUTE_LABELS[activeRoute.value]}疾病治理規則已建立稽核快照並發布。`
      emit('saved', updated)
    } catch (requestError) {
      error.value = requestError.message
    } finally {
      saving.value = false
    }
  }

  return {
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
  }
}
