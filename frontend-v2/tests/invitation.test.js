import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clearInvitationToken,
  readInvitationToken,
} from '../packages/shared/src/auth/patientInvitation.js'

test('reads invitation tokens from supported fragment formats', () => {
  assert.equal(readInvitationToken('#token=abc-123'), 'abc-123')
  assert.equal(readInvitationToken('#/invite?token=abc-123'), 'abc-123')
  assert.equal(readInvitationToken('#invite=abc-123'), 'abc-123')
  assert.equal(readInvitationToken('#abc-123'), 'abc-123')
  assert.equal(readInvitationToken(''), '')
})

test('clears the fragment without changing path or query', () => {
  let replaced = ''
  clearInvitationToken(
    { pathname: '/start', search: '?lang=zh-TW' },
    { replaceState: (_state, _title, url) => { replaced = url } },
  )
  assert.equal(replaced, '/start?lang=zh-TW')
})
