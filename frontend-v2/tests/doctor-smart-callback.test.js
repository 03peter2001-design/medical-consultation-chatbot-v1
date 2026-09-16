import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

import {
  completeDoctorSmartAuthorization,
  verifySmartUccContext,
} from '../apps/doctor/src/services/smartDoctorSession.js'

const root = path.resolve(import.meta.dirname, '..')

function memoryStorage() {
  const values = new Map([['chest-pain-ai-doctor.smart.pending', '1']])
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

function smartClient({ patient = 'patient-1', encounter = 'encounter-1' } = {}) {
  return {
    patient: { id: patient },
    encounter: { id: encounter },
    state: {
      tokenResponse: {
        patient,
        encounter,
        fhirUser: 'Practitioner/doctor-1',
      },
    },
  }
}

test('Doctor completes SMART callback only after matching explicit UCC FHIR context', async () => {
  const storage = memoryStorage()
  let replacement = ''
  const context = await completeDoctorSmartAuthorization({
    fhirLibrary: { oauth2: { ready: async () => smartClient() } },
    storageLike: storage,
    locationLike: {
      pathname: '/ai-consult/',
      search: '?smart=1&code=secret&state=oauth-state',
      hash: '#/doctor',
    },
    historyLike: {
      state: {},
      replaceState: (_state, _title, url) => {
        replacement = url
      },
    },
    uccContext: {
      patient: { fhir_reference: 'Patient/patient-1' },
      encounter: { fhir_reference: 'Encounter/encounter-1' },
    },
  })

  assert.deepEqual(context, {
    patientId: 'patient-1',
    encounterId: 'encounter-1',
    fhirUser: 'Practitioner/doctor-1',
    bindingVerified: true,
  })
  assert.equal(storage.getItem('chest-pain-ai-doctor.smart.pending'), null)
  assert.doesNotMatch(replacement, /secret/)
  assert.doesNotMatch(replacement, /smart=|state=/)
})

test('Doctor fails closed when SMART and explicit UCC context disagree', () => {
  assert.throws(
    () =>
      verifySmartUccContext(smartClient(), {
        fhir_patient_id: 'another-patient',
        fhir_encounter_id: 'encounter-1',
      }),
    /Patient.*UCC.*不一致/,
  )
  assert.throws(
    () =>
      verifySmartUccContext(smartClient(), {
        fhir_patient_id: 'patient-1',
        fhir_encounter_id: 'another-encounter',
      }),
    /Encounter.*UCC.*不一致/,
  )
})

test('Doctor can complete OAuth without treating unbound SMART context as trusted', () => {
  assert.deepEqual(verifySmartUccContext(smartClient(), {}), {
    patientId: 'patient-1',
    encounterId: 'encounter-1',
    fhirUser: 'Practitioner/doctor-1',
    bindingVerified: false,
  })
})

test('Doctor app keeps UCC bootstrap ahead of SMART callback completion', async () => {
  const app = await readFile(
    path.join(root, 'apps/doctor/src/App.vue'),
    'utf8',
  )
  assert.match(
    app,
    /const uccContext = await doctorSession\.start\(\)[\s\S]*completeDoctorSmartAuthorization\(\{ uccContext \}\)/,
  )
  assert.match(app, /SMART context 不會用於邀請或臨床寫入/)
})
