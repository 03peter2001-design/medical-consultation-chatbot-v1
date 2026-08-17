const OPTION_PUNCTUATION = /[\s，,。.!！?？；;：:'\"「」『』（）()]/g
const CHOICE_SEPARATOR = /(?:、|，|,|以及|和|與|佮|閣有)/

function normalizedOption(value) {
  return String(value || '').replace(OPTION_PUNCTUATION, '').toLocaleLowerCase()
}

function withoutSelectionPrefix(value) {
  return String(value || '')
    .trim()
    .replace(/^(?:我的答案是|答案是|我選擇|我選|選擇|我欲揀|我揀)\s*/, '')
}

function localizedValueMap(values, labels = {}) {
  const result = new Map()
  for (const value of values) {
    result.set(normalizedOption(value), value)
    const label = labels[value]
    if (label) result.set(normalizedOption(label), value)
  }
  return result
}

function matchChoice(spec, transcript) {
  const options = spec?.options ?? []
  const optionByNormalizedValue = localizedValueMap(
    options,
    spec?.option_labels,
  )
  const spoken = withoutSelectionPrefix(transcript)
  const wholeMatch = optionByNormalizedValue.get(normalizedOption(spoken))
  let selectedOptions = wholeMatch ? [wholeMatch] : []

  if (!wholeMatch && spec?.multiple) {
    const parts = spoken
      .split(CHOICE_SEPARATOR)
      .map((part) => normalizedOption(withoutSelectionPrefix(part)))
      .filter(Boolean)
    const matched = parts.map((part) => optionByNormalizedValue.get(part))
    if (parts.length > 1 && matched.every(Boolean)) {
      selectedOptions = [...new Set(matched)]
    }
  }

  const exclusive = new Set(spec?.exclusive_options ?? [])
  if (
    selectedOptions.length &&
    !(
      selectedOptions.length > 1 &&
      selectedOptions.some((option) => exclusive.has(option))
    )
  ) {
    return {
      status: 'mapped',
      kind: 'choice',
      selectedOptions,
      transcript,
    }
  }

  if (spec?.allow_other) {
    return {
      status: 'other',
      kind: 'choice',
      otherText: transcript.trim(),
      transcript,
    }
  }
  return { status: 'unresolved', kind: 'choice', transcript }
}

function matchDuration(spec, transcript) {
  const compact = String(transcript || '')
    .trim()
    .replace(/[\s，,。!！?？；;：:'\"「」『』（）()]/g, '')
  const quickOption = localizedValueMap(
    spec?.quick_options ?? [],
    spec?.quick_option_labels,
  ).get(normalizedOption(compact))
  if (quickOption) {
    return {
      status: 'mapped',
      kind: 'duration',
      quickOption,
      transcript,
    }
  }

  const unitMatch = [...(spec?.units ?? [])]
    .flatMap((canonical) => [
      [canonical, canonical],
      [spec?.unit_labels?.[canonical], canonical],
    ])
    .filter(([label]) => label)
    .sort(([left], [right]) => right.length - left.length)
    .find(([label]) => compact.endsWith(label))
  const number = unitMatch ? compact.slice(0, -unitMatch[0].length) : ''
  const unit = unitMatch?.[1]
  if (unit && /^\d+(?:\.\d+)?$/.test(number) && Number(number) > 0) {
    return {
      status: 'mapped',
      kind: 'duration',
      durationNumber: number,
      durationUnit: unit,
      transcript,
    }
  }

  if (spec?.allow_other) {
    return {
      status: 'other',
      kind: 'duration',
      otherText: transcript.trim(),
      transcript,
    }
  }
  return { status: 'unresolved', kind: 'duration', transcript }
}

function normalizedVoiceDate(transcript, maxDate) {
  const raw = String(transcript || '').trim()
  const match = raw.match(
    /^(民國)?\s*(\d{2,4})\s*(?:年|[/.\-])\s*(\d{1,2})\s*(?:月|[/.\-])\s*(\d{1,2})\s*日?[。.]?$/,
  )
  if (!match) return ''

  const year = Number(match[2]) + (match[1] ? 1911 : 0)
  const month = Number(match[3])
  const day = Number(match[4])
  const date = new Date(Date.UTC(year, month - 1, day))
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return ''
  }
  const isoDate = [
    String(year).padStart(4, '0'),
    String(month).padStart(2, '0'),
    String(day).padStart(2, '0'),
  ].join('-')
  if (maxDate && isoDate > maxDate) return ''
  if (maxDate) {
    const [todayYear, todayMonth, todayDay] = maxDate.split('-').map(Number)
    const age =
      todayYear -
      year -
      (todayMonth < month || (todayMonth === month && todayDay < day) ? 1 : 0)
    if (age > 130) return ''
  }
  return isoDate
}

export function interpretQuestionnaireVoice(
  spec,
  transcript,
  { maxDate = '' } = {},
) {
  const spoken = String(transcript || '').trim()
  if (!spoken) {
    return {
      status: 'unresolved',
      kind: spec?.kind ?? 'unknown',
      transcript: '',
    }
  }
  if (spec?.kind === 'choice') return matchChoice(spec, spoken)
  if (spec?.kind === 'duration') return matchDuration(spec, spoken)
  if (spec?.kind === 'date') {
    const dateValue = normalizedVoiceDate(spoken, maxDate)
    return dateValue
      ? {
          status: 'mapped',
          kind: 'date',
          dateValue,
          transcript: spoken,
        }
      : { status: 'unresolved', kind: 'date', transcript: spoken }
  }
  return {
    status: 'unresolved',
    kind: spec?.kind ?? 'unknown',
    transcript: spoken,
  }
}
