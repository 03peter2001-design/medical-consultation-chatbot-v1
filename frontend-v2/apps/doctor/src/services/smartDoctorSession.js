import {
  ensureSmartClientLibrary,
  markSmartLaunchPending,
  sanitizeSmartCallbackUrl,
} from '@medical/shared/services/smart.js'

function tokenResponse(client) {
  return client?.state?.tokenResponse || client?.getState?.('tokenResponse') || {}
}

function resourceId(value, resourceType) {
  const normalized = String(value || '').trim()
  if (!normalized) return ''
  const prefix = `${resourceType}/`
  return normalized.startsWith(prefix)
    ? normalized.slice(prefix.length)
    : normalized
}

function explicitUccFhirContext(uccContext) {
  return {
    patientId: resourceId(
      uccContext?.fhir_patient_id ||
        uccContext?.fhirPatientId ||
        uccContext?.patient?.fhir_patient_id ||
        uccContext?.patient?.fhirPatientId ||
        uccContext?.patient?.fhir_reference ||
        uccContext?.patient?.fhirReference,
      'Patient',
    ),
    encounterId: resourceId(
      uccContext?.fhir_encounter_id ||
        uccContext?.fhirEncounterId ||
        uccContext?.encounter?.fhir_encounter_id ||
        uccContext?.encounter?.fhirEncounterId ||
        uccContext?.encounter?.fhir_reference ||
        uccContext?.encounter?.fhirReference,
      'Encounter',
    ),
  }
}

export function verifySmartUccContext(client, uccContext) {
  const token = tokenResponse(client)
  const patientId = resourceId(client?.patient?.id || token.patient, 'Patient')
  const encounterId = resourceId(
    client?.encounter?.id || token.encounter,
    'Encounter',
  )
  if (!patientId) {
    throw new Error(
      'SMART Launch Context 沒有 patient id，請回到 UCC 重新選擇病人。',
    )
  }

  const expected = explicitUccFhirContext(uccContext)
  if (expected.patientId && expected.patientId !== patientId) {
    throw new Error('SMART Patient 與 UCC 病人 context 不一致，已停止載入。')
  }
  if (expected.encounterId && expected.encounterId !== encounterId) {
    throw new Error('SMART Encounter 與 UCC 就診 context 不一致，已停止載入。')
  }

  return {
    patientId,
    encounterId,
    fhirUser: String(token.fhirUser || '').trim(),
    bindingVerified: Boolean(expected.patientId && expected.encounterId),
  }
}

export async function completeDoctorSmartAuthorization({
  fhirLibrary,
  globalLike = typeof window === 'undefined' ? null : window,
  documentLike = globalLike?.document,
  storageLike = globalLike?.sessionStorage,
  locationLike = globalLike?.location,
  historyLike = globalLike?.history,
  uccContext,
} = {}) {
  try {
    const FHIR =
      fhirLibrary ||
      (await ensureSmartClientLibrary({ globalLike, documentLike }))
    const client = await FHIR.oauth2.ready()
    const context = verifySmartUccContext(client, uccContext)
    markSmartLaunchPending(storageLike, false)
    sanitizeSmartCallbackUrl(locationLike, historyLike)
    return context
  } catch (error) {
    markSmartLaunchPending(storageLike, false)
    sanitizeSmartCallbackUrl(locationLike, historyLike)
    throw error
  }
}
