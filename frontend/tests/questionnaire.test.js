import assert from 'node:assert/strict'
import test from 'node:test'

import {
  composeQuestionAnswer,
  isQuestionAnswerReady,
  toggleQuestionOption,
} from '../src/services/questionnaire.js'

test('single choice replaces the previous selection', () => {
  const spec = { multiple: false, exclusive_options: [] }
  assert.deepEqual(toggleQuestionOption(['男性'], '女性', spec), ['女性'])
})

test('exclusive choice clears multi-select answers', () => {
  const spec = {
    multiple: true,
    exclusive_options: ['以上皆無'],
  }
  assert.deepEqual(
    toggleQuestionOption(['噁心', '發燒'], '以上皆無', spec),
    ['以上皆無'],
  )
  assert.deepEqual(
    toggleQuestionOption(['以上皆無'], '噁心', spec),
    ['噁心'],
  )
})

test('choice answer preserves an other free-text answer', () => {
  const answer = composeQuestionAnswer(
    { kind: 'choice', multiple: true },
    {
      selectedOptions: ['鈍痛'],
      otherText: '偶爾抽痛',
    },
  )
  assert.equal(answer, '鈍痛、其他：偶爾抽痛')
})

test('empty choice is not ready', () => {
  assert.equal(
    isQuestionAnswerReady(
      { kind: 'choice', multiple: true },
      { selectedOptions: [], otherText: '' },
    ),
    false,
  )
})

test('duration shortcut is submitted directly', () => {
  const answer = composeQuestionAnswer(
    { kind: 'duration', units: ['分鐘前', '小時前'] },
    { quickOption: '1週前' },
  )
  assert.equal(answer, '1週前')
})

test('custom duration combines number and selected unit', () => {
  const answer = composeQuestionAnswer(
    { kind: 'duration', units: ['分鐘前', '小時前', '個月前'] },
    {
      durationNumber: '3',
      durationUnit: '個月前',
    },
  )
  assert.equal(answer, '3個月前')
})

test('duration free text takes precedence', () => {
  const answer = composeQuestionAnswer(
    { kind: 'duration', units: ['小時前'] },
    {
      quickOption: '1小時前',
      durationNumber: '2',
      durationUnit: '小時前',
      otherText: '昨天晚上開始',
    },
  )
  assert.equal(answer, '昨天晚上開始')
})
