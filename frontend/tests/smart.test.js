import assert from 'node:assert/strict'
import test from 'node:test'

import {
  hasSmartLaunchContext,
  initializeSmartPatient,
  markSmartLaunchPending,
  readSmartPatientRecord,
  resetSmartClientCache,
  sanitizeSmartCallbackUrl,
} from '../src/services/smart.js'

function memoryStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}

test('detects SMART callbacks and the launch pending hint', () => {
  const storage = memoryStorage()
  assert.equal(
    hasSmartLaunchContext(
      { search: '?smart=1&code=abc&state=state-1' },
      storage,
    ),
    true,
  )
  assert.equal(hasSmartLaunchContext({ search: '' }, storage), false)
  markSmartLaunchPending(storage)
  assert.equal(hasSmartLaunchContext({ search: '' }, storage), true)
  markSmartLaunchPending(storage, false)
  assert.equal(hasSmartLaunchContext({ search: '' }, storage), false)
})

test('removes the authorization code from browser history', () => {
  let replacement = ''
  const result = sanitizeSmartCallbackUrl(
    {
      pathname: '/',
      search: '?smart=1&code=secret-code&state=state-1',
      hash: '#/',
    },
    {
      replaceState: (_state, _title, url) => {
        replacement = url
      },
    },
  )
  assert.equal(result, '/?smart=1&state=state-1#/')
  assert.equal(replacement, '/?smart=1&state=state-1#/')
})

test('reads the launch-context patient through the authorized client', async () => {
  const requests = []
  const record = await readSmartPatientRecord({
    patient: {
      id: 'patient-123',
      read: async () => ({
        resourceType: 'Patient',
        id: 'patient-123',
        name: [{ text: 'SMART 測試病人' }],
      }),
    },
    encounter: { id: 'encounter-456' },
    state: {
      serverUrl: 'https://ehr.example/fhir',
      tokenResponse: {
        scope: 'launch patient/*.read',
      },
    },
    request: async (url, options) => {
      requests.push({ url, options })
      return {
        resourceType: 'Bundle',
        entry: [
          {
            resource: {
              resourceType: 'Condition',
              id: 'condition-1',
            },
          },
        ],
      }
    },
  })

  assert.equal(record.patient.id, 'patient-123')
  assert.equal(record.resources[0].resourceType, 'Patient')
  assert.equal(record.resources[1].resourceType, 'Condition')
  assert.equal(record.smart.encounterId, 'encounter-456')
  assert.deepEqual(record.smart.scopes, ['launch', 'patient/*.read'])
  assert.deepEqual(requests, [
    {
      url: 'Patient/patient-123/$everything?_count=100',
      options: { flat: false, pageLimit: 10 },
    },
  ])
})

test('rejects SMART launches without a patient context', async () => {
  await assert.rejects(
    () => readSmartPatientRecord({ patient: {} }),
    /沒有 patient id/,
  )
})

test('initializes OAuth once and clears the pending hint', async () => {
  resetSmartClientCache()
  const storage = memoryStorage()
  markSmartLaunchPending(storage)
  let readyCalls = 0
  const client = {
    patient: {
      id: 'patient-1',
      read: async () => ({
        resourceType: 'Patient',
        id: 'patient-1',
      }),
    },
    state: { serverUrl: 'https://ehr.example/fhir' },
    request: async () => ({ resourceType: 'Bundle', entry: [] }),
  }
  const fhirLibrary = {
    oauth2: {
      ready: async () => {
        readyCalls += 1
        return client
      },
    },
  }

  const first = await initializeSmartPatient({
    fhirLibrary,
    storageLike: storage,
  })
  const second = await initializeSmartPatient({
    fhirLibrary,
    storageLike: storage,
  })

  assert.equal(first, second)
  assert.equal(readyCalls, 1)
  assert.equal(hasSmartLaunchContext({ search: '' }, storage), false)
  resetSmartClientCache()
})
