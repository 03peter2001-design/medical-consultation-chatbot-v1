import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const launchHtml = readFileSync(
  new URL('../launch.html', import.meta.url),
  'utf8',
)
const launchEntry = readFileSync(
  new URL('../src/smartLaunchEntry.js', import.meta.url),
  'utf8',
)
const router = readFileSync(
  new URL('../src/router.js', import.meta.url),
  'utf8',
)
const doctorLauncher = readFileSync(
  new URL('../src/views/DoctorLauncherView.vue', import.meta.url),
  'utf8',
)
const viteConfig = readFileSync(
  new URL('../vite.config.js', import.meta.url),
  'utf8',
)

test('ships a local SMART launch entry without an external script dependency', () => {
  assert.match(launchHtml, /data-smart-launch-status/)
  assert.match(launchHtml, /src="\/src\/smartLaunchEntry\.js"/)
  assert.doesNotMatch(launchHtml, /https?:\/\/[^"']+\.js/)
  assert.match(launchEntry, /import FHIR from 'fhirclient'/)
  assert.match(launchEntry, /VITE_SMART_CLIENT_ID/)
  assert.match(launchEntry, /import\.meta\.env\.BASE_URL/)
  assert.match(launchEntry, /SMART_DOCTOR_QR_MODE/)
})

test('routes the dedicated SMART callback to the QR result view', () => {
  assert.match(router, /isSmartDoctorQrCallback\(\)/)
  assert.match(router, /#\/doctor\/launcher/)
  assert.match(doctorLauncher, /initializeSmartPatient\(\)/)
  assert.match(doctorLauncher, /smartContext\.value\.fhirBaseUrl/)
  assert.match(doctorLauncher, /api\.createDoctorLaunchInvitation/)
  assert.doesNotMatch(doctorLauncher, /loadPatientByIdentifier/)
  assert.doesNotMatch(doctorLauncher, /VITE_ENABLE_DIRECT_FHIR/)
})

test('builds both app and launch documents under the configured base', () => {
  assert.match(viteConfig, /base: '\/ai-consult\/'/)
  assert.match(viteConfig, /launch: fileURLToPath/)
  assert.match(viteConfig, /new URL\('\.\/launch\.html'/)
  assert.match(router, /createWebHashHistory\(import\.meta\.env\.BASE_URL\)/)
})
