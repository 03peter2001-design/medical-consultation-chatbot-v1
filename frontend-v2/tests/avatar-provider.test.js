import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

const avatar = read('../packages/shared/src/composables/useAvatar.js')
const settings = read('../packages/shared/src/components/AvatarSettings.vue')
const patientView = read('../apps/patient/src/views/PatientView.vue')
const stage = read('../apps/patient/src/components/AvatarStage.vue')
const envExample = read('../apps/patient/.env.example')

test('patient app supports local and D-ID providers with local as default', () => {
  assert.match(avatar, /import\('@d-id\/client-sdk'\)/i)
  assert.match(avatar, /createAgentManager/)
  assert.match(avatar, /initialProvider = 'local'/)
  assert.match(settings, /value="local"/)
  assert.match(settings, /value="did"/)
  assert.match(patientView, /VITE_AVATAR_PROVIDER/)
  assert.match(envExample, /VITE_AVATAR_PROVIDER=local/)
  assert.doesNotMatch(avatar, /esm\.sh|vite-ignore/i)
})

test('patient can select Mandarin or Minnan for questionnaire and local speech', () => {
  assert.match(avatar, /function normalizeAvatarLanguage/)
  assert.match(avatar, /function setLanguage/)
  assert.match(settings, /問卷與醫生語言/)
  assert.match(settings, /avatar\.setLanguage/)
  assert.match(settings, /<option value="mandarin">國語<\/option>/)
  assert.match(settings, /<option value="minnan">台語<\/option>/)
  assert.match(patientView, /avatar\.language\.value/)
})

test('D-ID credentials remain in memory and carry a public-bundle warning', () => {
  assert.match(patientView, /VITE_DID_CLIENT_KEY/)
  assert.match(patientView, /VITE_DID_AGENT_ID/)
  assert.match(settings, /公開的/)
  assert.doesNotMatch(avatar, /localStorage|sessionStorage/)
  assert.doesNotMatch(envExample, /VITE_DID_CLIENT_KEY=\S+/)
})

test('keeps the deployed patient doctor, caption, chat text, and audio controls visible', () => {
  assert.match(avatar, /const caption = ref\(''\)/)
  assert.match(avatar, /caption\.value = input/)
  assert.match(patientView, /import AvatarStage from '\.\.\/components\/AvatarStage\.vue'/)
  assert.match(patientView, /const consultationAvatarVisible = computed/)
  assert.match(patientView, /<AvatarStage[\s\S]*v-if="started && consultationAvatarVisible"/)
  assert.match(patientView, /v-for="message in messages"/)
  assert.match(stage, /avatar\.imageUrl\.value/)
  assert.match(stage, /avatar\.videoUrl\.value/)
  assert.match(stage, /avatar\.caption\.value/)
  assert.match(stage, /ref="localVideoElement"/)
  assert.match(stage, /controls/)
  assert.match(stage, /@loadedmetadata="playLocalVideo"/)
  assert.match(stage, /playbackBlocked/)
  assert.match(stage, /播放醫師語音/)
  assert.doesNotMatch(settings, /<video/)
})
