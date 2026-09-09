import assert from 'node:assert/strict'
import test from 'node:test'

import {
  SMART_DOCTOR_QR_MODE,
  authorizeSmartEhrLaunch,
  hasSmartLaunchContext,
  initializeSmartPatient,
  isSmartDoctorQrCallback,
  markSmartLaunchPending,
  readSmartPatientRecord,
  resetSmartClientCache,
  sanitizeSmartCallbackUrl,
  smartCallbackUrl,
  smartEhrLaunchContext,
} from '../packages/shared/src/services/smart.js'

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

test('builds a base-aware callback URL before the hash route', () => {
  assert.equal(
    smartCallbackUrl(
      { origin: 'http://127.0.0.1:5173' },
      '/ai-consult/',
    ),
    'http://127.0.0.1:5173/ai-consult/?smart=1',
  )
  assert.equal(
    smartCallbackUrl(
      { origin: 'https://consult.example.test' },
      '/ai-consult/',
      SMART_DOCTOR_QR_MODE,
    ),
    'https://consult.example.test/ai-consult/?smart=1&launch_mode=doctor-qr',
  )
  assert.equal(
    isSmartDoctorQrCallback({
      search: '?smart=1&launch_mode=doctor-qr&code=secret',
    }),
    true,
  )
  assert.equal(
    isSmartDoctorQrCallback({ search: '?smart=1' }),
    false,
  )
})

test('starts the QR launcher OAuth flow with its dedicated callback mode', async () => {
  let options = null
  await authorizeSmartEhrLaunch({
    fhirLibrary: {
      oauth2: {
        authorize: async (value) => { options = value },
      },
    },
    clientId: 'test-client',
    locationLike: {
      origin: 'https://consult.example.test',
      search: '?iss=https%3A%2F%2F192.168.102.51%2Ffhir&launch=launch-123',
    },
    storageLike: memoryStorage(),
    basePath: '/ai-consult/',
    callbackMode: SMART_DOCTOR_QR_MODE,
  })

  assert.equal(
    options.redirectUri,
    'https://consult.example.test/ai-consult/?smart=1&launch_mode=doctor-qr',
  )
  assert.equal(options.iss, 'https://192.168.102.51/fhir')
})

test('validates EHR launch parameters without accepting unsafe issuers', () => {
  assert.deepEqual(
    smartEhrLaunchContext({
      search:
        '?iss=https%3A%2F%2Fehr.example%2Ffhir%2F&launch=launch-123',
    }),
    {
      issuer: 'https://ehr.example/fhir',
      launch: 'launch-123',
    },
  )
  assert.throws(
    () => smartEhrLaunchContext({ search: '?iss=javascript:alert(1)&launch=x' }),
    /HTTP\(S\)/,
  )
  assert.throws(
    () => smartEhrLaunchContext({ search: '?iss=https://ehr.example/fhir' }),
    /iss 或 launch/,
  )
})

test('starts provider OAuth with the registered base-aware callback', async () => {
  const storage = memoryStorage()
  let options = null
  await authorizeSmartEhrLaunch({
    fhirLibrary: {
      oauth2: {
        authorize: async (value) => {
          options = value
        },
      },
    },
    clientId: 'test-client',
    locationLike: {
      origin: 'http://127.0.0.1:5173',
      search:
        '?iss=https%3A%2F%2Fehr.example%2Ffhir&launch=launch-123',
    },
    storageLike: storage,
    basePath: '/ai-consult/',
  })

  assert.deepEqual(options, {
    clientId: 'test-client',
    scope: 'launch patient/*.read',
    redirectUri: 'http://127.0.0.1:5173/ai-consult/?smart=1',
    iss: 'https://ehr.example/fhir',
    launch: 'launch-123',
  })
  assert.equal(hasSmartLaunchContext({ search: '' }, storage), true)
})

test('clears the pending hint when OAuth cannot start', async () => {
  const storage = memoryStorage()
  await assert.rejects(
    () =>
      authorizeSmartEhrLaunch({
        fhirLibrary: {
          oauth2: {
            authorize: async () => {
              throw new Error('discovery unavailable')
            },
          },
        },
        clientId: 'test-client',
        locationLike: {
          origin: 'http://127.0.0.1:5173',
          search: '?iss=https%3A%2F%2Fehr.example%2Ffhir&launch=launch-123',
        },
        storageLike: storage,
        basePath: '/ai-consult/',
      }),
    /discovery unavailable/,
  )
  assert.equal(hasSmartLaunchContext({ search: '' }, storage), false)
})

test('removes the authorization code from browser history', () => {
  let replacement = ''
  let replacementState = null
  const originalState = { current: '/#/' }
  const result = sanitizeSmartCallbackUrl(
    {
      pathname: '/ai-consult/',
      search: '?smart=1&code=secret-code&state=state-1',
      hash: '#/',
    },
    {
      state: originalState,
      replaceState: (state, _title, url) => {
        replacementState = state
        replacement = url
      },
    },
  )
  assert.equal(result, '/ai-consult/?smart=1&state=state-1#/')
  assert.equal(replacement, '/ai-consult/?smart=1&state=state-1#/')
  assert.equal(replacementState, originalState)
})

test('reads the launch-context patient through the authorized client', async () => {
  const requests = []
  let patientReadOptions = null
  const record = await readSmartPatientRecord({
    patient: {
      id: 'patient-123',
      read: async (options) => {
        patientReadOptions = options
        return {
          resourceType: 'Patient',
          id: 'patient-123',
          name: [{ text: 'SMART 測試病人' }],
        }
      },
    },
    encounter: { id: 'encounter-456' },
    state: {
      serverUrl: 'https://ehr.example/fhir',
      tokenResponse: {
        access_token: 'must-not-leak',
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
  assert.doesNotMatch(JSON.stringify(record), /must-not-leak/)
  assert.deepEqual(patientReadOptions, {
    cache: 'no-store',
    headers: {
      Accept: 'application/fhir+json',
      'Cache-Control': 'no-cache',
    },
  })
  assert.deepEqual(requests, [
    {
      url: {
        url: 'Patient/patient-123/$everything?_count=100',
        cache: 'no-store',
        headers: {
          Accept: 'application/fhir+json',
          'Cache-Control': 'no-cache',
        },
      },
      options: { flat: false, pageLimit: 10 },
    },
  ])
})

test('uses the matching Patient returned by $everything for current identity', async () => {
  const record = await readSmartPatientRecord({
    patient: {
      id: 'patient-123',
      read: async () => ({
        resourceType: 'Patient',
        id: 'patient-123',
        name: [{ text: '先前快取姓名' }],
      }),
    },
    state: { serverUrl: 'https://ehr.example/fhir' },
    request: async () => ({
      resourceType: 'Bundle',
      entry: [
        {
          resource: {
            resourceType: 'Patient',
            id: 'patient-123',
            name: [{ text: '本次病人姓名' }],
          },
        },
      ],
    }),
  })

  assert.equal(record.patient.name[0].text, '本次病人姓名')
  assert.equal(record.resources[0], record.patient)
})

test('rejects a Patient mismatch between launch context and $everything', async () => {
  await assert.rejects(
    () =>
      readSmartPatientRecord({
        patient: {
          id: 'patient-123',
          read: async () => ({
            resourceType: 'Patient',
            id: 'patient-123',
          }),
        },
        state: { serverUrl: 'https://ehr.example/fhir' },
        request: async () => ({
          resourceType: 'Bundle',
          entry: [
            {
              resource: {
                resourceType: 'Patient',
                id: 'patient-456',
              },
            },
          ],
        }),
      }),
    /token 為 Patient\/patient-123.*Patient\/patient-456/,
  )
})

test('rejects a Patient mismatch between launch context and Patient read', async () => {
  await assert.rejects(
    () =>
      readSmartPatientRecord({
        patient: {
          id: 'patient-123',
          read: async () => ({
            resourceType: 'Patient',
            id: 'patient-456',
          }),
        },
      }),
    /token 為 Patient\/patient-123.*Patient\/patient-456/,
  )
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
    locationLike: { search: '?smart=1&state=state-1' },
  })
  const second = await initializeSmartPatient({
    fhirLibrary,
    storageLike: storage,
    locationLike: { search: '?smart=1&state=state-1' },
  })

  assert.equal(first, second)
  assert.equal(readyCalls, 1)
  assert.equal(hasSmartLaunchContext({ search: '' }, storage), false)
  resetSmartClientCache()
})

test('reloads the patient when a new SMART launch state is received', async () => {
  resetSmartClientCache()
  const clients = [
    {
      patient: {
        id: 'patient-1',
        read: async () => ({
          resourceType: 'Patient',
          id: 'patient-1',
          name: [{ text: '第一位病人' }],
        }),
      },
      state: { serverUrl: 'https://ehr.example/fhir' },
      request: async () => ({ resourceType: 'Bundle', entry: [] }),
    },
    {
      patient: {
        id: 'patient-2',
        read: async () => ({
          resourceType: 'Patient',
          id: 'patient-2',
          name: [{ text: '第二位病人' }],
        }),
      },
      state: { serverUrl: 'https://ehr.example/fhir' },
      request: async () => ({ resourceType: 'Bundle', entry: [] }),
    },
  ]
  let readyCalls = 0
  const fhirLibrary = {
    oauth2: {
      ready: async () => clients[readyCalls++],
    },
  }

  const first = await initializeSmartPatient({
    fhirLibrary,
    locationLike: { search: '?smart=1&state=state-1' },
  })
  const second = await initializeSmartPatient({
    fhirLibrary,
    locationLike: { search: '?smart=1&state=state-2' },
  })

  assert.equal(readyCalls, 2)
  assert.equal(first.patient.id, 'patient-1')
  assert.equal(first.patient.name[0].text, '第一位病人')
  assert.equal(second.patient.id, 'patient-2')
  assert.equal(second.patient.name[0].text, '第二位病人')
  resetSmartClientCache()
})
