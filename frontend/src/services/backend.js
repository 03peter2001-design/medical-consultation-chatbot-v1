const runtimeLocation =
  typeof window === 'undefined'
    ? { search: '', protocol: 'http:', hostname: '127.0.0.1' }
    : window.location

function parseBoolean(value, fallback = false) {
  if (value == null || value === '') return fallback
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase())
}

function allowedOrigins(value) {
  return new Set(
    String(value || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
      .flatMap((item) => {
        try {
          return [new URL(item).origin]
        } catch {
          return []
        }
      }),
  )
}

function allowedQueryUrl(requested, allowlist) {
  if (!requested) return ''
  const candidate = /^https?:\/\//i.test(requested)
    ? requested
    : `http://${requested}`
  try {
    const url = new URL(candidate)
    if (
      ['http:', 'https:'].includes(url.protocol) &&
      allowedOrigins(allowlist).has(url.origin)
    ) {
      return url.toString().replace(/\/+$/, '')
    }
  } catch {
    // Invalid or untrusted query overrides fall through to configured defaults.
  }
  return ''
}

export function resolveBackendUrl(
  locationLike = runtimeLocation,
  configuredBaseUrl = import.meta.env?.VITE_BACKEND_BASE_URL,
  {
    developmentMode = import.meta.env?.DEV === true,
    queryOverrideEnabled = import.meta.env
      ?.VITE_ENABLE_BACKEND_QUERY_OVERRIDE,
    queryOverrideOrigins = import.meta.env
      ?.VITE_BACKEND_QUERY_OVERRIDE_ORIGINS,
  } = {},
) {
  const params = new URLSearchParams(locationLike.search || '')
  const queryOverridesAllowed =
    developmentMode && parseBoolean(queryOverrideEnabled)

  if (queryOverridesAllowed) {
    const override = allowedQueryUrl(
      params.get('backend')?.trim(),
      queryOverrideOrigins,
    )
    if (override) return override
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

  const protocol = locationLike.protocol === 'https:' ? 'https:' : 'http:'
  const hostname = locationLike.hostname || '127.0.0.1'
  const requestedPort = queryOverridesAllowed
    ? params.get('backendPort')?.trim()
    : ''
  if (
    /^\d{1,5}$/.test(requestedPort || '') &&
    Number(requestedPort) <= 65535
  ) {
    const override = allowedQueryUrl(
      `${protocol}//${hostname}:${requestedPort}`,
      queryOverrideOrigins,
    )
    if (override) return override
  }
  const backendPort = import.meta.env?.VITE_BACKEND_PORT || '18000'
  return `${protocol}//${hostname}:${backendPort}`
}

export const backendUrl = resolveBackendUrl()
export const apiVersionPrefix = '/v1'

export function credentialsForBackendUrl(
  baseUrl,
  locationLike = runtimeLocation,
) {
  const pageOrigin =
    locationLike.origin ||
    `${locationLike.protocol === 'https:' ? 'https:' : 'http:'}//${
      locationLike.hostname || '127.0.0.1'
    }${locationLike.port ? `:${locationLike.port}` : ''}`
  try {
    return new URL(baseUrl, pageOrigin).origin === new URL(pageOrigin).origin
      ? 'include'
      : 'omit'
  } catch {
    return 'omit'
  }
}

const backendCredentials = credentialsForBackendUrl(backendUrl)

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
  const response = await fetch(`${backendUrl}${path}`, {
    ...options,
    credentials: backendCredentials,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(formatApiErrorDetail(data.detail, response.status))
  }
  return data
}

async function requestVideo(path, options = {}) {
  const response = await fetch(`${backendUrl}${path}`, {
    ...options,
    credentials: backendCredentials,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(formatApiErrorDetail(data.detail, response.status))
  }
  return {
    blob: await response.blob(),
    speechModel: response.headers.get('X-Speech-Model') || '',
    animationModel: response.headers.get('X-Animation-Model') || '',
    cacheHit: response.headers.get('X-Avatar-Cache') === 'hit',
  }
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

export function audioUploadFilename(mimeType = '') {
  const normalized = mimeType.split(';', 1)[0].toLowerCase()
  const extension = {
    'audio/mp4': 'm4a',
    'audio/mpeg': 'mp3',
    'audio/ogg': 'ogg',
    'audio/wav': 'wav',
    'audio/x-wav': 'wav',
  }[normalized] || 'webm'
  return `audio.${extension}`
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
  patientBack: (sessionId) =>
    request(
      apiPath('/chat'),
      jsonOptions('POST', {
        message: '',
        session_id: sessionId,
        action: 'back',
      }),
    ),
  transcribe: (audioBlob) => {
    const formData = new FormData()
    formData.append(
      'audio',
      audioBlob,
      audioUploadFilename(audioBlob.type),
    )
    return request(apiPath('/transcribe'), {
      method: 'POST',
      body: formData,
    })
  },
  avatarStatus: () => request(apiPath('/avatar/status')),
  avatarWarmup: () =>
    request(apiPath('/avatar/warmup'), jsonOptions('POST', {})),
  speakAvatar: (text, options = {}) =>
    requestVideo(
      apiPath('/avatar/speak'),
      {
        ...jsonOptions('POST', {
          text,
          language: options.language || 'mandarin',
        }),
        signal: options.signal,
      },
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
  suggestRuleEdits: (payload, adminToken, signal) =>
    request(ruleAssistantPath, {
      ...jsonOptions('POST', payload),
      signal,
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
