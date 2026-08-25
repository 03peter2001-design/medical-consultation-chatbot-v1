import assert from 'node:assert/strict'
import test from 'node:test'

import {
  authorizeSmartEhrLaunch,
  hasSmartLaunchContext,
  initializeSmartPatient,
  markSmartLaunchPending,
  readSmartPatientRecord,
  resetSmartClientCache,
  sanitizeSmartCallbackUrl,
  smartCallbackUrl,
  smartEhrLaunchContext,
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

test('builds a base-aware callback URL before the hash route', () => {
  assert.equal(
    smartCallbackUrl(
      { origin: 'http://127.0.0.1:5173' },
      '/ai-consult/',
    ),
    'http://127.0.0.1:5173/ai-consult/?smart=1',
  )
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
