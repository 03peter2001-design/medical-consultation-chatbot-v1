import assert from 'node:assert/strict'
import { createCipheriv, pbkdf2Sync, webcrypto } from 'node:crypto'
import test, { after } from 'node:test'

import {
  assertBirthdayCryptoAvailable,
  decryptBirthdayLaunchCode,
  encryptBirthdayLaunchCode,
  isBirthdayLaunchCode,
  normalizeBirthday,
} from '../src/services/birthdayLaunchCode.js'

const cryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
after(() => {
  if (cryptoDescriptor) Object.defineProperty(globalThis, 'crypto', cryptoDescriptor)
  else delete globalThis.crypto
})

const code = 'Synthetic_0123456789_abcdefghijklmno'
const birthday = '20000101'

test('normalizes complete Gregorian birthdays without the Date year 0–99 offset', () => {
  assert.equal(normalizeBirthday('2000-01-01'), birthday)
  assert.equal(normalizeBirthday(birthday), birthday)
  assert.equal(normalizeBirthday('2000-02-29'), '20000229')
  assert.equal(normalizeBirthday('0004-02-29'), '00040229')
  assert.equal(normalizeBirthday('0099-01-01'), '00990101')
  for (const value of [null, 20000101, '', '2000', '2000-01', '2000-1-1', '2000/01/01',
    '0000-01-01', '1900-02-29', '2025-02-29', '2000-04-31', '2000-00-01',
    '2000-13-01', '2000-01-00', '2000-01-32', '9999-12-31', '20000101-secret']) {
    assert.throws(() => normalizeBirthday(value), /生日/)
  }
})

test('round trips only with the birthday and randomizes both salt and IV', async () => {
  const first = await encryptBirthdayLaunchCode(code, '2000-01-01')
  const second = await encryptBirthdayLaunchCode(code, birthday)
  assert.equal(isBirthdayLaunchCode(first), true)
  assert.equal(await decryptBirthdayLaunchCode(first, birthday), code)
  assert.equal(await decryptBirthdayLaunchCode(second, '2000-01-01'), code)
  assert.notEqual(first, second)
  assert.notEqual(first.split('.')[1], second.split('.')[1])
  assert.notEqual(first.split('.')[2], second.split('.')[2])
  assert.ok(!first.includes(code))
  assert.ok(!first.includes(birthday))
  await assert.rejects(decryptBirthdayLaunchCode(first, '20000102'), /生日不正確或 QR code 已損壞/)
})

test('authenticates salt, IV and ciphertext instead of returning a corrupted code', async () => {
  const encrypted = await encryptBirthdayLaunchCode(code, birthday)
  for (const index of [1, 2, 3]) {
    const parts = encrypted.split('.')
    parts[index] = (parts[index][0] === 'A' ? 'B' : 'A') + parts[index].slice(1)
    await assert.rejects(decryptBirthdayLaunchCode(parts.join('.'), birthday), /生日不正確或 QR code 已損壞/)
  }
})

test('matches an independent fixed bqr1 vector and rejects authenticated invalid payloads', async () => {
  const salt = Buffer.alloc(16, 7)
  const iv = Buffer.alloc(12, 9)
  const key = pbkdf2Sync(birthday, salt, 600_000, 32, 'sha256')
  function envelopeFor(payload, version = 'bqr1') {
    const cipher = createCipheriv('aes-256-gcm', key, iv)
    cipher.setAAD(Buffer.from(version))
    const encrypted = Buffer.concat([cipher.update(payload), cipher.final(), cipher.getAuthTag()])
    return ['bqr1', salt.toString('base64url'), iv.toString('base64url'), encrypted.toString('base64url')].join('.')
  }
  assert.equal(await decryptBirthdayLaunchCode(envelopeFor(code), birthday), code)
  await assert.rejects(decryptBirthdayLaunchCode(envelopeFor(code, 'bqr2'), birthday), /已損壞/)
  await assert.rejects(decryptBirthdayLaunchCode(envelopeFor('!'.repeat(32)), birthday), /已損壞/)
  await assert.rejects(decryptBirthdayLaunchCode(envelopeFor(Buffer.alloc(32, 255)), birthday), /已損壞/)
})

test('rejects unsupported versions and malformed or oversized envelopes before decryption', async () => {
  const encrypted = await encryptBirthdayLaunchCode(code, birthday)
  const parts = encrypted.split('.')
  for (const value of [null, {}, code, '', 'bqr1', `${encrypted}.extra`,
    encrypted.replace('bqr1.', 'bqr2.'), ` ${encrypted}`, `${encrypted}\n`,
    `bqr1.${parts[1]}=.${parts[2]}.${parts[3]}`, `bqr1.A.${parts[2]}.${parts[3]}`,
    `bqr1.${parts[1]}.A.${parts[3]}`, `bqr1.${parts[1]}.${parts[2]}.AA`,
    `bqr1.${parts[1]}.${parts[2]}.${'A'.repeat(706)}`, 'bqr1.' + 'A'.repeat(1024)]) {
    assert.equal(isBirthdayLaunchCode(value), false)
    await assert.rejects(decryptBirthdayLaunchCode(value, birthday), /QR code 格式無效/)
  }
  // A 16-byte salt's last base64url character has four unused bits.
  const alternate = [...parts]
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
  const last = alternate[1].at(-1)
  alternate[1] = alternate[1].slice(0, -1) + alphabet[alphabet.indexOf(last) + 1]
  assert.equal(isBirthdayLaunchCode(alternate.join('.')), false)
})

test('enforces raw token boundaries and does not reflect unsafe input in errors', async () => {
  for (const value of [null, 123, '', 'A'.repeat(31), 'A'.repeat(513), `${code} `, `${code}.secret`]) {
    await assert.rejects(encryptBirthdayLaunchCode(value, birthday), /QR code 格式無效/)
  }
  for (const length of [32, 512]) {
    const raw = 'A'.repeat(length)
    const encrypted = await encryptBirthdayLaunchCode(raw, birthday)
    assert.ok(encrypted.length <= 1024)
    assert.equal(await decryptBirthdayLaunchCode(encrypted, birthday), raw)
  }
})

test('fails closed when Web Crypto or a secure context is unavailable', async () => {
  Object.defineProperty(globalThis, 'crypto', { value: undefined, configurable: true })
  try {
    assert.throws(assertBirthdayCryptoAvailable, /HTTPS/)
    await assert.rejects(encryptBirthdayLaunchCode(code, birthday), /HTTPS/)
    await assert.rejects(decryptBirthdayLaunchCode('bqr1.invalid', birthday), /HTTPS/)
  } finally {
    Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
  }
  const secureDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'isSecureContext')
  Object.defineProperty(globalThis, 'isSecureContext', { value: false, configurable: true })
  try {
    assert.throws(assertBirthdayCryptoAvailable, /HTTPS/)
  } finally {
    if (secureDescriptor) Object.defineProperty(globalThis, 'isSecureContext', secureDescriptor)
    else delete globalThis.isSecureContext
  }
})
