const configured = import.meta.env?.VITE_BACKEND_BASE_URL?.trim()
export const backendUrl = configured?.startsWith('/')
  ? configured.replace(/\/+$/, '') || '/'
  : configured || '/api'

function apiPath(path) {
  return `/v1${path}`
}

async function request(path, options = {}) {
  const response = await fetch(`${backendUrl}${path}`, {
    ...options,
    credentials: 'include',
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(data.detail || data.message || `HTTP ${response.status}`)
    error.status = response.status
    throw error
  }
  return data
}

async function requestVideo(path, options = {}) {
  const response = await fetch(`${backendUrl}${path}`, {
    ...options,
    credentials: 'include',
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const error = new Error(data.detail || data.message || `HTTP ${response.status}`)
    error.status = response.status
    throw error
  }
  return {
    blob: await response.blob(),
    speechModel: response.headers.get('X-Speech-Model') || '',
    animationModel: response.headers.get('X-Animation-Model') || '',
    cacheHit: response.headers.get('X-Avatar-Cache') === 'hit',
  }
}

function jsonOptions(body) {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export const patientApi = {
  session: () => request(apiPath('/patient/session')),
  exchangeInvitation: (token) =>
    request(apiPath('/invitations/exchange'), jsonOptions({ token })),
  chat: (
    message,
    sessionId,
    painLocationIds = [],
    patientPrefill = null,
    language = 'mandarin',
    fhirContext = null,
  ) =>
    request(
      apiPath('/chat'),
      jsonOptions({
        message,
        session_id: sessionId,
        pain_location_ids: painLocationIds,
        patient_prefill: patientPrefill,
        fhir_context: fhirContext,
        language,
      }),
    ),
  back: (sessionId, language = 'mandarin') =>
    request(
      apiPath('/chat'),
      jsonOptions({
        message: '',
        session_id: sessionId,
        action: 'back',
        language,
      }),
    ),
  transcribe: (audioBlob) => {
    const formData = new FormData()
    formData.append('audio', audioBlob, 'audio.webm')
    return request(apiPath('/transcribe'), { method: 'POST', body: formData })
  },
  avatarStatus: () => request(apiPath('/avatar/status')),
  avatarWarmup: () => request(apiPath('/avatar/warmup'), jsonOptions({})),
  speakAvatar: (text, options = {}) =>
    requestVideo(apiPath('/avatar/speak'), {
      ...jsonOptions({ text, language: options.language || 'mandarin' }),
      signal: options.signal,
    }),
}

export const api = {
  patientChat: patientApi.chat,
  patientBack: patientApi.back,
  transcribe: patientApi.transcribe,
  avatarStatus: patientApi.avatarStatus,
  avatarWarmup: patientApi.avatarWarmup,
  speakAvatar: patientApi.speakAvatar,
}

export function connectionError(error) {
  return `無法連線至問診服務：${error.message}\nAPI：${backendUrl}`
}
