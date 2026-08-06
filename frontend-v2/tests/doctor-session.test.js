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
