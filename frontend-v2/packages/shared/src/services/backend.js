const runtimeLocation =
  typeof window === 'undefined'
    ? { protocol: 'http:', hostname: '127.0.0.1' }
    : window.location

export function resolveBackendUrl(
  _locationLike = runtimeLocation,
  configuredBaseUrl = import.meta.env?.VITE_BACKEND_BASE_URL,
) {
  const configured = configuredBaseUrl?.trim()
  if (configured?.startsWith('/')) {
    return configured.replace(/\/+$/, '') || '/'
  }
  if (configured) {
    const url = new URL(configured)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      throw new Error('API URL 必須使用 HTTP 或 HTTPS')
    }
    return url.toString().replace(/\/+$/, '')
  }
  return '/ai-api'
}

export const backendUrl = resolveBackendUrl()
export const apiVersionPrefix = '/v1'

let authProvider = null

export function setAuthProvider(provider) {
  authProvider = provider || null
}

function apiPath(path) {
  return `${apiVersionPrefix}${path}`
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return response.json().catch(() => ({}))
  }
  const text = await response.text()
  return text ? { detail: text } : {}
}

async function request(path, options = {}, retry = true) {
  const headers = new Headers(options.headers || {})
  const token = await authProvider?.getToken?.()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(`${backendUrl}${path}`, {
    ...options,
    headers,
    credentials: 'include',
    // Doctor responses may contain patient data or a transient authentication
    // failure. Neither is safe to reuse from a browser or intermediary cache.
    cache: 'no-store',
  })

  if (response.status === 401 && retry && authProvider?.refresh) {
    await authProvider.refresh()
    return request(path, options, false)
  }

  const data = await parseResponse(response)
  if (!response.ok) {
    const error = new Error(formatApiErrorDetail(data.detail, response.status))
    error.status = response.status
    throw error
  }
  return data
}

function jsonOptions(method, body) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export function consultationListPath({ search = '', limit = 30, offset = 0 } = {}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  const normalizedSearch = search.trim()
  if (normalizedSearch) params.set('search', normalizedSearch)
  return apiPath(`/doctor/consultations?${params.toString()}`)
}

export function consultationDetailPath(consultationId) {
  return apiPath(`/doctor/consultations/${encodeURIComponent(consultationId)}`)
}

export function fhirCompositionPath(consultationId) {
  return apiPath(
    `/doctor/consultations/${encodeURIComponent(consultationId)}/fhir-composition`,
  )
}

export function consultationLookupFields(value) {
  const reference = String(value ?? '').trim()
  if (/^(?:\d{3}|\d{5})$/.test(reference)) return { registration_number: reference }
  return { consultation_id: reference }
}

export const ruleCenterPath = apiPath('/doctor/rules')
export const ruleAuthorizationPath = apiPath('/doctor/rules/authorize')
export const ruleAssistantPath = apiPath('/doctor/rules/assistant')
export const safetyRuleUpdatePath = apiPath('/doctor/rules/safety')
export const factLabelUpdatePath = apiPath('/doctor/rules/fact-labels')

export function diseaseProfileUpdatePath(route) {
  return apiPath(`/doctor/rules/disease-profiles/${encodeURIComponent(route)}`)
}

export function formatApiErrorDetail(detail, status) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue) => {
        if (!issue || typeof issue !== 'object') return ''
        const location = Array.isArray(issue.loc)
          ? issue.loc.filter((part) => part !== 'body').join('.')
          : ''
        return [location, issue.msg || ''].filter(Boolean).join('：')
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }
  return `HTTP ${status}`
}

export const api = {
  health: () => request(apiPath('/health')),
  listConsultations: (options) => request(consultationListPath(options)),
  deleteConsultation: (consultationId) =>
    request(consultationDetailPath(consultationId), { method: 'DELETE' }),
  createFhirComposition: (consultationId, payload) =>
    request(
      fhirCompositionPath(consultationId),
      jsonOptions('POST', payload),
    ),
  loadPatient: (consultationId, sessionId) =>
    request(
      apiPath('/doctor/load_patient'),
      jsonOptions('POST', {
        session_id: sessionId,
        ...consultationLookupFields(consultationId),
      }),
    ),
  unloadPatient: (sessionId) =>
    request(apiPath(`/doctor/patient/${encodeURIComponent(sessionId)}`), {
      method: 'DELETE',
    }),
  doctorChat: (message, sessionId, mode) =>
    request(apiPath('/doctor/chat'), jsonOptions('POST', { message, session_id: sessionId, mode })),
  clearDoctorSession: (sessionId) =>
    request(apiPath(`/doctor/session/${encodeURIComponent(sessionId)}`), {
      method: 'DELETE',
    }),
  loadRuleCenter: () => request(ruleCenterPath),
  authorizeRuleEditor: () => request(ruleAuthorizationPath, { method: 'POST' }),
  suggestRuleEdits: (payload) => request(ruleAssistantPath, jsonOptions('POST', payload)),
  updateSafetyRules: (payload) => request(safetyRuleUpdatePath, jsonOptions('PUT', payload)),
  updateFactLabels: (payload) => request(factLabelUpdatePath, jsonOptions('PUT', payload)),
  updateDiseaseProfile: (route, payload) =>
    request(diseaseProfileUpdatePath(route), jsonOptions('PUT', payload)),
}

export function connectionError(error) {
  return `無法連線至後端：${error.message}\nAPI：${backendUrl}`
}
