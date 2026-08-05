const runtimeLocation =
  typeof window === 'undefined'
    ? { search: '', protocol: 'http:', hostname: '127.0.0.1' }
    : window.location

export function resolveBackendUrl(
  locationLike = runtimeLocation,
  configuredBaseUrl = import.meta.env?.VITE_BACKEND_BASE_URL,
) {
  const params = new URLSearchParams(locationLike.search || '')
  const override = params.get('backend')?.trim()

  if (override) {
    const candidate = /^https?:\/\//i.test(override)
      ? override
      : `http://${override}`
    try {
      const url = new URL(candidate)
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        return url.toString().replace(/\/+$/, '')
      }
    } catch {
      console.warn('忽略無效的 backend 網址參數：', override)
    }
  }

  const configured = configuredBaseUrl?.trim()
  if (configured?.startsWith('/')) {
    return configured.replace(/\/+$/, '') || '/'
  }
  if (configured) {
    try {
      const url = new URL(configured)
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        return url.toString().replace(/\/+$/, '')
      }
    } catch {
      console.warn('忽略無效的 VITE_BACKEND_BASE_URL：', configured)
    }
  }

  const requestedPort = params.get('backendPort')?.trim()
  const backendPort =
    /^\d{1,5}$/.test(requestedPort || '') && Number(requestedPort) <= 65535
      ? requestedPort
      : import.meta.env?.VITE_BACKEND_PORT || '8000'
  const protocol = locationLike.protocol === 'https:' ? 'https:' : 'http:'
  const hostname = locationLike.hostname || '127.0.0.1'
  return `${protocol}//${hostname}:${backendPort}`
}

export const backendUrl = resolveBackendUrl()
export const apiVersionPrefix = '/v1'

function apiPath(path) {
  return `${apiVersionPrefix}${path}`
}

export function consultationListPath({
  search = '',
  limit = 30,
  offset = 0,
} = {}) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  const normalizedSearch = search.trim()
  if (normalizedSearch) params.set('search', normalizedSearch)
  return apiPath(`/doctor/consultations?${params.toString()}`)
}

export function consultationDetailPath(consultationId) {
  return apiPath(
    `/doctor/consultations/${encodeURIComponent(consultationId)}`,
  )
}

export function consultationLookupFields(value) {
  const reference = String(value ?? '').trim()
  if (/^(?:\d{3}|\d{5})$/.test(reference)) {
    return { registration_number: reference }
  }
  return { consultation_id: reference }
}

export const ruleCenterPath = apiPath('/doctor/rules')
export const ruleAuthorizationPath = apiPath('/doctor/rules/authorize')
export const ruleAssistantPath = apiPath('/doctor/rules/assistant')
export const safetyRuleUpdatePath = apiPath('/doctor/rules/safety')
export const factLabelUpdatePath = apiPath('/doctor/rules/fact-labels')

export function diseaseProfileUpdatePath(route) {
  return apiPath(
    `/doctor/rules/disease-profiles/${encodeURIComponent(route)}`,
  )
}

export function snomedSearchPath({
  query,
  limit = 20,
  offset = 0,
}) {
  const params = new URLSearchParams({
    query: String(query || '').trim(),
    limit: String(limit),
    offset: String(offset),
  })
  return apiPath(`/doctor/terminology/snomed?${params.toString()}`)
}

async function request(path, options = {}) {
  const response = await fetch(`${backendUrl}${path}`, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(formatApiErrorDetail(data.detail, response.status))
  }
  return data
}

export function formatApiErrorDetail(detail, status) {
  if (typeof detail === 'string' && detail.trim()) {
    if (status === 409 && detail.includes('跨日期重複')) {
      return '此掛號編號在不同日期有多筆病例，請輸入「YYYY-MM-DD:編號」指定日期。'
    }
    return detail
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue) => {
        if (!issue || typeof issue !== 'object') return ''
        const location = Array.isArray(issue.loc)
          ? issue.loc.filter((part) => part !== 'body').join('.')
          : ''
        const message = issue.msg || ''
        return [location, message].filter(Boolean).join('：')
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }
  return `HTTP ${status}`
}

function jsonOptions(method, body) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export const api = {
  health: () => request(apiPath('/health')),
  listConsultations: (options) =>
    request(consultationListPath(options)),
  deleteConsultation: (consultationId) =>
    request(consultationDetailPath(consultationId), {
      method: 'DELETE',
    }),
  patientChat: (
    message,
    sessionId,
    painLocationIds = [],
    patientPrefill = null,
  ) =>
    request(
      apiPath('/chat'),
      jsonOptions('POST', {
        message,
        session_id: sessionId,
        pain_location_ids: painLocationIds,
        patient_prefill: patientPrefill,
      }),
    ),
  transcribe: (audioBlob) => {
    const formData = new FormData()
    formData.append('audio', audioBlob, 'audio.webm')
    return request(apiPath('/transcribe'), {
      method: 'POST',
      body: formData,
    })
  },
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
    request(
      apiPath('/doctor/chat'),
      jsonOptions('POST', {
        message,
        session_id: sessionId,
        mode,
      }),
    ),
  clearDoctorSession: (sessionId) =>
    request(apiPath(`/doctor/session/${encodeURIComponent(sessionId)}`), {
      method: 'DELETE',
    }),
  searchSnomed: (options) => request(snomedSearchPath(options)),
  loadRuleCenter: () => request(ruleCenterPath),
  authorizeRuleEditor: (adminToken) =>
    request(ruleAuthorizationPath, {
      method: 'POST',
      headers: { 'X-Rule-Admin-Token': adminToken },
    }),
  suggestRuleEdits: (payload, adminToken) =>
    request(ruleAssistantPath, {
      ...jsonOptions('POST', payload),
      headers: {
        'Content-Type': 'application/json',
        'X-Rule-Admin-Token': adminToken,
      },
    }),
  updateSafetyRules: (payload, adminToken) =>
    request(safetyRuleUpdatePath, {
      ...jsonOptions('PUT', payload),
      headers: {
        'Content-Type': 'application/json',
        'X-Rule-Admin-Token': adminToken,
      },
    }),
  updateFactLabels: (payload, adminToken) =>
    request(factLabelUpdatePath, {
      ...jsonOptions('PUT', payload),
      headers: {
        'Content-Type': 'application/json',
        'X-Rule-Admin-Token': adminToken,
      },
    }),
  updateDiseaseProfile: (route, payload, adminToken) =>
    request(diseaseProfileUpdatePath(route), {
      ...jsonOptions('PUT', payload),
      headers: {
        'Content-Type': 'application/json',
        'X-Rule-Admin-Token': adminToken,
      },
    }),
}

export function connectionError(error) {
  return `無法連接後端（${error.message}）。\n嘗試連線：${backendUrl}\n請確認 FastAPI 的 host 與 port 設定。`
}
