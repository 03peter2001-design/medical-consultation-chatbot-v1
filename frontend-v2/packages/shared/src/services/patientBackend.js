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
  chat: (message, sessionId, painLocationIds = []) =>
    request(
      apiPath('/chat'),
      jsonOptions({
        message,
        session_id: sessionId,
        pain_location_ids: painLocationIds,
      }),
    ),
  back: (sessionId) =>
    request(
      apiPath('/chat'),
      jsonOptions({
        message: '',
        session_id: sessionId,
        action: 'back',
      }),
    ),
  transcribe: (audioBlob) => {
    const formData = new FormData()
    formData.append('audio', audioBlob, 'audio.webm')
    return request(apiPath('/transcribe'), { method: 'POST', body: formData })
  },
}

export const api = {
  patientChat: patientApi.chat,
  patientBack: patientApi.back,
  transcribe: patientApi.transcribe,
}

export function connectionError(error) {
  return `無法連線至問診服務：${error.message}\nAPI：${backendUrl}`
}
