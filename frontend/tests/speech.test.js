import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const patientView = readFileSync(
  new URL('../src/views/PatientView.vue', import.meta.url),
  'utf8',
)

test('records browser audio and stops automatically at sixty seconds', () => {
  assert.match(patientView, /new MediaRecorder\(mediaStream, options\)/)
  assert.match(patientView, /recordingTimeout = window\.setTimeout/)
  assert.match(patientView, /60_000/)
})

test('fills the input for patient confirmation instead of auto-submitting ASR text', () => {
  assert.match(patientView, /input\.value = text/)
  assert.match(patientView, /請確認文字後再送出/)
  assert.doesNotMatch(patientView, /submitMessage\(text\)/)
})

test('supports common Chrome Firefox and Safari recording containers', () => {
  assert.match(patientView, /audio\/webm;codecs=opus/)
  assert.match(patientView, /audio\/mp4/)
  assert.match(patientView, /audio\/webm/)
})
