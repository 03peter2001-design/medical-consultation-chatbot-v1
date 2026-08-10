import assert from 'node:assert/strict'
import test from 'node:test'

import {
  api,
  apiVersionPrefix,
  audioUploadFilename,
  consultationDetailPath,
  consultationListPath,
  consultationLookupFields,
  credentialsForBackendUrl,
  diseaseProfileUpdatePath,
  factLabelUpdatePath,
  formatApiErrorDetail,
  resolveBackendUrl,
  ruleAssistantPath,
  ruleAuthorizationPath,
  ruleCenterPath,
  safetyRuleUpdatePath,
  snomedSearchPath,
} from '../src/services/backend.js'

test('uses the canonical versioned API prefix', () => {
  assert.equal(apiVersionPrefix, '/v1')
})

test('uses an audio filename that matches the browser recording type', () => {
  assert.equal(audioUploadFilename('audio/webm;codecs=opus'), 'audio.webm')
  assert.equal(audioUploadFilename('audio/mp4'), 'audio.m4a')
  assert.equal(audioUploadFilename('audio/ogg;codecs=opus'), 'audio.ogg')
})

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
    resolveBackendUrl(
      {
        search: '?backendPort=9000',
        protocol: 'http:',
        hostname: 'localhost',
      },
      '',
      {
        developmentMode: true,
        queryOverrideEnabled: 'true',
        queryOverrideOrigins: 'http://localhost:9000',
      },
    ),
    'http://localhost:9000',
  )
})

test('supports an explicitly enabled and allowlisted development backend override', () => {
  assert.equal(
    resolveBackendUrl(
      {
        search: '?backend=https://api.example.test/v1/',
        protocol: 'https:',
        hostname: 'app.example.test',
      },
      '',
      {
        developmentMode: true,
        queryOverrideEnabled: 'true',
        queryOverrideOrigins: 'https://api.example.test',
      },
    ),
    'https://api.example.test/v1',
  )
})

test('ignores backend query overrides by default', () => {
  assert.equal(
    resolveBackendUrl({
      search: '?backend=https://attacker.example/v1&backendPort=9443',
      protocol: 'https:',
      hostname: 'app.example.test',
    }),
    'https://app.example.test:8000',
  )
})

test('ignores backend query overrides outside development even when configured', () => {
  assert.equal(
    resolveBackendUrl(
      {
        search: '?backend=https://api.example.test/v1/',
        protocol: 'https:',
        hostname: 'app.example.test',
      },
      '/api',
      {
        developmentMode: false,
        queryOverrideEnabled: 'true',
        queryOverrideOrigins: 'https://api.example.test',
      },
    ),
    '/api',
  )
})

test('ignores an unallowlisted development backend origin', () => {
  assert.equal(
    resolveBackendUrl(
      {
        search: '?backend=https://attacker.example/v1/',
        protocol: 'https:',
        hostname: 'app.example.test',
      },
      '/api',
      {
        developmentMode: true,
        queryOverrideEnabled: 'true',
        queryOverrideOrigins: 'https://api.example.test',
      },
    ),
    '/api',
  )
})

test('supports a same-origin backend proxy path', () => {
  assert.equal(
    resolveBackendUrl(
      {
        search: '',
        protocol: 'https:',
        hostname: 'ehr-app.example.test',
      },
      '/api/',
    ),
    '/api',
  )
})

test('sends credentials only to the page origin', () => {
  const location = {
    origin: 'https://app.example.test',
    protocol: 'https:',
    hostname: 'app.example.test',
  }
  assert.equal(credentialsForBackendUrl('/api', location), 'include')
  assert.equal(
    credentialsForBackendUrl('https://app.example.test/api', location),
    'include',
  )
  assert.equal(
    credentialsForBackendUrl('https://api.example.test', location),
    'omit',
  )
})

test('builds an encoded consultation list query', () => {
  assert.equal(
    consultationListPath({
      search: ' 王小明 胸痛 ',
      limit: 20,
      offset: 40,
    }),
    '/v1/doctor/consultations?limit=20&offset=40&search=%E7%8E%8B%E5%B0%8F%E6%98%8E+%E8%83%B8%E7%97%9B',
  )
})

test('encodes a consultation identifier for delete requests', () => {
  assert.equal(
    consultationDetailPath('2026-08-05:001'),
    '/v1/doctor/consultations/2026-08-05%3A001',
  )
})

test('keeps a bare consultation number unqualified by date', () => {
  assert.deepEqual(consultationLookupFields(' 00000 '), {
    registration_number: '00000',
  })
})

test('keeps a date-qualified consultation id unchanged', () => {
  assert.deepEqual(consultationLookupFields(' 2026-08-04:001 '), {
    consultation_id: '2026-08-04:001',
  })
})

test('loads a doctor record by a bare number without binding it to today', async () => {
  const originalFetch = globalThis.fetch
  let captured
  globalThis.fetch = async (url, options) => {
    captured = { url, options }
    return {
      ok: true,
      json: async () => ({ consultation_id: '2026-08-04:00000' }),
    }
  }
  try {
    await api.loadPatient('00000', 'doctor-session')
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.deepEqual(JSON.parse(captured.options.body), {
    session_id: 'doctor-session',
    registration_number: '00000',
  })
  assert.equal(captured.options.credentials, 'omit')
})

test('loads a doctor record by the date-qualified consultation id', async () => {
  const originalFetch = globalThis.fetch
  let captured
  globalThis.fetch = async (url, options) => {
    captured = { url, options }
    return {
      ok: true,
      json: async () => ({ consultation_id: '2026-08-04:001' }),
    }
  }
  try {
    await api.loadPatient('2026-08-04:001', 'doctor-session')
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.match(captured.url, /\/v1\/doctor\/load_patient$/)
  assert.deepEqual(JSON.parse(captured.options.body), {
    session_id: 'doctor-session',
    consultation_id: '2026-08-04:001',
  })
})

test('uses dedicated doctor rule management endpoints', () => {
  assert.equal(ruleCenterPath, '/v1/doctor/rules')
  assert.equal(ruleAuthorizationPath, '/v1/doctor/rules/authorize')
  assert.equal(ruleAssistantPath, '/v1/doctor/rules/assistant')
  assert.equal(safetyRuleUpdatePath, '/v1/doctor/rules/safety')
  assert.equal(factLabelUpdatePath, '/v1/doctor/rules/fact-labels')
  assert.equal(
    diseaseProfileUpdatePath('chest/pilot'),
    '/v1/doctor/rules/disease-profiles/chest%2Fpilot',
  )
})

test('builds an encoded SNOMED CT search query', () => {
  assert.equal(
    snomedSearchPath({
      query: ' acute coronary syndrome ',
      limit: 25,
      offset: 50,
    }),
    '/v1/doctor/terminology/snomed?query=acute+coronary+syndrome&limit=25&offset=50',
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

test('turns a cross-date 409 into an actionable date-qualified lookup message', () => {
  assert.equal(
    formatApiErrorDetail(
      '此掛號編號跨日期重複，請指定日期或 consultation_id',
      409,
    ),
    '此掛號編號在不同日期有多筆病例，請輸入「YYYY-MM-DD:編號」指定日期。',
  )
})

test('shows an actionable message when a bare number is ambiguous across dates', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => ({
    ok: false,
    status: 409,
    json: async () => ({
      detail: '此掛號編號跨日期重複，請指定日期或 consultation_id',
    }),
  })
  try {
    await assert.rejects(
      api.loadPatient('001', 'doctor-session'),
      /請輸入「YYYY-MM-DD:編號」指定日期/,
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})
