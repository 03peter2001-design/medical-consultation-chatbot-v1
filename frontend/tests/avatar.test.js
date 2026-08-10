import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  normalizeAvatarLanguage,
  normalizeAvatarProvider,
  useAvatar,
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
const startOverlay = readFileSync(
  new URL('../src/components/StartConsultationOverlay.vue', import.meta.url),
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
  assert.match(patientView, /VITE_DID_CLIENT_KEY/)
  assert.doesNotMatch(avatar, /localStorage|sessionStorage/)
  assert.doesNotMatch(avatar, /esm\.sh|vite-ignore/i)
})

test('coalesces local generation and revokes old object URLs', () => {
  assert.match(avatar, /pendingLocalSpeech = \{ id: requestId, text: input \}/)
  assert.match(avatar, /while \(pendingLocalSpeech/)
  assert.match(avatar, /requestId !== localSpeechRequestId/)
  assert.match(avatar, /URL\.revokeObjectURL/)
  assert.match(avatar, /URL\.createObjectURL/)
  assert.match(avatar, /activeRequestController\?\.abort\(\)/)
  assert.match(avatar, /signal: controller\.signal/)
  assert.match(avatar, /let userEnabled = false/)
})

test('keeps questions interactive and skips stale queued avatar renders', async () => {
  const calls = []
  const pending = new Map()
  const originalWarn = console.warn
  console.warn = (...args) => {
    if (!String(args[0]).includes('onBeforeUnmount')) originalWarn(...args)
  }
  const controller = useAvatar({
    getStatus: async () => ({ enabled: true, available: true }),
    warmup: async () => ({ available: true, loaded: true }),
    synthesize: (text) => {
      calls.push(text)
      return new Promise((resolve) => pending.set(text, resolve))
    },
  })
  console.warn = originalWarn

  await controller.connect()
  const worker = controller.speak('第一題')
  await new Promise((resolve) => setImmediate(resolve))
  void controller.speak('已經過時的第二題')
  void controller.speak('最新的第三題')

  assert.equal(controller.isConnected.value, true)
  assert.equal(controller.rendering.value, true)
  assert.equal(controller.caption.value, '最新的第三題')
  assert.deepEqual(calls, ['第一題'])

  pending.get('第一題')({ blob: new Blob(['first']) })
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(calls, ['第一題', '最新的第三題'])

  pending.get('最新的第三題')({ blob: new Blob(['third']) })
  await worker
  assert.equal(controller.rendering.value, false)
  assert.equal(controller.isConnected.value, true)
  await controller.disconnect()
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
  assert.match(stage, /<section\s+class="avatar-stage"/)
})

test('starts the avatar automatically and preserves an accessible text fallback', () => {
  assert.match(patientView, /onMounted\(\(\) => \{\s*void connectAvatar\(\)/)
  assert.match(patientView, /@connect-avatar="connectAvatar"/)
  assert.match(patientView, /@connect="connectAvatar"/)
  assert.match(startOverlay, /class="start-avatar-stage"/)
  assert.match(startOverlay, /<AvatarStage[\s\S]*?:avatar="avatar"/)
  assert.match(startOverlay, /<AvatarSettings[\s\S]*?:avatar="avatar"/)
  assert.match(startOverlay, /v-model:client-key="avatarClientKey"/)
  assert.match(startOverlay, /AI 醫師 Avatar 會自動啟用/)
  assert.match(stage, /Avatar 不影響問診；您仍可使用下方文字輸入。/)
  assert.match(stage, /重新啟用 Avatar/)
  assert.match(stage, /<button type="button" @click="emit\('connect'\)">/)
  assert.match(stage, /aria-live="polite"/)
})

test('keeps avatar configuration visible at start and collapsible during consultation', () => {
  assert.match(settings, /class="avatar-controls"/)
  assert.match(settings, /醫師 Avatar 設定/)
  assert.match(settings, /class="controls-grid"/)
  assert.match(settings, /avatar\.setProvider/)
  assert.match(settings, /avatar\.setLanguage/)
  assert.match(settings, /avatar\.disconnect/)
  assert.doesNotMatch(settings, /avatar-sidebar|drawer-backdrop|drawer-close/)
  assert.doesNotMatch(patientView, /mobileAvatarOpen|avatar-toggle|drawer-open/)
  assert.match(startOverlay, /<AvatarSettings[\s\S]*?:avatar="avatar"/)
  assert.match(patientView, /const consultationAvatarSettingsOpen = ref\(false\)/)
  assert.match(patientView, /const consultationAvatarVisible = computed/)
  assert.match(patientView, /avatar\.isConnected\.value \|\|[\s\S]*avatar\.isConnecting\.value \|\|[\s\S]*avatar\.rendering\.value/)
  assert.match(patientView, /v-if="started && consultationAvatarVisible"/)
  assert.match(patientView, /aria-controls="consultation-avatar-settings"/)
  assert.match(patientView, /:aria-expanded="consultationAvatarSettingsOpen"/)
  assert.match(patientView, /v-show="consultationAvatarSettingsOpen"/)
  assert.match(patientView, /consultationAvatarSettingsOpen \? '隱藏 ↑' : '顯示 ↓'/)
  assert.match(startOverlay, /class="start-workspace"/)
  assert.match(startOverlay, /grid-template-areas:\s*'stage actions'\s*'settings actions'/)
  assert.match(startOverlay, /grid-template-areas:\s*'stage'\s*'actions'\s*'settings'/)
  assert.match(startOverlay, /class="start-actions"/)
})

test('does not expose legacy AMIE traces in the patient consultation', () => {
  assert.doesNotMatch(patientView, /AmieTracePanel|amieTraces|amie_debug/)
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

test('keeps model and loading status visible in the controls and central stage', () => {
  assert.match(settings, /class="config-status"/)
  assert.match(settings, /role="status"/)
  assert.match(settings, /語音模型/)
  assert.match(settings, /唇形動畫/)
  assert.match(settings, /avatar\.status\.value/)
  assert.match(stage, /avatar\.isConnecting\.value/)
  assert.match(stage, /:aria-busy="avatar\.isConnecting\.value \|\| avatar\.rendering\.value"/)
  assert.match(stage, /AI 醫師準備中/)
  assert.match(stage, /模型載入／生成中/)
  assert.match(stage, /問題已顯示，可立即作答，不必等待影片完成。/)
  assert.match(stage, /avatar\.status\.value/)
  assert.match(patientView, /<AvatarStage[\s\S]*?:avatar="avatar"/)
})
