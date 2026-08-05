import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildDiseasePayload,
  getDiseaseChanges,
  hasInvalidSafetyLinks,
  hasInvalidWeights,
  hasSafetyGroup,
} from '../src/composables/diseaseGovernance.js'

const safetyGroup = {
  label: '高風險胸痛',
  original_label: 'high_risk_chest',
  rules: [{ code: 'chest_syncope' }, { code: 'chest_dyspnea' }],
}

function profile(overrides = {}) {
  return {
    id: 'acute_coronary_syndrome',
    name: '急性冠心症',
    must_not_miss: true,
    safety_rule_codes: ['chest_syncope', 'chest_dyspnea'],
    clues: [
      {
        fact: 'chest_pressure',
        status: 'present',
        direction: 'support',
        weight: 2,
      },
    ],
    ...overrides,
  }
}

test('reports clue and safety-link changes without mutating either route', () => {
  const deployed = { profiles: [profile()] }
  const draft = {
    profiles: [
      profile({
        safety_rule_codes: [],
        clues: [
          {
            fact: 'chest_pressure',
            status: 'present',
            direction: 'support',
            weight: 3,
          },
          {
            fact: 'diaphoresis',
            status: 'present',
            direction: 'support',
            weight: 1,
          },
        ],
      }),
    ],
  }
  const originalDraft = structuredClone(draft)

  const changes = getDiseaseChanges(draft, deployed, [safetyGroup])

  assert.deepEqual(
    changes.map((change) => [change.action, change.fact]),
    [
      ['updated', 'chest_pressure'],
      ['added', 'diaphoresis'],
      ['safety_removed', undefined],
    ],
  )
  assert.deepEqual(draft, originalDraft)
})

test('validates weight bounds and must-not-miss safety invariants', () => {
  assert.equal(hasInvalidWeights({ profiles: [profile()] }, 5), false)
  assert.equal(
    hasInvalidWeights(
      { profiles: [profile({ clues: [{ fact: 'x', weight: 1.5 }] })] },
      5,
    ),
    true,
  )
  assert.equal(hasInvalidSafetyLinks({ profiles: [profile()] }), false)
  assert.equal(
    hasInvalidSafetyLinks({
      profiles: [profile({ safety_rule_codes: [] })],
    }),
    true,
  )
  assert.equal(hasSafetyGroup(profile(), safetyGroup), true)
})

test('builds the disease update API payload with normalized audit fields', () => {
  const route = { profiles: [profile()] }
  const payload = buildDiseasePayload({
    route,
    sessionId: 'session-42',
    expectedRevision: 7,
    confirmation: '  CONFIRM  ',
    changeNote: '  clinical review  ',
    reviewer: '  王醫師  ',
  })

  assert.deepEqual(payload, {
    session_id: 'session-42',
    expected_revision: 7,
    confirmation: 'CONFIRM',
    change_note: 'clinical review',
    reviewer: '王醫師',
    profiles: [
      {
        id: 'acute_coronary_syndrome',
        safety_rule_codes: ['chest_syncope', 'chest_dyspnea'],
        clues: [
          {
            fact: 'chest_pressure',
            status: 'present',
            direction: 'support',
            weight: 2,
          },
        ],
      },
    ],
  })
  assert.notEqual(payload.profiles[0].clues, route.profiles[0].clues)
})
