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

  return {
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
}

export function codingSystemLabel(system) {
  if (system === SNOMED_CT_SYSTEM) return 'SNOMED CT'
  if (system === LOINC_SYSTEM) return 'LOINC'
  return 'CODE'
}

export function codingKey(coding) {
  return `${coding?.system || ''}|${coding?.code || ''}|${coding?.field || ''}`
}

export function resolveConditionCoding(condition, explicitCoding = null) {
  return normalizeCoding(explicitCoding, {
    display: condition,
  })
}

function supportedCodings(concept, fallback = {}) {
  return (concept?.coding || [])
    .map((coding) =>
      normalizeCoding(coding, {
        ...fallback,
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
