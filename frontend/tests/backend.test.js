import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveBackendUrl } from '../src/services/backend.js'

test('uses the page hostname and default backend port', () => {
  assert.equal(
    resolveBackendUrl({
      search: '',
      protocol: 'http:',
      hostname: '192.168.1.20',
    }),
    'http://192.168.1.20:8000',
  )
})

test('supports a custom backend port', () => {
  assert.equal(
    resolveBackendUrl({
      search: '?backendPort=9000',
      protocol: 'http:',
      hostname: 'localhost',
    }),
    'http://localhost:9000',
  )
})

test('supports a complete backend URL override', () => {
  assert.equal(
    resolveBackendUrl({
      search: '?backend=https://api.example.test/v1/',
      protocol: 'https:',
      hostname: 'app.example.test',
    }),
    'https://api.example.test/v1',
  )
})
