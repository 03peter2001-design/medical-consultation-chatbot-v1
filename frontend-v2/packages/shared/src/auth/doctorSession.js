import { setAuthProvider } from '../services/backend.js'

function decodeExpiry(token) {
  try {
    const payload = token.split('.')[1]
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
    return Number(JSON.parse(atob(normalized)).exp || 0) * 1000
  } catch {
    return 0
  }
}

function readRegistrationNumber(locationLike) {
  return new URLSearchParams(locationLike.search || '').get('regSno')?.trim() || ''
}

export function createDoctorSession({
  bootstrapUrl = import.meta.env?.VITE_UCC_BOOTSTRAP_URL || '/AiConsult/Bootstrap',
  fetchImpl = (...args) => fetch(...args),
  locationLike = typeof window === 'undefined' ? { search: '' } : window.location,
} = {}) {
  let token = ''
  let expiresAt = 0
  let timer = null
  let pending = null
  let context = null

  async function refresh() {
    if (pending) return pending
    pending = (async () => {
      const params = new URLSearchParams()
      const regSno = readRegistrationNumber(locationLike)
      if (regSno) params.set('regSno', regSno)
      const url = params.size ? `${bootstrapUrl}?${params}` : bootstrapUrl
      const response = await fetchImpl(url, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(data.detail || data.message || `UCC 驗證失敗（HTTP ${response.status}）`)
      }
      const nextToken = data.access_token || data.accessToken || data.token
      if (!nextToken) throw new Error('UCC Bootstrap 未回傳 access token')
      token = nextToken
      expiresAt = data.expires_at ? new Date(data.expires_at).getTime() : decodeExpiry(token)
      context = data
      if (timer) clearTimeout(timer)
      if (expiresAt) {
        const delay = Math.max(5_000, expiresAt - Date.now() - 60_000)
        timer = setTimeout(() => void refresh().catch(() => {}), delay)
      }
      return data
    })()
    try {
      return await pending
    } finally {
      pending = null
    }
  }

  async function getToken() {
    if (!token || (expiresAt && expiresAt - Date.now() < 30_000)) await refresh()
    return token
  }

  async function start() {
    setAuthProvider({ getToken, refresh })
    return refresh()
  }

  function stop() {
    if (timer) clearTimeout(timer)
    timer = null
    token = ''
    expiresAt = 0
    context = null
    pending = null
    setAuthProvider(null)
  }

  function hasScope(scope) {
    const scopes = context?.scopes || context?.scope?.split?.(' ') || []
    return scopes.includes(scope)
  }

  function canCreateInvitation() {
    const regSno = readRegistrationNumber(locationLike)
    const bootstrapRegSno = context?.encounter?.reg_sno ?? context?.encounter?.regSno
    return Boolean(
      context?.csrf_token
      && regSno
      && bootstrapRegSno != null
      && String(bootstrapRegSno) === regSno,
    )
  }

  async function createInvitation(regSno = readRegistrationNumber(locationLike)) {
    if (!regSno) throw new Error('缺少目前就診識別碼')
    if (!context?.csrf_token) await refresh()
    const requestRegSno = /^\d+$/.test(String(regSno)) ? Number(regSno) : regSno
    const response = await fetchImpl('/AiConsult/Invitations', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        RequestVerificationToken: context.csrf_token,
      },
      body: JSON.stringify({ regSno: requestRegSno }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(data.detail || data.message || `建立邀請失敗（HTTP ${response.status}）`)
    }
    return data
  }

  return {
    start,
    stop,
    refresh,
    getToken,
    hasScope,
    canCreateInvitation,
    createInvitation,
    get context() { return context },
  }
}

export const doctorSession = createDoctorSession()
