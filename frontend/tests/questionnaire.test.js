import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  composeQuestionAnswer,
  isQuestionAnswerReady,
  toggleQuestionOption,
} from '../src/services/questionnaire.js'

const questionnaireControl = readFileSync(
  new URL('../src/components/QuestionnaireControl.vue', import.meta.url),
  'utf8',
)

test('single choice replaces the previous selection', () => {
  const spec = { multiple: false, exclusive_options: [] }
  assert.deepEqual(toggleQuestionOption(['男性'], '女性', spec), ['女性'])
})

test('selected choice can be cancelled', () => {
  const spec = { multiple: false, exclusive_options: [] }
  assert.deepEqual(toggleQuestionOption(['男性'], '男性', spec), [])
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

test('choice other text replaces stale selected options', () => {
  const answer = composeQuestionAnswer(
    { kind: 'choice', multiple: true },
    {
      selectedOptions: ['鈍痛'],
      otherText: '偶爾抽痛',
    },
  )
  assert.equal(answer, '其他：偶爾抽痛')
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

test('renders localized labels while submitting canonical values', () => {
  assert.match(questionnaireControl, /localizedLabel\(spec\.option_labels, option\)/)
  assert.match(questionnaireControl, /localizedLabel\(spec\.quick_option_labels, option\)/)
  assert.match(questionnaireControl, /localizedLabel\(spec\.unit_labels, unit\)/)
  assert.equal(
    composeQuestionAnswer(
      {
        kind: 'choice',
        options: ['沒有，從未抽菸'],
        option_labels: { '沒有，從未抽菸': '無，毋捌食薰' },
      },
      { selectedOptions: ['沒有，從未抽菸'] },
    ),
    '沒有，從未抽菸',
  )
})
