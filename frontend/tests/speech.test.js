import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  AVATAR_SILENCE_MS,
  normalizeVoiceLevel,
  rootMeanSquare,
  updateVoiceActivity,
} from '../src/services/voiceActivity.js'

const patientView = readFileSync(
  new URL('../src/views/PatientView.vue', import.meta.url),
  'utf8',
)

test('records browser audio and stops automatically at sixty seconds', () => {
  assert.match(patientView, /new MediaRecorder\(mediaStream, options\)/)
  assert.match(patientView, /recordingTimeout = window\.setTimeout/)
  assert.match(patientView, /60_000/)
})

test('keeps transcribed text editable before avatar voice mode auto-submits', () => {
  assert.match(patientView, /input\.value = text/)
  assert.match(patientView, /scheduleAutoSend\(\)/)
  assert.match(patientView, /cancelAutoSendForEditing/)
  assert.match(patientView, /@input="cancelAutoSendForEditing"/)
  assert.match(patientView, /void submitMessage\(text\)/)
})

test('offers voice input for structured questions without auto-submitting them', () => {
  const questionnaireControl = readFileSync(
    new URL('../src/components/QuestionnaireControl.vue', import.meta.url),
    'utf8',
  )
  assert.doesNotMatch(
    patientView,
    /recording\.value \|\| sending\.value \|\| currentInputKind\.value !== 'text'/,
  )
  assert.match(patientView, /class="structured-voice-bar"/)
  assert.match(patientView, /applyVoiceTranscript\(text\)/)
  assert.match(
    patientView,
    /shouldAutoSubmit && currentInputKind\.value === 'text'/,
  )
  assert.match(patientView, /仍需確認後送出/)
  assert.match(questionnaireControl, /defineExpose\(\{ applyVoiceTranscript, focus \}\)/)
})

test('supports common Chrome Firefox and Safari recording containers', () => {
  assert.match(patientView, /audio\/webm;codecs=opus/)
  assert.match(patientView, /audio\/mp4/)
  assert.match(patientView, /audio\/webm/)
})

test('waits for speech before treating five seconds of silence as complete', () => {
  assert.equal(AVATAR_SILENCE_MS, 5_000)
  let state = updateVoiceActivity(undefined, { rms: 0, now: 10_000 })
  assert.equal(state.speechStarted, false)
  assert.equal(state.shouldStop, false)

  state = updateVoiceActivity(state, { rms: 0.05, now: 11_000 })
  assert.equal(state.speechStarted, true)
  assert.equal(state.shouldStop, false)

  state = updateVoiceActivity(state, { rms: 0, now: 15_999 })
  assert.equal(state.shouldStop, false)
  state = updateVoiceActivity(state, { rms: 0, now: 16_000 })
  assert.equal(state.shouldStop, true)
})

test('calculates zero RMS for browser silence and positive RMS for speech', () => {
  assert.equal(rootMeanSquare(new Uint8Array([128, 128, 128])), 0)
  assert.ok(rootMeanSquare(new Uint8Array([128, 180, 76])) > 0.2)
})

test('normalizes microphone volume for a stable visual waveform', () => {
  assert.equal(normalizeVoiceLevel(0), 0)
  assert.equal(normalizeVoiceLevel(0.006), 0)
  assert.equal(normalizeVoiceLevel(0.16), 1)
  assert.equal(normalizeVoiceLevel(9), 1)
  assert.ok(normalizeVoiceLevel(0.05) > 0)
  assert.ok(normalizeVoiceLevel(0.05) < 1)
})

test('shows a live waveform for both manual and avatar voice recording', () => {
  const waveform = readFileSync(
    new URL('../src/components/VoiceWaveform.vue', import.meta.url),
    'utf8',
  )
  assert.match(patientView, /startVoiceActivityDetection\(mediaStream, \{/)
  assert.match(patientView, /autoStop: autoSubmitOnSilence/)
  assert.match(patientView, /voiceLevel\.value = normalizeVoiceLevel\(rms\)/)
  assert.match(patientView, /voiceDetected\.value = voiceActivityState\.speechStarted/)
  assert.match(patientView, /<VoiceWaveform/)
  assert.match(patientView, /:level="voiceLevel"/)
  assert.match(waveform, /已收到聲音/)
  assert.match(waveform, /正在聆聽/)
  assert.match(waveform, /role="status"/)
})

test('asks the patient to repeat through the connected doctor avatar', () => {
  assert.match(patientView, /對不起，我沒有聽清楚，請再講一次。/)
  assert.match(patientView, /async function askPatientToRepeat/)
  assert.match(patientView, /await avatar\.speak\(prompt\)/)
  assert.match(patientView, /if \(!text\) \{\s*await askPatientToRepeat\(\)/)
  assert.match(patientView, /catch \(error\) \{\s*await askPatientToRepeat/)
})
