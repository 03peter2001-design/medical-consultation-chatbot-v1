export function toggleQuestionOption(current, option, spec) {
  const selected = new Set(current)
  const exclusive = new Set(spec?.exclusive_options ?? [])

  if (selected.has(option)) {
    selected.delete(option)
    return [...selected]
  }

  if (!spec?.multiple) return [option]
  if (exclusive.has(option)) return [option]

  for (const value of exclusive) selected.delete(value)
  selected.add(option)
  return [...selected]
}

export function composeQuestionAnswer(
  spec,
  {
    text = '',
    selectedOptions = [],
    otherText = '',
    quickOption = '',
    durationNumber = '',
    durationUnit = '',
  } = {},
) {
  if (spec?.kind === 'choice') {
    const other = otherText.trim()
    if (other) return `其他：${other}`

    const answers = [...selectedOptions]
    return answers.join('、')
  }

  if (spec?.kind === 'duration') {
    const other = otherText.trim()
    if (other) return other
    if (quickOption) return quickOption

    const number = String(durationNumber ?? '').trim()
    const unit = durationUnit || spec.units?.[0] || ''
    return number && unit ? `${number}${unit}` : ''
  }

  return text.trim()
}

export function isQuestionAnswerReady(spec, state = {}) {
  return composeQuestionAnswer(spec, state).length > 0
}
