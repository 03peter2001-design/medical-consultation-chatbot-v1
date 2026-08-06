const SMART_PENDING_KEY = 'chest-pain-ai-doctor.smart.pending'

let libraryPromise = null
let cachedClient = null
let cachedPatientRecord = null

function runtimeWindow() {
  return typeof window === 'undefined' ? null : window
}

export function hasSmartLaunchContext(
  locationLike = runtimeWindow()?.location,
  storageLike = runtimeWindow()?.sessionStorage,
) {
  const params = new URLSearchParams(locationLike?.search || '')
  const callback =
    params.get('smart') === '1' ||
    (params.has('state') && (params.has('code') || params.has('error')))
  let pending = false
  try {
    pending = storageLike?.getItem(SMART_PENDING_KEY) === '1'
  } catch {
    // Some embedded EHR browsers disable sessionStorage.
  }
  return callback || pending
}

export function markSmartLaunchPending(
  storageLike = runtimeWindow()?.sessionStorage,
  pending = true,
) {
  try {
    if (pending) storageLike?.setItem(SMART_PENDING_KEY, '1')
    else storageLike?.removeItem(SMART_PENDING_KEY)
  } catch {
    // OAuth still works from its state query parameter without this hint.
  }
}

export function sanitizeSmartCallbackUrl(
  locationLike = runtimeWindow()?.location,
  historyLike = runtimeWindow()?.history,
) {
  if (!locationLike || typeof historyLike?.replaceState !== 'function') {
    return ''
  }
  const params = new URLSearchParams(locationLike.search || '')
  const sensitiveKeys = [
    'code',
    'error',
    'error_description',
    'error_uri',
  ]
  let changed = false
  for (const key of sensitiveKeys) {
    if (!params.has(key)) continue
    params.delete(key)
    changed = true
  }
  if (!changed) return ''

  const query = params.toString()
  const sanitized =
    `${locationLike.pathname || '/'}${query ? `?${query}` : ''}` +
    (locationLike.hash || '')
  historyLike.replaceState({}, '', sanitized)
  return sanitized
}

function hasReadyApi(candidate) {
  return typeof candidate?.oauth2?.ready === 'function'
}

export function ensureSmartClientLibrary({
  globalLike = runtimeWindow(),
  documentLike = runtimeWindow()?.document,
  scriptUrl = '/vendor/fhir-client.js',
} = {}) {
  if (hasReadyApi(globalLike?.FHIR)) {
    return Promise.resolve(globalLike.FHIR)
  }
  if (!documentLike?.createElement) {
    return Promise.reject(
      new Error('目前環境無法載入 SMART on FHIR client。'),
    )
  }
  if (libraryPromise) return libraryPromise

  libraryPromise = new Promise((resolve, reject) => {
    const existing = documentLike.querySelector?.(
      'script[data-smart-fhir-client]',
    )
    const script = existing || documentLike.createElement('script')

    const finish = () => {
      if (hasReadyApi(globalLike?.FHIR)) resolve(globalLike.FHIR)
      else reject(new Error('SMART on FHIR client 載入後未提供 OAuth API。'))
    }
    script.addEventListener('load', finish, { once: true })
    script.addEventListener(
      'error',
      () => reject(new Error(`無法載入 SMART client：${scriptUrl}`)),
      { once: true },
    )

    if (!existing) {
      script.src = scriptUrl
      script.async = true
      script.dataset.smartFhirClient = 'true'
      documentLike.head.appendChild(script)
    }
  }).catch((error) => {
    libraryPromise = null
    throw error
  })
  return libraryPromise
}

function tokenResponse(client) {
  return (
    client?.state?.tokenResponse ||
    client?.getState?.('tokenResponse') ||
    {}
  )
}

function resourcesFromBundle(bundle, patient) {
  const resources = Array.isArray(bundle)
    ? bundle.filter(Boolean)
    : (bundle?.entry || [])
        .map((entry) => entry?.resource)
        .filter(Boolean)
  if (
    patient &&
    !resources.some(
      (resource) =>
        resource.resourceType === 'Patient' &&
        resource.id === patient.id,
    )
  ) {
    resources.unshift(patient)
  }
  return resources
}

export async function readSmartPatientRecord(client) {
  const patientId = client?.patient?.id
  if (!patientId) {
    throw new Error(
      'SMART Launch Context 沒有 patient id，請回到 EHR 重新選擇病人。',
    )
  }

  const patient = await client.patient.read()
  const bundle = await client.request(
    `Patient/${encodeURIComponent(patientId)}/$everything?_count=100`,
    { flat: false, pageLimit: 10 },
  )
  const token = tokenResponse(client)
  return {
    patient,
    bundle,
    resources: resourcesFromBundle(bundle, patient),
    smart: {
      patientId,
      encounterId: client?.encounter?.id || token.encounter || '',
      fhirBaseUrl: client?.state?.serverUrl || '',
      scopes: String(token.scope || '')
        .split(/\s+/)
        .filter(Boolean),
    },
  }
}

export async function initializeSmartPatient({
  fhirLibrary,
  globalLike = runtimeWindow(),
  documentLike = runtimeWindow()?.document,
  storageLike = runtimeWindow()?.sessionStorage,
  locationLike = runtimeWindow()?.location,
  historyLike = runtimeWindow()?.history,
} = {}) {
  if (cachedPatientRecord) return cachedPatientRecord

  const FHIR =
    fhirLibrary ||
    (await ensureSmartClientLibrary({ globalLike, documentLike }))
  const client = cachedClient || (await FHIR.oauth2.ready())
  cachedClient = client
  cachedPatientRecord = await readSmartPatientRecord(client)
  markSmartLaunchPending(storageLike, false)
  sanitizeSmartCallbackUrl(locationLike, historyLike)
  return cachedPatientRecord
}

export function resetSmartClientCache() {
  cachedClient = null
  cachedPatientRecord = null
  libraryPromise = null
}
