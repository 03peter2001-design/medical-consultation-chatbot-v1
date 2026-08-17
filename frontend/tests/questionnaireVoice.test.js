import assert from 'node:assert/strict'
import test from 'node:test'

import { interpretQuestionnaireVoice } from '../src/services/questionnaireVoice.js'

test('maps one exact spoken choice and keeps confirmation pending', () => {
  const result = interpretQuestionnaireVoice(
    {
      kind: 'choice',
      multiple: false,
      options: ['男性', '女性'],
      allow_other: true,
    },
    '我的答案是女性。',
  )

  assert.equal(result.status, 'mapped')
  assert.deepEqual(result.selectedOptions, ['女性'])
})

test('maps multiple exact spoken choices separated by conjunctions', () => {
  const result = interpretQuestionnaireVoice(
    {
      kind: 'choice',
      multiple: true,
      options: ['噁心', '嘔吐', '畏光'],
      exclusive_options: [],
      allow_other: true,
    },
    '噁心和嘔吐',
  )

  assert.equal(result.status, 'mapped')
  assert.deepEqual(result.selectedOptions, ['噁心', '嘔吐'])
})

test('does not combine an exclusive option with other spoken choices', () => {
  const result = interpretQuestionnaireVoice(
    {
      kind: 'choice',
      multiple: true,
      options: ['噁心', '以上皆無'],
      exclusive_options: ['以上皆無'],
      allow_other: false,
    },
    '噁心和以上皆無',
  )

  assert.equal(result.status, 'unresolved')
})

test('preserves unmatched speech as other only when the question permits it', () => {
  const allowed = interpretQuestionnaireVoice(
    {
      kind: 'choice',
      multiple: false,
      options: ['左側', '右側'],
      allow_other: true,
    },
    '靠近後腦勺',
  )
  const denied = interpretQuestionnaireVoice(
    {
      kind: 'choice',
      multiple: false,
      options: ['左側', '右側'],
      allow_other: false,
    },
    '靠近後腦勺',
  )

  assert.equal(allowed.status, 'other')
  assert.equal(allowed.otherText, '靠近後腦勺')
  assert.equal(denied.status, 'unresolved')
})

test('maps duration quick options and numeric approved units', () => {
  const spec = {
    kind: 'duration',
    quick_options: ['今天', '1週前'],
    units: ['分鐘前', '小時前', '天前'],
    allow_other: true,
  }

  assert.equal(
    interpretQuestionnaireVoice(spec, '1週前。').quickOption,
    '1週前',
  )
  assert.deepEqual(
    interpretQuestionnaireVoice(spec, '3 天前'),
    {
      status: 'mapped',
      kind: 'duration',
      durationNumber: '3',
      durationUnit: '天前',
      transcript: '3 天前',
    },
  )
})

test('maps spoken Taigi labels back to canonical values', () => {
  const choice = interpretQuestionnaireVoice(
    {
      kind: 'choice',
      multiple: false,
      options: ['沒有，從未抽菸'],
      option_labels: { '沒有，從未抽菸': '無，毋捌食薰' },
      allow_other: false,
    },
    '我揀無，毋捌食薰',
  )
  assert.deepEqual(choice.selectedOptions, ['沒有，從未抽菸'])

  const duration = interpretQuestionnaireVoice(
    {
      kind: 'duration',
      quick_options: [],
      units: ['天前'],
      unit_labels: { 天前: '工進前' },
      allow_other: false,
    },
    '3工進前',
  )
  assert.equal(duration.durationNumber, '3')
  assert.equal(duration.durationUnit, '天前')
})

test('maps explicit Gregorian and ROC dates to ISO', () => {
  const spec = { kind: 'date' }
  const options = { maxDate: '2026-08-10' }

  assert.equal(
    interpretQuestionnaireVoice(spec, '1990年1月2日', options).dateValue,
    '1990-01-02',
  )
  assert.equal(
    interpretQuestionnaireVoice(spec, '民國79年1月2日', options).dateValue,
    '1990-01-02',
  )
  assert.equal(
    interpretQuestionnaireVoice(spec, '1896年8月10日', options).dateValue,
    '1896-08-10',
  )
})

test('rejects invalid, future, and over-130-year voice dates', () => {
  const spec = { kind: 'date' }
  const options = { maxDate: '2026-08-10' }

  assert.equal(
    interpretQuestionnaireVoice(spec, '2025年2月29日', options).status,
    'unresolved',
  )
  assert.equal(
    interpretQuestionnaireVoice(spec, '2027年1月1日', options).status,
    'unresolved',
  )
  assert.equal(
    interpretQuestionnaireVoice(spec, '1895年8月9日', options).status,
    'unresolved',
  )
})
