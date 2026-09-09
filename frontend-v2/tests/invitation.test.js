import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  cameraAccessErrorMessage,
  clearInvitationToken,
  invitationCodeFromScan,
  isInvitationCodeFormat,
  isPatientSessionPayload,
  normalizeInvitationCode,
  readInvitationToken,
} from '../packages/shared/src/auth/patientInvitation.js'

const code = 'AbCd_1234-efgh5678_IJKL9012-mnop3456'

test('reads invitation tokens from supported fragment formats', () => {
  assert.equal(readInvitationToken(`#token=${code}`), code)
  assert.equal(readInvitationToken(`#/invite?token=${code}`), code)
  assert.equal(readInvitationToken(`#invite=${code}`), code)
  assert.equal(readInvitationToken(`#${code}`), code)
  assert.equal(readInvitationToken(''), '')
})

test('accepts only bounded opaque invitation codes', () => {
  assert.equal(normalizeInvitationCode(`  ${code}\n`), code)
  assert.equal(isInvitationCodeFormat(code), true)
  assert.equal(isInvitationCodeFormat('short-code'), false)
  assert.equal(isInvitationCodeFormat(`${'A'.repeat(40)}.${'B'.repeat(40)}`), false)
  assert.equal(readInvitationToken('#%E0%A4%A'), '')
})

test('accepts only a complete active patient session payload', () => {
  assert.equal(
    isPatientSessionPayload({
      status: 'active',
      expires_at: '2026-09-09T12:00:00Z',
      interview_session_id: 'synthetic-session-1',
    }),
    true,
  )
  assert.equal(isPatientSessionPayload({}), false)
  assert.equal(
    isPatientSessionPayload({
      status: 'ok',
      expires_at: '2026-09-09T12:00:00Z',
      interview_session_id: 'synthetic-session-1',
    }),
    false,
  )
  assert.equal(
    isPatientSessionPayload({
      status: 'active',
      expires_at: '',
      interview_session_id: '',
    }),
    false,
  )
})

test('reads raw codes and full invitation URLs without accepting unsafe URLs', () => {
  assert.equal(invitationCodeFromScan(code), code)
  assert.equal(
    invitationCodeFromScan(`https://patient.example/#token=${code}`),
    code,
  )
  assert.equal(
    invitationCodeFromScan(`https://patient.example/start?code=${code}`),
    code,
  )
  assert.equal(invitationCodeFromScan('javascript:alert(1)'), '')
  assert.equal(invitationCodeFromScan('https://patient.example/#token=short'), '')
})

test('maps camera failures without exposing device error details', () => {
  assert.match(cameraAccessErrorMessage(null, false), /HTTPS/)
  assert.match(
    cameraAccessErrorMessage({ name: 'NotAllowedError', message: 'device details' }),
    /權限被拒絕或站台政策禁止/,
  )
  assert.match(cameraAccessErrorMessage({ name: 'NotFoundError' }), /找不到可用的相機/)
  assert.doesNotMatch(
    cameraAccessErrorMessage({ name: 'UnknownError', message: 'device details' }),
    /device details/,
  )
})

test('clears the fragment without changing path or query', () => {
  let replaced = ''
  let replacementState = null
  const originalState = { app: 'patient' }
  clearInvitationToken(
    { pathname: '/start', search: '?lang=zh-TW' },
    {
      state: originalState,
      replaceState: (state, _title, url) => {
        replacementState = state
        replaced = url
      },
    },
  )
  assert.equal(replaced, '/start?lang=zh-TW')
  assert.equal(replacementState, originalState)
})

test('removes invitation codes from the URL query while preserving other state', () => {
  let replaced = ''
  clearInvitationToken(
    {
      pathname: '/start',
      search: `?lang=zh-TW&code=${code}`,
    },
    {
      replaceState: (_state, _title, url) => { replaced = url },
    },
  )
  assert.equal(replaced, '/start?lang=zh-TW')
})

test('patient gate verifies the server session and scanner always provides paste fallback', () => {
  const app = readFileSync(
    new URL('../apps/patient/src/App.vue', import.meta.url),
    'utf8',
  )
  const entry = readFileSync(
    new URL('../apps/patient/src/components/PatientLaunchEntry.vue', import.meta.url),
    'utf8',
  )
  const scanner = readFileSync(
    new URL('../apps/patient/src/components/QrCodeScanner.vue', import.meta.url),
    'utf8',
  )

  assert.match(
    app,
    /patientApi\.session\(\)[\s\S]*patientApi\.exchangeInvitation\(code\)[\s\S]*patientApi\.session\(\)/,
  )
  assert.match(app, /exchangedInvitationToken !== code/)
  assert.match(app, /isPatientSessionPayload\(session\)/)
  assert.match(app, /invitationCodeFromScan\(window\.location\.href\)/)
  assert.match(app, /:patient-session="patientSession"/)
  assert.match(entry, /掃描 QR 或貼上一次性 code/)
  assert.match(entry, /code 或邀請連結/)
  assert.match(entry, /invitationCodeFromScan/)
  assert.match(entry, /驗證並開始/)
  assert.match(scanner, /BarcodeDetector/)
  assert.match(scanner, /import\('@zxing\/browser'\)/)
  assert.match(scanner, /getTracks\(\)\.forEach\(\(track\) => track\.stop\(\)\)/)
  assert.match(scanner, /zxingControls\?\.stop\(\)/)
  assert.match(scanner, /onBeforeUnmount\(stopScanner\)/)
})
