import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  normalizeAvatarLanguage,
  normalizeAvatarProvider,
} from '../src/composables/useAvatar.js'

const avatar = readFileSync(
  new URL('../src/composables/useAvatar.js', import.meta.url),
  'utf8',
)
const settings = readFileSync(
  new URL('../src/components/AvatarSettings.vue', import.meta.url),
  'utf8',
)
const stage = readFileSync(
  new URL('../src/components/AvatarStage.vue', import.meta.url),
  'utf8',
)
const patientView = readFileSync(
  new URL('../src/views/PatientView.vue', import.meta.url),
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

test('uses the bundled doctor image and renders a central captioned stage', () => {
  assert.match(avatar, /dr%20training%20pc\.png/)
  assert.doesNotMatch(avatar, /['"]\/avatar\/doctor\.png['"]/)
  assert.match(stage, /class="avatar-stage"/)
  assert.match(stage, /avatar\.caption\.value/)
  assert.match(stage, /justify-content: center/)
})

test('offers Mandarin and Minnan and sends the selected language', () => {
  assert.equal(normalizeAvatarLanguage(), 'mandarin')
  assert.equal(normalizeAvatarLanguage('unknown'), 'mandarin')
  assert.equal(normalizeAvatarLanguage(' MINNAN '), 'minnan')
  assert.match(settings, /醫生說話語言/)
  assert.match(settings, /<option value="mandarin">國語<\/option>/)
  assert.match(settings, /<option value="minnan">閩南語<\/option>/)
  assert.match(avatar, /language: language\.value/)
  assert.match(backend, /language: options\.language \|\| 'mandarin'/)
  assert.match(stage, /avatar\.languageLabel\.value/)
})

test('warms every local voice model before marking the avatar connected', () => {
  assert.match(backend, /avatar\/warmup/)
  assert.match(avatar, /正在預載 Breeze ASR、CosyVoice3 與 MuseTalk/)
  assert.match(avatar, /const warmed = await warmup\(\)/)
  assert.match(avatar, /!warmed\.available \|\| !warmed\.loaded/)
})

test('keeps model loading status visible in the drawer and central stage', () => {
  assert.match(settings, /model-loading-overlay/)
  assert.match(settings, /模型載入／生成中/)
  assert.match(settings, /avatar\.status\.value/)
  assert.match(stage, /avatar\.isConnecting\.value/)
  assert.match(stage, /:aria-busy="avatar\.isConnecting\.value"/)
  assert.match(stage, /AI 醫師準備中/)
  assert.match(stage, /模型載入／生成中/)
  assert.match(stage, /avatar\.status\.value/)
  assert.match(patientView, /<AvatarStage :avatar="avatar"/)
})
