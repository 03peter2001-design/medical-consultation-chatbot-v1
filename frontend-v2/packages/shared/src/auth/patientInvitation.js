export function readInvitationToken(hash = window.location.hash) {
  const value = String(hash || '').replace(/^#/, '')
  if (!value) return ''
  if (!value.includes('=') && !value.includes('?') && !value.includes('/')) {
    return decodeURIComponent(value)
  }
  const query = value.includes('?') ? value.slice(value.indexOf('?') + 1) : value
  const params = new URLSearchParams(query)
  return params.get('token')?.trim() || params.get('invite')?.trim() || ''
}

export function clearInvitationToken(locationLike = window.location, historyLike = window.history) {
  historyLike.replaceState(null, '', `${locationLike.pathname}${locationLike.search}`)
}
