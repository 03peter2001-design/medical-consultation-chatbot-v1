import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { splitStructuredNote } from '../src/services/structuredNote.js'

test('moves the EMR section out while preserving clinical decisions', () => {
  const sections = splitStructuredNote(`【病歷摘要 EMR】
58歲男性，活動時胸悶。

【初步鑑別診斷（前3項最可能）】
1. 急性冠心症

【理學檢查建議】
- 生命徵象`)

  assert.equal(sections.emrSummary, '58歲男性，活動時胸悶。')
  assert.doesNotMatch(sections.clinicalDecision, /病歷摘要 EMR/)
  assert.match(sections.clinicalDecision, /初步鑑別診斷/)
  assert.match(sections.clinicalDecision, /理學檢查建議/)
})

test('keeps the full report when no EMR heading exists', () => {
  const text = '【初步鑑別診斷】\n1. 急性冠心症'

  assert.deepEqual(splitStructuredNote(text), {
    emrSummary: '',
    clinicalDecision: text,
  })
})

test('preloaded report moves EMR to the patient card and keeps the bottom report', () => {
  const doctorView = readFileSync(
    new URL('../src/views/DoctorView.vue', import.meta.url),
    'utf8',
  )
  const structuredReport = readFileSync(
    new URL('../src/components/StructuredReport.vue', import.meta.url),
    'utf8',
  )

  assert.match(
    doctorView,
    /pushStructured\(record\.structured_note, record\.structured_sources, true\)/,
  )
  assert.match(doctorView, /:hide-emr="item\.hideEmr"/)
  assert.match(
    structuredReport,
    /🩺 結構化病歷分析（EMR \+ 臨床決策）/,
  )
  assert.match(structuredReport, /splitStructuredNote\(props\.text\)\.clinicalDecision/)
})
