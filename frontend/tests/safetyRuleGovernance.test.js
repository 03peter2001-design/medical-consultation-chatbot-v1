import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope, reactive } from 'vue'

import {
  buildSafetyGroup,
  buildSafetyPublishPayload,
  cloneSafetyGroups,
  getChangedSafetyGroups,
  useSafetyRuleGovernance,
} from '../src/composables/safetyRuleGovernance.js'

const deployedGroups = [
  {
    original_label: 'vision_warning',
    label: '視力警訊',
    possible_conditions: ['中風'],
    categories: ['headache'],
    rules: [
      {
        code: 'vision_loss',
        kind: 'structured',
        scope: 'route',
        route: 'headache',
        level: 'stop',
        when: {
          age_gte: 50,
          any_findings: ['vision_loss', 'diplopia'],
        },
      },
    ],
  },
]

test('clones deployed groups into isolated editor fields and rebuilds them', () => {
  const drafts = cloneSafetyGroups(deployedGroups)

  assert.notEqual(drafts, deployedGroups)
  assert.notEqual(drafts[0].rules, deployedGroups[0].rules)
  assert.equal(drafts[0].conditionsText, '中風')
  assert.equal(drafts[0].rules[0].featureMode, 'any_findings')
  assert.deepEqual(drafts[0].rules[0].selectedFeatures, [
    'vision_loss',
    'diplopia',
  ])
  assert.deepEqual(buildSafetyGroup(drafts[0]), deployedGroups[0])
})

test('detects meaningful draft changes and treats invalid JSON as changed', () => {
  const drafts = cloneSafetyGroups(deployedGroups)
  assert.deepEqual(getChangedSafetyGroups(drafts, deployedGroups), [])

  drafts[0].rules[0].selectedFeatures.push('ataxia')
  assert.deepEqual(getChangedSafetyGroups(drafts, deployedGroups), [drafts[0]])

  drafts[0].rules[0].conditionText = '{broken'
  assert.deepEqual(getChangedSafetyGroups(drafts, deployedGroups), [drafts[0]])
  assert.throws(
    () => buildSafetyGroup(drafts[0]),
    /vision_loss 的 JSON 條件格式錯誤/,
  )
})

test('builds a normalized safety publish payload without editor-only fields', () => {
  const drafts = cloneSafetyGroups(deployedGroups)
  drafts[0].conditionsText = ' 中風 \n\n 急性青光眼 '

  const payload = buildSafetyPublishPayload({
    groups: drafts,
    sessionId: 'session-42',
    expectedRevision: 'revision-7',
    confirmation: '  CONFIRM  ',
    changeNote: '  clinical review  ',
  })

  assert.equal(payload.confirmation, 'CONFIRM')
  assert.equal(payload.change_note, 'clinical review')
  assert.deepEqual(payload.safety_groups[0].possible_conditions, [
    '中風',
    '急性青光眼',
  ])
  assert.equal('conditionsText' in payload.safety_groups[0], false)
  assert.equal('conditionText' in payload.safety_groups[0].rules[0], false)
})

test('resets feature filters whenever a group is selected again', () => {
  const scope = effectScope()

  try {
    scope.run(() => {
      const governance = useSafetyRuleGovernance(
        reactive({
          rulebook: {
            safety_groups: deployedGroups,
            confirmation_text: 'CONFIRM',
          },
          authorized: true,
        }),
        () => {},
      )

      governance.featureSearch.value = 'vision'
      governance.activeFeatureCategory.value = 'headache'
      governance.selectGroup('vision_warning')

      assert.equal(governance.activeGroupId.value, 'vision_warning')
      assert.equal(governance.featureSearch.value, '')
      assert.equal(governance.activeFeatureCategory.value, 'all')

      governance.featureSearch.value = 'diplopia'
      governance.activeFeatureCategory.value = 'safety'
      governance.selectGroup('vision_warning')

      assert.equal(governance.featureSearch.value, '')
      assert.equal(governance.activeFeatureCategory.value, 'all')
    })
  } finally {
    scope.stop()
  }
})
