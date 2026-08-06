const EMR_HEADING = '【病歷摘要 EMR】'

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
