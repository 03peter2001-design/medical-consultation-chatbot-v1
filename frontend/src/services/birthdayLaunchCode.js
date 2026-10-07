// bqr1 fixes the KDF and cipher parameters; changing them requires a new version.
// Birthdays have low entropy: this supplements the server's short-lived, one-use
// invitation and must not be treated as a strong authentication factor.
const VERSION = 'bqr1'
const ITERATIONS = 600_000
const MAX_ENVELOPE_LENGTH = 1024
const RAW_CODE = /^[A-Za-z0-9_-]{32,512}$/
const BASE64URL = /^[A-Za-z0-9_-]+$/
const INVALID_ENVELOPE = 'QR code 格式無效，請重新掃描或取得新的 code。'

export function normalizeBirthday(value) {
  const input = typeof value === 'string' ? value.trim() : ''
  if (!/^(?:\d{8}|\d{4}-\d{2}-\d{2})$/.test(input)) {
    throw new Error('請輸入完整西元生日，格式為 YYYYMMDD。')
  }
  const normalized = input.replaceAll('-', '')
  const year = Number(normalized.slice(0, 4))
  const month = Number(normalized.slice(4, 6))
  const day = Number(normalized.slice(6, 8))
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const daysInMonth = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  const today = new Date()
  const todayValue = today.getFullYear() * 10000 + (today.getMonth() + 1) * 100 + today.getDate()
  if (
    year < 1 || month < 1 || month > 12 || day < 1 ||
    day > daysInMonth[month - 1] || Number(normalized) > todayValue
  ) {
    throw new Error('請輸入有效且不晚於今天的完整西元生日。')
  }
  return normalized
}

export function assertBirthdayCryptoAvailable() {
  const crypto = globalThis.crypto
  if (
    globalThis.isSecureContext === false ||
    typeof crypto?.getRandomValues !== 'function' ||
    !['importKey', 'deriveKey', 'encrypt', 'decrypt'].every(
      (method) => typeof crypto?.subtle?.[method] === 'function',
    )
  ) {
    throw new Error('此環境無法安全處理生日加密 QR code，請使用可信任的 HTTPS 網址與支援的瀏覽器。')
  }
}

function encode(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

function decode(value) {
  if (!BASE64URL.test(value)) throw new Error(INVALID_ENVELOPE)
  const padded = value.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - value.length % 4) % 4)
  const bytes = Uint8Array.from(atob(padded), (char) => char.charCodeAt(0))
  // Reject alternate encodings with unused nonzero bits or explicit padding.
  if (encode(bytes) !== value) throw new Error(INVALID_ENVELOPE)
  return bytes
}

function parseEnvelope(value) {
  if (typeof value !== 'string' || value.length > MAX_ENVELOPE_LENGTH) {
    throw new Error(INVALID_ENVELOPE)
  }
  const parts = value.split('.')
  if (parts.length !== 4 || parts[0] !== VERSION) throw new Error(INVALID_ENVELOPE)
  try {
    const [salt, iv, ciphertext] = parts.slice(1).map(decode)
    // AES-GCM appends a 16-byte authentication tag to a 32–512-byte ASCII code.
    if (salt.length !== 16 || iv.length !== 12 || ciphertext.length < 48 || ciphertext.length > 528) {
      throw new Error(INVALID_ENVELOPE)
    }
    return { salt, iv, ciphertext }
  } catch {
    throw new Error(INVALID_ENVELOPE)
  }
}

export function isBirthdayLaunchCode(value) {
  try {
    parseEnvelope(value)
    return true
  } catch {
    return false
  }
}

async function deriveKey(birthday, salt, usage) {
  const material = await globalThis.crypto.subtle.importKey(
    'raw', new TextEncoder().encode(birthday), 'PBKDF2', false, ['deriveKey'],
  )
  return globalThis.crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt, iterations: ITERATIONS, hash: 'SHA-256' },
    material, { name: 'AES-GCM', length: 256 }, false, [usage],
  )
}

function cipherParameters(iv) {
  return { name: 'AES-GCM', iv, additionalData: new TextEncoder().encode(VERSION), tagLength: 128 }
}

export async function encryptBirthdayLaunchCode(rawCode, birthDate) {
  assertBirthdayCryptoAvailable()
  const birthday = normalizeBirthday(birthDate)
  if (typeof rawCode !== 'string' || !RAW_CODE.test(rawCode)) throw new Error(INVALID_ENVELOPE)
  try {
    const salt = globalThis.crypto.getRandomValues(new Uint8Array(16))
    const iv = globalThis.crypto.getRandomValues(new Uint8Array(12))
    const key = await deriveKey(birthday, salt, 'encrypt')
    const encrypted = await globalThis.crypto.subtle.encrypt(
      cipherParameters(iv), key, new TextEncoder().encode(rawCode),
    )
    return [VERSION, encode(salt), encode(iv), encode(new Uint8Array(encrypted))].join('.')
  } catch {
    throw new Error('無法產生生日加密 QR code，請重試。')
  }
}

export async function decryptBirthdayLaunchCode(envelope, birthDate) {
  assertBirthdayCryptoAvailable()
  const birthday = normalizeBirthday(birthDate)
  const { salt, iv, ciphertext } = parseEnvelope(envelope)
  try {
    const key = await deriveKey(birthday, salt, 'decrypt')
    const decrypted = await globalThis.crypto.subtle.decrypt(cipherParameters(iv), key, ciphertext)
    const rawCode = new TextDecoder('utf-8', { fatal: true }).decode(decrypted)
    if (!RAW_CODE.test(rawCode)) throw new Error(INVALID_ENVELOPE)
    return rawCode
  } catch {
    throw new Error('生日不正確或 QR code 已損壞，請確認生日或重新取得 code。')
  }
}
