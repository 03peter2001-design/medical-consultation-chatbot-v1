import assert from 'node:assert/strict'
import test from 'node:test'

import { createDoctorSession } from '../packages/shared/src/auth/doctorSession.js'

function jwt(exp) {
  const encode = (value) => Buffer.from(JSON.stringify(value)).toString('base64url')
  return `${encode({ alg: 'none' })}.${encode({ exp })}.signature`
}

test('bootstrap stays in memory and forwards regSno', async () => {
  const calls = []
  const session = createDoctorSession({
    locationLike: { search: '?regSno=12345' },
    fetchImpl: async (url, options) => {
      calls.push({ url, options })
      return new Response(JSON.stringify({
        access_token: jwt(Math.floor(Date.now() / 1000) + 300),
        csrf_token: 'csrf',
        encounter: { reg_sno: 12345 },
        scopes: ['consultation:read', 'rules:write'],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    },
  })

  await session.start()
  assert.match(calls[0].url, /regSno=12345/)
  assert.equal(session.hasScope('rules:write'), true)
  assert.equal(session.hasScope('invite:create'), false)
  assert.equal(session.canCreateInvitation(), true)
  assert.ok(await session.getToken())
  session.stop()
})

test('bootstrap reports an expired UCC session after a login redirect', async () => {
  const session = createDoctorSession({
    fetchImpl: async () => {
      const response = new Response('<html>login</html>', {
        status: 200,
        headers: { 'Content-Type': 'text/html' },
      })
      Object.defineProperty(response, 'redirected', { value: true })
      return response
    },
  })

  await assert.rejects(
    () => session.start(),
    /UCC 登入工作階段已失效，請重新登入/,
  )
})

test('bootstrap reports an expired UCC session for login HTML returned with 200', async () => {
  const session = createDoctorSession({
    fetchImpl: async () => new Response('<!doctype html><title>Login</title>', {
      status: 200,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    }),
  })

  await assert.rejects(
    () => session.start(),
    /UCC 登入工作階段已失效，請重新登入/,
  )
})

test('bootstrap reports an expired UCC session for non-JSON or missing content type', async () => {
  for (const headers of [
    { 'Content-Type': 'text/plain' },
    {},
  ]) {
    const session = createDoctorSession({
      fetchImpl: async () => new Response('{"access_token":"not-trusted"}', {
        status: 200,
        headers,
      }),
    })

    await assert.rejects(
      () => session.start(),
      /UCC 登入工作階段已失效，請重新登入/,
    )
  }
})

test('bootstrap reports an expired UCC session for malformed JSON', async () => {
  const session = createDoctorSession({
    fetchImpl: async () => new Response('<not-json>', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  })

  await assert.rejects(
    () => session.start(),
    /UCC 登入工作階段已失效，請重新登入/,
  )
})

test('bootstrap reports an expired UCC session for 401 and 403', async () => {
  for (const status of [401, 403]) {
    const session = createDoctorSession({
      fetchImpl: async () => new Response(JSON.stringify({ detail: 'unauthorized' }), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    })

    await assert.rejects(
      () => session.start(),
      /UCC 登入工作階段已失效，請重新登入/,
    )
  }
})

test('bootstrap keeps a distinct error for valid JSON missing an access token', async () => {
  const session = createDoctorSession({
    fetchImpl: async () => new Response(JSON.stringify({ csrf_token: 'csrf' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  })

  await assert.rejects(
    () => session.start(),
    /UCC Bootstrap 未回傳 access token/,
  )
})

test('doctor dashboard bootstraps without an encounter and cannot create an invitation', async () => {
  const calls = []
  const session = createDoctorSession({
    locationLike: { search: '' },
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options })
      return new Response(JSON.stringify({
        access_token: jwt(Math.floor(Date.now() / 1000) + 300),
        csrf_token: 'csrf-dashboard',
        encounter: null,
        capabilities: {
          has_encounter: false,
          can_create_invitation: false,
        },
        scopes: ['consultation:read', 'rules:read'],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    },
  })

  await session.start()
  assert.equal(calls[0].url, '/AiConsult/Bootstrap')
  assert.equal(session.hasEncounter(), false)
  assert.equal(session.hasScope('consultation:read'), true)
  assert.equal(session.hasScope('rules:read'), true)
  assert.equal(session.canCreateInvitation(), false)
  await assert.rejects(
    () => session.createInvitation('999'),
    /B\./,
  )
  assert.equal(calls.length, 1, 'an encounter-free dashboard must not POST an invitation')
  session.stop()
})

test('invitation creation uses UCC antiforgery contract', async () => {
  const calls = []
  const session = createDoctorSession({
    locationLike: { search: '?regSno=321' },
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options })
      const body = url.includes('Bootstrap')
        ? {
            access_token: jwt(Math.floor(Date.now() / 1000) + 300),
            csrf_token: 'csrf-1',
            encounter: { reg_sno: 321 },
          }
        : { invite_id: 'i-1', public_url: 'https://patient.test/#token=x' }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    },
  })

  await session.start()
  assert.equal(session.canCreateInvitation(), true)
  await session.createInvitation()
  assert.equal(calls[1].url, '/AiConsult/Invitations')
  assert.equal(calls[1].options.headers.RequestVerificationToken, 'csrf-1')
  assert.deepEqual(JSON.parse(calls[1].options.body), { regSno: 321 })
  session.stop()
})

test('invitation capability is bound to bootstrap encounter, not browser JWT scope', async () => {
  const session = createDoctorSession({
    locationLike: { search: '?regSno=321' },
    fetchImpl: async () => new Response(JSON.stringify({
      access_token: jwt(Math.floor(Date.now() / 1000) + 300),
      csrf_token: 'csrf-1',
      scopes: ['consultation:read', 'invite:create'],
      encounter: { reg_sno: 999 },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
  })

  await session.start()
  assert.equal(session.canCreateInvitation(), false)
  session.stop()
})
