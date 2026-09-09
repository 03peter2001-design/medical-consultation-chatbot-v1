const OPAQUE_INVITATION_CODE = /^[A-Za-z0-9_-]{32,512}$/

export function normalizeInvitationCode(value) {
  return String(value || '').trim()
}

export function isInvitationCodeFormat(value) {
  return OPAQUE_INVITATION_CODE.test(normalizeInvitationCode(value))
}

export function isPatientSessionPayload(value) {
  return Boolean(
    value &&
      typeof value === 'object' &&
      value.status === 'active' &&
      typeof value.expires_at === 'string' &&
      value.expires_at.trim() &&
      typeof value.interview_session_id === 'string' &&
      value.interview_session_id.trim(),
  )
}

function codeFromFragment(fragment) {
  const value = String(fragment || '').replace(/^#/, '')
  if (!value) return ''

  if (!value.includes('=') && !value.includes('?') && !value.includes('/')) {
    try {
      const decoded = decodeURIComponent(value)
      return isInvitationCodeFormat(decoded)
        ? normalizeInvitationCode(decoded)
        : ''
    } catch {
      return ''
    }
  }

  const query = value.includes('?') ? value.slice(value.indexOf('?') + 1) : value
  const params = new URLSearchParams(query)
  const candidate =
    params.get('token') || params.get('code') || params.get('invite') || ''
  return isInvitationCodeFormat(candidate)
    ? normalizeInvitationCode(candidate)
    : ''
}

export function readInvitationToken(hash = window.location.hash) {
  return codeFromFragment(hash)
}

export function invitationCodeFromScan(value) {
  const scanned = normalizeInvitationCode(value)
  if (isInvitationCodeFormat(scanned)) return scanned

  try {
    const url = new URL(scanned)
    if (!['http:', 'https:'].includes(url.protocol)) return ''
    const candidate =
      codeFromFragment(url.hash) ||
      [
        url.searchParams.get('token'),
        url.searchParams.get('code'),
        url.searchParams.get('invite'),
      ].find(isInvitationCodeFormat) ||
      ''
    return normalizeInvitationCode(candidate)
  } catch {
    return ''
  }
}

export function cameraAccessErrorMessage(error, secureContext = true) {
  if (!secureContext) {
    return '相機掃描需要可信任的 HTTPS 網址；請改用 HTTPS 開啟本頁，或貼上 code。'
  }
  const errorName = String(error?.name || '')
  if (errorName === 'NotAllowedError' || errorName === 'SecurityError') {
    return '相機權限被拒絕或站台政策禁止使用相機；請允許相機權限後重試，或貼上 code。'
  }
  if (errorName === 'NotFoundError' || errorName === 'OverconstrainedError') {
    return '找不到可用的相機；請確認裝置相機可用，或貼上 code。'
  }
  if (errorName === 'NotReadableError' || errorName === 'AbortError') {
    return '相機目前被其他程式占用；請關閉其他相機程式後重試，或貼上 code。'
  }
  return '暫時無法啟用相機掃描；請重新開啟掃描器，或貼上 code。'
}

export function clearInvitationToken(locationLike = window.location, historyLike = window.history) {
  const params = new URLSearchParams(locationLike.search || '')
  for (const key of ['token', 'code', 'invite']) params.delete(key)
  const query = params.toString()
  historyLike.replaceState(
    historyLike.state ?? null,
    '',
    `${locationLike.pathname}${query ? `?${query}` : ''}`,
  )
}
