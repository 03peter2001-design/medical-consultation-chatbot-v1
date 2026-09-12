import assert from 'node:assert/strict'
import test from 'node:test'
import { useInvitations } from '../apps/doctor/src/invitations.js'
import { api, setAuthProvider } from '../packages/shared/src/services/backend.js'

test('invitation requests use doctor authentication, no-store, encoded IDs and POST mutations', async () => {
  const original = globalThis.fetch
  const calls = []
  setAuthProvider({ getToken: async () => 'synthetic-token' })
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify({ items: [], total: 0 }), { headers: { 'Content-Type': 'application/json' } })
  }
  try {
    await api.listInvitations({ status: 'expired', limit: 20, offset: 40 })
    await api.cancelInvitation('synthetic/id')
    await api.reissueInvitation('synthetic/id')
    assert.match(calls[0].url, /\/v1\/doctor\/invitations\?limit=20&offset=40&status=expired$/)
    assert.match(calls[1].url, /synthetic%2Fid\/cancel$/)
    assert.match(calls[2].url, /synthetic%2Fid\/reissue$/)
    for (const { options } of calls) {
      assert.equal(options.cache, 'no-store')
      assert.equal(options.headers.get('Authorization'), 'Bearer synthetic-token')
    }
    assert.equal(calls[1].options.method, 'POST')
    assert.equal(calls[2].options.method, 'POST')
  } finally { globalThis.fetch = original; setAuthProvider(null) }
})

test('changing filters ignores out-of-order list responses and preserves pagination', async () => {
  const pending = []
  const model = useInvitations({ listInvitations: (options) => new Promise((resolve) => pending.push({ options, resolve })) })
  const first = model.load(20)
  model.status.value = 'consumed'
  const second = model.load(0)
  pending[1].resolve({ items: [{ invite_id: 'latest' }], total: 21 })
  await second
  pending[0].resolve({ items: [{ invite_id: 'stale' }], total: 1 })
  await first
  assert.equal(model.items.value[0].invite_id, 'latest')
  assert.equal(model.offset.value, 0)
  assert.equal(model.hasNext.value, true)
  assert.equal(pending[1].options.status, 'consumed')
})

test('reissue is guarded against double submit, refreshes list and only retains the new code', async () => {
  let finish
  let calls = 0
  const model = useInvitations({
    listInvitations: async () => ({ items: [{ invite_id: 'new' }], total: 1 }),
    reissueInvitation: () => { calls++; return new Promise((resolve) => { finish = resolve }) },
  })
  const operation = model.act('reissue', { invite_id: 'old' })
  assert.equal(await model.act('reissue', { invite_id: 'old' }), false)
  finish({ invite_id: 'new', public_url: 'https://synthetic.invalid/#token=synthetic' })
  assert.equal(await operation, true)
  assert.equal(calls, 1)
  assert.equal(model.issued.value.invite_id, 'new')
  await model.load()
  assert.equal(model.issued.value, null)
})

test('ambiguous mutation failure refreshes state without resending or showing an old code', async () => {
  let calls = 0
  const model = useInvitations({
    cancelInvitation: async () => { calls++; throw new Error('network failure') },
    listInvitations: async () => ({ items: [{ invite_id: 'old', status: 'revoked' }], total: 1 }),
  })
  model.issued.value = { public_url: 'synthetic-old-code' }
  assert.equal(await model.act('cancel', { invite_id: 'old' }), false)
  assert.equal(calls, 1)
  assert.equal(model.items.value[0].status, 'revoked')
  assert.equal(model.issued.value, null)
  assert.match(model.error.value, /操作未能確認/)
})

test('unmount ignores pending list results', async () => {
  let finish
  const model = useInvitations({ listInvitations: () => new Promise((resolve) => { finish = resolve }) })
  const request = model.load()
  model.dispose()
  finish({ items: [{ invite_id: 'late' }], total: 1 })
  await request
  assert.deepEqual(model.items.value, [])
})
