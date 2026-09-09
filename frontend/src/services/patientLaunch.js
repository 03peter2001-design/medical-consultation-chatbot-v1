const OPAQUE_LAUNCH_CODE = /^[A-Za-z0-9_-]{32,512}$/

export function normalizeLaunchCode(value) {
  return String(value || '').trim()
}

export function isLaunchCodeFormat(value) {
  return OPAQUE_LAUNCH_CODE.test(normalizeLaunchCode(value))
}

export function launchCodeFromScan(value) {
  const scanned = normalizeLaunchCode(value)
  if (isLaunchCodeFormat(scanned)) return scanned

  try {
    const url = new URL(scanned)
    if (!['http:', 'https:'].includes(url.protocol)) return ''
    const hash = url.hash.replace(/^#\/?\??/, '')
    const hashParams = new URLSearchParams(hash)
    const candidate =
      hashParams.get('token') ||
      hashParams.get('code') ||
      url.searchParams.get('token') ||
      url.searchParams.get('code') ||
      ''
    return isLaunchCodeFormat(candidate)
      ? normalizeLaunchCode(candidate)
      : ''
  } catch {
    return ''
  }
}

export function launchSecondsRemaining(expiresAt, now = Date.now()) {
  const expiry = Date.parse(expiresAt || '')
  if (!Number.isFinite(expiry)) return 0
  return Math.max(0, Math.ceil((expiry - now) / 1000))
}

export function launchCountdownLabel(seconds) {
  const bounded = Math.max(0, Math.floor(Number(seconds) || 0))
  const minutes = Math.floor(bounded / 60)
  const remainder = String(bounded % 60).padStart(2, '0')
  return `${minutes}:${remainder}`
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
