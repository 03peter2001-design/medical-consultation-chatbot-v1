const EMR_HEADING = '【病歷摘要 EMR】'

const SECTION_DEFINITIONS = [
  {
    key: 'emr',
    title: '病歷摘要 EMR',
    question: '這次就診的病歷重點是什麼？',
    tone: 'emr',
    matches: (heading) => heading.includes('病歷摘要') && heading.includes('EMR'),
  },
  {
    key: 'differential',
    title: '初步鑑別診斷',
    question: '最可能的前三項診斷是什麼？',
    tone: 'differential',
    matches: (heading) => heading.includes('初步鑑別診斷'),
  },
  {
    key: 'must-not-miss',
    title: '防漏診鑑別',
    question: '哪些致命疾病絕對不能漏掉？',
    tone: 'danger',
    matches: (heading) => heading.includes('防漏診鑑別'),
  },
  {
    key: 'physical',
    title: '理學檢查',
    question: '要做哪些重點理學檢查？',
    tone: 'physical',
    matches: (heading) => heading.includes('理學檢查'),
  },
  {
    key: 'laboratory',
    title: '檢驗（抽血／驗尿）',
    question: '最小且有鑑別力的檢驗有哪些？',
    tone: 'laboratory',
    matches: (heading) => heading.includes('檢驗') && heading.includes('抽血'),
  },
  {
    key: 'imaging',
    title: '影像學決策',
    question: '需要哪些影像，以及 CT／MRI 是否必要？',
    tone: 'imaging',
    matches: (heading) => heading.includes('影像學決策'),
  },
]

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

function sectionDefinition(heading) {
  return SECTION_DEFINITIONS.find((definition) =>
    definition.matches(heading),
  )
}

export function parseStructuredNoteBlocks(text) {
  const source = String(text || '').trim()
  if (!source) {
    return { sections: [], footer: '', fallbackText: '' }
  }

  const footerIndex = source.search(/(?:^|\n)模型：/)
  const body = (footerIndex < 0 ? source : source.slice(0, footerIndex)).trim()
  const footer = (footerIndex < 0 ? '' : source.slice(footerIndex)).trim()
  const headings = [...body.matchAll(/【([^】]+)】/g)]

  if (!headings.length) {
    return { sections: [], footer, fallbackText: body }
  }

  const fallbackText = body.slice(0, headings[0].index).trim()
  const sections = headings
    .map((match, index) => {
      const heading = match[1].trim()
      const definition = sectionDefinition(heading)
      const contentStart = Number(match.index) + match[0].length
      const contentEnd =
        index + 1 < headings.length
          ? Number(headings[index + 1].index)
          : body.length
      const content = body.slice(contentStart, contentEnd).trim()

      return {
        key: definition?.key || `section-${index + 1}`,
        title: definition?.title || heading,
        question: definition?.question || '其他需要注意的臨床資訊是什麼？',
        tone: definition?.tone || 'neutral',
        content,
      }
    })
    .filter((section) => section.content)

  return { sections, footer, fallbackText }
}
