const runtimeLocation =
  typeof window === 'undefined'
    ? { search: '', protocol: 'http:', hostname: '127.0.0.1' }
    : window.location

export function resolveBackendUrl(locationLike = runtimeLocation) {
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

async function request(path, options = {}) {
  const response = await fetch(`${backendUrl}${path}`, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status}`)
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

export const api = {
  health: () => request('/health'),
  patientChat: (
    message,
    sessionId,
    painLocationIds = [],
    patientPrefill = null,
  ) =>
    request(
      '/chat',
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
    return request('/transcribe', { method: 'POST', body: formData })
  },
  loadPatient: (queueNumber, sessionId) =>
    request(
      '/doctor/load_patient',
      jsonOptions('POST', {
        session_id: sessionId,
        queue_number: queueNumber,
      }),
    ),
  unloadPatient: (sessionId) =>
    request(`/doctor/patient/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    }),
  doctorChat: (message, sessionId, mode) =>
    request(
      '/doctor/chat',
      jsonOptions('POST', {
        message,
        session_id: sessionId,
        mode,
      }),
    ),
  clearDoctorSession: (sessionId) =>
    request(`/doctor/session/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    }),
}

export function connectionError(error) {
  return `無法連接後端（${error.message}）。\n嘗試連線：${backendUrl}\n請確認 FastAPI 的 host 與 port 設定。`
}
