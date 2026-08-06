import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

const root = path.resolve(import.meta.dirname, '..')

async function distText(app) {
  const assets = path.join(root, 'apps', app, 'dist', 'assets')
  const files = await readdir(assets).catch(() => [])
  const chunks = await Promise.all(
    files.filter((file) => file.endsWith('.js')).map((file) => readFile(path.join(assets, file), 'utf8')),
  )
  return chunks.join('\n')
}

test('doctor router exposes no patient or SNOMED management route', async () => {
  const router = await readFile(path.join(root, 'apps/doctor/src/router.js'), 'utf8')
  assert.doesNotMatch(router, /PatientView|SnomedSearchView|terminology\/snomed/)
  assert.match(router, /path: '\/doctor'/)
  assert.match(router, /path: '\/doctor\/rules'/)
})

test('doctor source graph uses doctor-safe API and presentation modules', async () => {
  const doctorClient = await readFile(
    path.join(root, 'packages/shared/src/services/backend.js'),
    'utf8',
  )
  const clinicalRecord = await readFile(
    path.join(root, 'packages/shared/src/services/clinicalRecord.js'),
    'utf8',
  )
  const recordCard = await readFile(
    path.join(root, 'packages/shared/src/components/PatientRecordCard.vue'),
    'utf8',
  )
  const doctorEvidence = await readFile(
    path.join(root, 'packages/shared/src/doctor/components/ClinicalEvidence.vue'),
    'utf8',
  )
  const doctorView = await readFile(
    path.join(root, 'apps/doctor/src/views/DoctorView.vue'),
    'utf8',
  )
  const doctorSession = await readFile(
    path.join(root, 'packages/shared/src/auth/doctorSession.js'),
    'utf8',
  )

  assert.doesNotMatch(doctorClient, /patientChat|\/transcribe|apiPath\('\/chat'\)/)
  assert.doesNotMatch(clinicalRecord, /terminology\.js|SNOMED|snomed-registry/)
  assert.match(recordCard, /doctor\/components\/ClinicalEvidence\.vue/)
  assert.doesNotMatch(`${recordCard}\n${doctorEvidence}`, /TerminologyCode|SNOMED|snomed-registry/)
  assert.doesNotMatch(doctorView, /hasScope\(['"]invite:create['"]\)/)
  assert.match(doctorView, /doctorSession\.canCreateInvitation\(\)/)
  assert.match(doctorSession, /fetchImpl\(['"]\/AiConsult\/Invitations['"]/)
  assert.doesNotMatch(doctorSession, /\/v1\/invitations/)
})

test('patient source has no doctor router or doctor API client', async () => {
  const app = await readFile(path.join(root, 'apps/patient/src/App.vue'), 'utf8')
  const view = await readFile(path.join(root, 'apps/patient/src/views/PatientView.vue'), 'utf8')
  assert.doesNotMatch(`${app}\n${view}`, /vue-router|\/doctor|DoctorView|RuleCenter/)
  assert.match(`${app}\n${view}`, /patientBackend/)
})

test('each app injects its own same-origin API base at build time', async () => {
  const doctorConfig = await readFile(path.join(root, 'apps/doctor/vite.config.js'), 'utf8')
  const patientConfig = await readFile(path.join(root, 'apps/patient/vite.config.js'), 'utf8')
  const doctorClient = await readFile(
    path.join(root, 'packages/shared/src/services/backend.js'),
    'utf8',
  )
  const patientClient = await readFile(
    path.join(root, 'packages/shared/src/services/patientBackend.js'),
    'utf8',
  )

  assert.match(doctorConfig, /VITE_BACKEND_BASE_URL[^\n]+\|\| '\/ai-api'/)
  assert.match(patientConfig, /VITE_BACKEND_BASE_URL[^\n]+\|\| '\/api'/)
  assert.match(doctorConfig, /'import\.meta\.env\.VITE_BACKEND_BASE_URL'/)
  assert.match(patientConfig, /'import\.meta\.env\.VITE_BACKEND_BASE_URL'/)
  assert.match(doctorClient, /return '\/ai-api'/)
  assert.doesNotMatch(doctorClient, /return '\/api'/)
  assert.match(patientClient, /configured \|\| '\/api'/)
})

test('production bundles remain route-isolated when builds exist', async (t) => {
  const doctor = await distText('doctor')
  const patient = await distText('patient')
  if (!doctor || !patient) return t.skip('run npm run build before bundle inspection')
  assert.doesNotMatch(doctor, /PatientView|\/invitations\/exchange/)
  assert.doesNotMatch(doctor, /patientChat|\/transcribe|SNOMED CT|snomed-registry|TerminologyCode/)
  assert.doesNotMatch(patient, /DoctorView|\/doctor\/rules|\/doctor\/chat/)
  assert.match(doctor, /\/ai-api/)
  assert.doesNotMatch(doctor, /["'`]\/api["'`]/)
  assert.match(patient, /["'`]\/api["'`]/)
  assert.doesNotMatch(patient, /\/ai-api/)
})
