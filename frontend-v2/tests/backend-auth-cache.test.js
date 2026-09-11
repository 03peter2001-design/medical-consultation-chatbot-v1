import assert from 'node:assert/strict'
import test from 'node:test'

import { api, setAuthProvider } from '../packages/shared/src/services/backend.js'

test('doctor API requests and their authentication retry bypass the browser cache', async () => {
  const originalFetch = globalThis.fetch
  const requests = []
  let token = 'first-token'

  setAuthProvider({
    getToken: async () => token,
    refresh: async () => {
      token = 'refreshed-token'
    },
  })
  globalThis.fetch = async (_url, options) => {
    requests.push(options)
    const authorized = options.headers.get('Authorization') === 'Bearer refreshed-token'
    return new Response(JSON.stringify(authorized ? { items: [], total: 0 } : { detail: 'expired' }), {
      status: authorized ? 200 : 401,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  try {
    await api.listConsultations()
    assert.equal(requests.length, 2)
    assert.deepEqual(requests.map((options) => options.cache), ['no-store', 'no-store'])
    assert.equal(requests[1].headers.get('Authorization'), 'Bearer refreshed-token')
  } finally {
    setAuthProvider(null)
    globalThis.fetch = originalFetch
  }
})
