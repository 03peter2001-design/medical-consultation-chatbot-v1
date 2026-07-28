import assert from 'node:assert/strict'
import test from 'node:test'

import {
  consultationDetailPath,
  consultationListPath,
  formatApiErrorDetail,
  resolveBackendUrl,
} from '../src/services/backend.js'

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

test('builds an encoded consultation list query', () => {
  assert.equal(
    consultationListPath({
      search: ' 王小明 胸痛 ',
      limit: 20,
      offset: 40,
    }),
    '/doctor/consultations?limit=20&offset=40&search=%E7%8E%8B%E5%B0%8F%E6%98%8E+%E8%83%B8%E7%97%9B',
  )
})

test('encodes a consultation identifier for delete requests', () => {
  assert.equal(
    consultationDetailPath('急診/001'),
    '/doctor/consultations/%E6%80%A5%E8%A8%BA%2F001',
  )
})

test('formats FastAPI validation errors with their field path', () => {
  assert.equal(
    formatApiErrorDetail(
      [
        {
          loc: ['body', 'pain_location_ids'],
          msg: '未知的疼痛位置：front_unknown',
        },
      ],
      422,
    ),
    'pain_location_ids：未知的疼痛位置：front_unknown',
  )
  assert.equal(formatApiErrorDetail(null, 500), 'HTTP 500')
})
