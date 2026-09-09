import assert from 'node:assert/strict'
import test from 'node:test'

import {
  api,
  fhirCompositionPath,
  setAuthProvider,
} from '../packages/shared/src/services/doctorBackend.js'

test('doctor API writes a confirmed Composition with UCC authorization', async () => {
  const originalFetch = globalThis.fetch
  let captured
  globalThis.fetch = async (url, options) => {
    captured = { url, options }
    return {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ status: 'created', resource_id: 'composition-1' }),
    }
  }
  setAuthProvider({ getToken: async () => 'synthetic-ucc-token' })
  const payload = {
    expected_updated_at: '2026-08-25T00:00:00Z',
    sections: [],
  }

  try {
    await api.createFhirComposition('2026-08-25:10000', payload)
  } finally {
    setAuthProvider(null)
    globalThis.fetch = originalFetch
  }

  assert.equal(
    fhirCompositionPath('2026-08-25:10000'),
    '/v1/doctor/consultations/2026-08-25%3A10000/fhir-composition',
  )
  assert.equal(
    captured.url,
    '/ai-api/v1/doctor/consultations/2026-08-25%3A10000/fhir-composition',
  )
  assert.equal(captured.options.method, 'POST')
  assert.equal(
    new Headers(captured.options.headers).get('Authorization'),
    'Bearer synthetic-ucc-token',
  )
  assert.deepEqual(JSON.parse(captured.options.body), payload)
})
