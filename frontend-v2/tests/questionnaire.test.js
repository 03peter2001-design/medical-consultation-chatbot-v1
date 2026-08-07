import assert from 'node:assert/strict'
import test from 'node:test'

import {
  composeQuestionAnswer,
  toggleQuestionOption,
} from '../packages/shared/src/services/questionnaire.js'

test('selected choice can be cancelled', () => {
  const spec = { multiple: false, exclusive_options: [] }
  assert.deepEqual(toggleQuestionOption(['男性'], '男性', spec), [])
})

test('other text replaces stale selected options', () => {
  const answer = composeQuestionAnswer(
    { kind: 'choice', multiple: true },
    {
      selectedOptions: ['鈍痛'],
      otherText: '偶爾抽痛',
    },
  )

  assert.equal(answer, '其他：偶爾抽痛')
})
