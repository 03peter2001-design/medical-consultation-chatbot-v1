// UI-only mappings between the versioned questionnaire options and the body
// map. Coarse options produce visual highlights, never inferred precise IDs.
const HEADACHE_OPTIONS = [
  '單側',
  '兩側都痛',
  '前額',
  '後腦勺及頸部',
  '整個頭',
]

const HEADACHE_FOREHEAD_IDS = [
  'front_forehead_right',
  'front_forehead_left',
]
const HEADACHE_POSTERIOR_IDS = [
  'back_occipital_right',
  'back_occipital_center',
  'back_occipital_left',
  'back_neck_right',
  'back_neck_center',
  'back_neck_left',
]
const HEADACHE_WHOLE_HEAD_IDS = [
  'front_vertex',
  'front_forehead_right',
  'front_forehead_left',
  'front_temple_right',
  'front_temple_left',
  'front_orbit_right',
  'front_orbit_left',
  'back_vertex',
  'back_occipital_right',
  'back_occipital_center',
  'back_occipital_left',
]

const CHEST_OPTION_REGIONS = {
  '左邊': ['front_chest_left', 'back_upper_left'],
  '右邊': ['front_chest_right', 'back_upper_right'],
  '正中間': ['front_chest_center', 'back_spine_upper'],
  '兩側都有': [
    'front_chest_right',
    'front_chest_left',
    'back_upper_right',
    'back_upper_left',
  ],
}

const ABDOMEN_OPTION_REGIONS = {
  '右上腹': ['front_upper_abdomen_right'],
  '左上腹': ['front_upper_abdomen_left'],
  '右下腹': ['front_lower_abdomen_right'],
  '左下腹': ['front_lower_abdomen_left'],
  '全腹痛': [
    'front_upper_abdomen_right',
    'front_upper_abdomen_center',
    'front_upper_abdomen_left',
    'front_lower_abdomen_right',
    'front_lower_abdomen_center',
    'front_lower_abdomen_left',
  ],
  '左側腰痛': ['back_flank_left'],
  '右側腰痛': ['back_flank_right'],
  '肚臍以下腹痛': [
    'front_lower_abdomen_right',
    'front_lower_abdomen_center',
    'front_lower_abdomen_left',
  ],
}

const SUPPORTED_ROUTES = new Set(['headache', 'chest', 'abdomen'])

function orderedSelections(options, selected) {
  return options.filter((option) => selected.has(option))
}

function hasAny(selectedIds, regionIds) {
  return regionIds.some((id) => selectedIds.has(id))
}

function mappedHighlights(options, mapping) {
  const highlights = new Set()
  for (const option of options) {
    for (const regionId of mapping[option] || []) highlights.add(regionId)
  }
  return [...highlights]
}

export function supportsPainLocationSync(route = '') {
  return SUPPORTED_ROUTES.has(route)
}

export function questionOptionsFromPainRegions(route, regionIds = []) {
  const selectedIds = new Set(regionIds)
  if (!selectedIds.size || !supportsPainLocationSync(route)) return []

  if (route === 'headache') {
    const selected = new Set()
    const hasRight = [...selectedIds].some((id) => id.endsWith('_right'))
    const hasLeft = [...selectedIds].some((id) => id.endsWith('_left'))
    if (hasRight && hasLeft) selected.add('兩側都痛')
    else if (hasRight || hasLeft) selected.add('單側')

    if (hasAny(selectedIds, HEADACHE_FOREHEAD_IDS)) selected.add('前額')
    if (hasAny(selectedIds, HEADACHE_POSTERIOR_IDS)) {
      selected.add('後腦勺及頸部')
    }
    if (HEADACHE_WHOLE_HEAD_IDS.every((id) => selectedIds.has(id))) {
      selected.clear()
      selected.add('整個頭')
    }
    return orderedSelections(HEADACHE_OPTIONS, selected)
  }

  if (route === 'chest') {
    const hasLeft = hasAny(selectedIds, CHEST_OPTION_REGIONS['左邊'])
    const hasRight = hasAny(selectedIds, CHEST_OPTION_REGIONS['右邊'])
    const selected = new Set()
    if (hasLeft && hasRight) selected.add('兩側都有')
    else if (hasLeft) selected.add('左邊')
    else if (hasRight) selected.add('右邊')
    if (hasAny(selectedIds, CHEST_OPTION_REGIONS['正中間'])) {
      selected.add('正中間')
    }
    return orderedSelections(Object.keys(CHEST_OPTION_REGIONS), selected)
  }

  const selected = new Set()
  const wholeAbdomen = ABDOMEN_OPTION_REGIONS['全腹痛']
  if (wholeAbdomen.every((id) => selectedIds.has(id))) {
    selected.add('全腹痛')
  } else {
    for (const option of [
      '右上腹',
      '左上腹',
      '右下腹',
      '左下腹',
      '左側腰痛',
      '右側腰痛',
    ]) {
      if (hasAny(selectedIds, ABDOMEN_OPTION_REGIONS[option])) {
        selected.add(option)
      }
    }
    if (selectedIds.has('front_lower_abdomen_center')) {
      selected.add('肚臍以下腹痛')
    }
  }
  return orderedSelections(Object.keys(ABDOMEN_OPTION_REGIONS), selected)
}

export function highlightedPainRegionsFromQuestionOptions(
  route,
  options = [],
) {
  if (!supportsPainLocationSync(route)) return []
  if (route === 'headache') {
    const highlights = new Set()
    if (options.includes('整個頭')) {
      return [...HEADACHE_WHOLE_HEAD_IDS]
    }
    if (options.includes('前額')) {
      for (const id of HEADACHE_FOREHEAD_IDS) highlights.add(id)
    }
    if (options.includes('後腦勺及頸部')) {
      for (const id of HEADACHE_POSTERIOR_IDS) highlights.add(id)
    }
    return [...highlights]
  }
  return mappedHighlights(
    options,
    route === 'chest' ? CHEST_OPTION_REGIONS : ABDOMEN_OPTION_REGIONS,
  )
}
