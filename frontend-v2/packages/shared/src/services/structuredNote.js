const EMR_HEADING = '【病歷摘要 EMR】'

function singleLine(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function summarySentences(value) {
  const normalized = singleLine(value)
  return (normalized.match(/[^。！？]+[。！？]?/g) || [])
    .map((part) => part.replace(/[。！？；，, ]+$/, '').slice(0, 100))
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => `${part}。`)
}

export function formatEmrSummary(record, summary) {
  const rawSummary = String(summary || '').trim()
  const normalized = singleLine(rawSummary)
  if (!normalized) return ''

  let detailSource = rawSummary
  const lines = rawSummary.split(/\r?\n/).filter((line) => line.trim())
  if (lines[0]?.includes('｜症狀：') && lines[0]?.includes('｜持續時間：')) {
    detailSource = lines.slice(1).join(' ')
  } else if (normalized.includes('發作／持續時間：')) {
    const firstBoundary = normalized.search(/[。！？]/)
    detailSource = firstBoundary >= 0 ? normalized.slice(firstBoundary + 1) : ''
  }

  const data = record?.patient_data || record?.data || {}
  const rawAge = singleLine(data.age) || '年齡未提供'
  const age =
    rawAge.endsWith('歲') || rawAge === '年齡未提供'
      ? rawAge
      : `${rawAge}歲`
  const rawGender = singleLine(data.gender)
  const gender =
    { 男: '男性', 男性: '男性', 女: '女性', 女性: '女性' }[
      rawGender
    ] || rawGender || '性別未提供'
  const symptom = singleLine(data.reason || record?.reason) || '未提供'
  const onset =
    singleLine(data.onset) ||
    singleLine([data.onset_num, data.onset_unit].filter(Boolean).join(' ')) ||
    '未提供'

  const fallbacks = [
    `過去病史：${singleLine(data.chronic) || '未提供'}；目前用藥：${
      singleLine(data.current_meds) || '未提供'
    }。`,
    `過敏史：${singleLine(data.allergy) || '未提供'}。`,
  ]
  const details = summarySentences(detailSource)
  details.push(...fallbacks.slice(details.length))

  return (
    `${age}${gender}｜症狀：${symptom.replace(/[。；，, ]+$/, '')}｜` +
    `持續時間：${onset.replace(/[。；，, ]+$/, '')}\n` +
    details.slice(0, 2).join('')
  )
}

export function splitStructuredNote(text) {
  const source = String(text || '').trim()
  const headingIndex = source.indexOf(EMR_HEADING)
  if (headingIndex < 0) {
    return {
      emrSummary: '',
      clinicalDecision: source,
    }
  }

  const beforeEmr = source.slice(0, headingIndex).trim()
  const afterHeading = source.slice(headingIndex + EMR_HEADING.length).trim()
  const nextHeadingIndex = afterHeading.search(/\n\s*【[^】]+】/)
  const emrSummary = (
    nextHeadingIndex < 0
      ? afterHeading
      : afterHeading.slice(0, nextHeadingIndex)
  ).trim()
  const afterEmr = (
    nextHeadingIndex < 0 ? '' : afterHeading.slice(nextHeadingIndex)
  ).trim()

  return {
    emrSummary,
    clinicalDecision: [beforeEmr, afterEmr].filter(Boolean).join('\n\n'),
  }
}

const EMR_FIELD_KEYS = {
  cc: 'cc',
  'chief complaint': 'cc',
  pi: 'pi',
  'present illness': 'pi',
  ph: 'ph',
  'past history': 'ph',
  meds: 'meds',
  'current medications': 'meds',
  'drug history': 'meds',
  allergy: 'allergy',
  'allergy history': 'allergy',
  'drug allergy history': 'allergy',
  'personal history': 'personal',
  'family history': 'family',
}

const EMR_FIELD_HEADING = new RegExp(
  `^(${Object.keys(EMR_FIELD_KEYS)
    .sort((left, right) => right.length - left.length)
    .join('|')})(?:（[^）]+）)?[：:]\\s*(.*)$`,
  'i',
)

export function parseEmrFields(text) {
  const source = splitStructuredNote(text).emrSummary
  if (!source) return {}

  const fields = {}
  let activeKey = ''
  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim()
    const heading = line.match(EMR_FIELD_HEADING)
    if (heading) {
      activeKey = EMR_FIELD_KEYS[heading[1].toLowerCase()] || ''
      if (activeKey && heading[2]) fields[activeKey] = heading[2]
      continue
    }
    if (!activeKey || !line) continue
    fields[activeKey] = [fields[activeKey], line]
      .filter(Boolean)
      .join('\n')
  }
  return fields
}
