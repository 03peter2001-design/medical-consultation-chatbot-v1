import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { normalizeAvatarProvider } from '../src/composables/useAvatar.js'

const avatar = readFileSync(
  new URL('../src/composables/useAvatar.js', import.meta.url),
  'utf8',
)
const settings = readFileSync(
  new URL('../src/components/AvatarSettings.vue', import.meta.url),
  'utf8',
)
const backend = readFileSync(
  new URL('../src/services/backend.js', import.meta.url),
  'utf8',
)

test('keeps local and D-ID avatar providers available', () => {
  assert.match(backend, /\/avatar\/status/)
  assert.match(backend, /\/avatar\/speak/)
  assert.match(avatar, /import\('@d-id\/client-sdk'\)/i)
  assert.match(avatar, /createAgentManager/)
  assert.match(settings, /client key/i)
  assert.match(settings, /agent id/i)
  assert.match(settings, /VITE_DID_CLIENT_KEY/)
  assert.doesNotMatch(avatar, /localStorage|sessionStorage/)
  assert.doesNotMatch(avatar, /esm\.sh|vite-ignore/i)
})

test('serializes local generation and revokes old object URLs', () => {
  assert.match(avatar, /speechQueue = speechQueue/)
  assert.match(avatar, /URL\.revokeObjectURL/)
  assert.match(avatar, /URL\.createObjectURL/)
  assert.match(avatar, /activeRequestController\?\.abort\(\)/)
  assert.match(avatar, /signal: controller\.signal/)
  assert.match(avatar, /let userEnabled = false/)
})

test('defaults invalid or missing provider settings to local', () => {
  assert.match(avatar, /initialProvider = 'local'/)
  assert.match(avatar, /=== 'did' \? 'did' : 'local'/)
  assert.equal(normalizeAvatarProvider(), 'local')
  assert.equal(normalizeAvatarProvider('unknown'), 'local')
  assert.equal(normalizeAvatarProvider(' DID '), 'did')
})
