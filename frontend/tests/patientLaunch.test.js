import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  cameraAccessErrorMessage,
  isLaunchCodeFormat,
  launchCodeFromScan,
  launchCountdownLabel,
  launchSecondsRemaining,
  normalizeLaunchCode,
} from '../src/services/patientLaunch.js'

const code = 'AbCd_1234-efgh5678_IJKL9012-mnop3456'

test('accepts only bounded opaque base64url-style launcher codes', () => {
  assert.equal(normalizeLaunchCode(`  ${code}\n`), code)
  assert.equal(isLaunchCodeFormat(code), true)
  assert.equal(isLaunchCodeFormat('short-code'), false)
  assert.equal(isLaunchCodeFormat(`${'A'.repeat(40)}.${'B'.repeat(40)}`), false)
  assert.equal(isLaunchCodeFormat(`${'A'.repeat(40)} patient-id`), false)
})

test('reads raw codes and legacy fragment URLs without decoding identity data', () => {
  assert.equal(launchCodeFromScan(code), code)
  assert.equal(
    launchCodeFromScan(`https://patient.example/ai-consult/#/?token=${code}`),
    code,
  )
  assert.equal(
    launchCodeFromScan(`https://patient.example/#token=${code}`),
    code,
  )
  assert.equal(launchCodeFromScan('javascript:alert(1)'), '')
  assert.equal(launchCodeFromScan('https://patient.example/#/?token=short'), '')
})

test('formats a bounded launcher expiry countdown', () => {
  assert.equal(
    launchSecondsRemaining('2026-08-27T00:05:00Z', Date.parse('2026-08-27T00:00:00Z')),
    300,
  )
  assert.equal(
    launchSecondsRemaining('2026-08-26T23:59:59Z', Date.parse('2026-08-27T00:00:00Z')),
    0,
  )
  assert.equal(launchCountdownLabel(300), '5:00')
  assert.equal(launchCountdownLabel(9), '0:09')
})

test('explains secure-context and camera permission failures safely', () => {
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

test('scanner and patient entry retain camera cleanup and paste fallback', () => {
  const scanner = readFileSync(
    new URL('../src/components/QrCodeScanner.vue', import.meta.url),
    'utf8',
  )
  const entry = readFileSync(
    new URL('../src/components/PatientLaunchEntry.vue', import.meta.url),
    'utf8',
  )
  const patientView = readFileSync(
    new URL('../src/views/PatientView.vue', import.meta.url),
    'utf8',
  )

  assert.match(scanner, /BarcodeDetector/)
  assert.match(scanner, /import\('@zxing\/browser'\)/)
  assert.match(scanner, /BrowserQRCodeReader/)
  assert.match(scanner, /getUserMedia/)
  assert.match(scanner, /getTracks\(\)\.forEach\(\(track\) => track\.stop\(\)\)/)
  assert.match(scanner, /onBeforeUnmount\(stopScanner\)/)
  assert.match(scanner, /onMounted/)
  assert.match(scanner, /zxingControls\?\.stop\(\)/)
  assert.match(entry, /掃描 QR 或貼上一次性 code/)
  assert.match(entry, /驗證並開始/)
  assert.match(patientView, /api\.exchangeInvitation\(code\)/)
  assert.match(patientView, /api\.patientSession\(\)/)
  assert.match(patientView, /finishConsultationStart\(null/)
})
