import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

const avatar = read('../packages/shared/src/composables/useAvatar.js')
const settings = read('../packages/shared/src/components/AvatarSettings.vue')
const patientView = read('../apps/patient/src/views/PatientView.vue')
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

test('D-ID credentials remain in memory and carry a public-bundle warning', () => {
  assert.match(patientView, /VITE_DID_CLIENT_KEY/)
  assert.match(patientView, /VITE_DID_AGENT_ID/)
  assert.match(settings, /公開的/)
  assert.doesNotMatch(avatar, /localStorage|sessionStorage/)
  assert.doesNotMatch(envExample, /VITE_DID_CLIENT_KEY=\S+/)
})
