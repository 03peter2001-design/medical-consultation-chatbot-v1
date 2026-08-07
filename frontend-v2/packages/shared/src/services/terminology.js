export const SNOMED_CT_SYSTEM = 'http://snomed.info/sct'
export const LOINC_SYSTEM = 'http://loinc.org'

const SUPPORTED_SYSTEMS = new Set([
  SNOMED_CT_SYSTEM,
  LOINC_SYSTEM,
])

export function normalizeCoding(coding, fallback = {}) {
  if (!coding || typeof coding !== 'object') return null
  const system = String(coding.system || fallback.system || '').trim()
  const code = String(coding.code || '').trim()
  if (!SUPPORTED_SYSTEMS.has(system) || !code) return null

  const normalized = {
    field: String(coding.field || fallback.field || '').trim(),
    system,
    code,
    display: String(
      coding.display || fallback.display || '',
    ).trim(),
    source: String(
      coding.source || fallback.source || 'fhir',
    ).trim(),
  }
  const text = String(coding.text || fallback.text || '').trim()
  if (text) normalized.text = text
  return normalized
}

export function codingSystemLabel(system) {
  if (system === SNOMED_CT_SYSTEM) return 'SNOMED CT'
  if (system === LOINC_SYSTEM) return 'LOINC'
  return 'CODE'
}

export function codingKey(coding) {
  return `${coding?.system || ''}|${coding?.code || ''}|${coding?.field || ''}`
}

function comparableText(value) {
  return String(value || '')
    .normalize('NFKC')
    .toLocaleLowerCase()
    .replace(/[\s()[\]（）{}「」『』【】"'。，,；;：:、/\\_-]+/g, '')
}

function fieldSegments(value) {
  return String(value || '')
    .split(/[、，,；;。\n/]+/)
    .map(comparableText)
    .filter(Boolean)
}

function uniqueCodingMatches(matches) {
  const byCode = new Map()
  for (const match of matches) {
    const key = `${match.coding.system}|${match.coding.code}`
    const existing = byCode.get(key)
    if (!existing || match.score > existing.score) {
      byCode.set(key, match)
    }
  }
  const ranked = [...byCode.values()].sort((a, b) => b.score - a.score)
  if (!ranked.length || ranked[0].score === ranked[1]?.score) return null
  return ranked[0].coding
}

export function resolveConditionCoding(
  condition,
  explicitCoding = null,
  sourceCodings = [],
  patientData = {},
) {
  const explicit = normalizeCoding(explicitCoding, {
    display: condition,
  })
  if (explicit) return explicit

  const target = comparableText(condition)
  if (!target) return null

  const matches = (sourceCodings || [])
    .map((coding) => normalizeCoding(coding))
    .filter(Boolean)
    .map((coding) => {
      const codingText = comparableText(coding.text)
      const display = comparableText(coding.display)
      const fieldValue = comparableText(patientData?.[coding.field])
      const segments = fieldSegments(patientData?.[coding.field])
      let score = 0

      if (codingText === target) score = 100
      else if (display === target) score = 90
      else if (fieldValue === target) score = 60
      else if (segments.includes(target)) score = 50
      else if (
        segments.some(
          (segment) =>
            segment.length >= 2 &&
            (segment.includes(target) || target.includes(segment)),
        )
      ) {
        score = 40
      }

      return { coding, score }
    })
    .filter((match) => match.score > 0)

  return uniqueCodingMatches(matches)
}

export function resolveConditionCodings(
  condition,
  explicitCoding = null,
  sourceCodings = [],
  patientData = {},
) {
  const explicit = (
    Array.isArray(explicitCoding) ? explicitCoding : [explicitCoding]
  )
    .map((coding) =>
      normalizeCoding(coding, {
        display: condition,
        source: 'snomed-registry',
      }),
    )
    .filter(Boolean)

  if (explicit.length) return uniqueCodings(explicit)

  const resolved = resolveConditionCoding(
    condition,
    null,
    sourceCodings,
    patientData,
  )
  return resolved ? [resolved] : []
}

function supportedCodings(concept, fallback = {}) {
  return (concept?.coding || [])
    .map((coding) =>
      normalizeCoding(coding, {
        ...fallback,
        text: concept?.text || fallback.text || '',
        display:
          coding.display ||
          concept?.text ||
          fallback.display ||
          '',
      }),
    )
    .filter(Boolean)
}

function uniqueCodings(codings) {
  const seen = new Set()
  return codings.filter((coding) => {
    const key = codingKey(coding)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function buildFhirClinicalCodings(
  resources = [],
  {
    includeCondition = () => true,
    conditionFields = () => ['chronic'],
    includeProcedure = () => true,
  } = {},
) {
  const codings = []

  for (const resource of resources) {
    if (resource?.resourceType === 'Observation') {
      const observationCodings = supportedCodings(resource.code)
      const bloodTypeObservation = observationCodings.some((coding) =>
        ['882-1', '883-9'].includes(coding.code),
      )
      if (bloodTypeObservation) {
        codings.push(
          ...observationCodings.map((coding) => ({
            ...coding,
            field: 'blood_type',
          })),
        )
      }
    }

    if (
      resource?.resourceType === 'Condition' &&
      includeCondition(resource)
    ) {
      const conditionCodings = supportedCodings(resource.code)
      for (const field of conditionFields(resource)) {
        codings.push(
          ...conditionCodings.map((coding) => ({
            ...coding,
            field,
          })),
        )
      }
    }

    if (
      resource?.resourceType === 'Procedure' &&
      resource.status === 'completed' &&
      includeProcedure(resource)
    ) {
      codings.push(
        ...supportedCodings(resource.code, { field: 'surgery' }),
      )
    }

    if (resource?.resourceType === 'AllergyIntolerance') {
      codings.push(
        ...supportedCodings(resource.code, { field: 'allergy' }),
      )
    }
  }

  return uniqueCodings(codings)
}
