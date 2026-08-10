import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  formatEmrSummary,
  splitStructuredNote,
} from '../src/services/structuredNote.js'

test('formats patient basics before two sentences about other EMR history', () => {
  const summary = formatEmrSummary(
    {
      patient_data: {
        age: '58',
        gender: '男',
        reason: '走路時胸口壓迫',
        onset: '3小時前',
      },
    },
    '有高血壓病史，目前規則服藥。無已知藥物過敏。第三句不應顯示。',
  )

  assert.equal(
    summary,
    '58歲男性｜症狀：走路時胸口壓迫｜持續時間：3小時前\n有高血壓病史，目前規則服藥。無已知藥物過敏。',
  )
})

test('keeps an already formatted EMR summary without duplicating identity', () => {
  const summary = formatEmrSummary(
    {
      patient_data: {
        age: '58',
        gender: '男',
        reason: '走路時胸口壓迫',
        onset: '3小時前',
      },
    },
    '58歲男性｜症狀：走路時胸口壓迫｜持續時間：3小時前\n有高血壓病史。無已知藥物過敏。',
  )

  assert.equal(
    summary,
    '58歲男性｜症狀：走路時胸口壓迫｜持續時間：3小時前\n有高血壓病史。無已知藥物過敏。',
  )
})

test('moves the EMR section out while preserving clinical decisions', () => {
  const sections = splitStructuredNote(`【病歷摘要 EMR】
58歲男性，活動時胸悶。

【初步鑑別診斷（前3項最可能）】
1. 急性冠心症

【理學檢查】
- 生命徵象`)

  assert.equal(sections.emrSummary, '58歲男性，活動時胸悶。')
  assert.doesNotMatch(sections.clinicalDecision, /病歷摘要 EMR/)
  assert.match(sections.clinicalDecision, /初步鑑別診斷/)
  assert.match(sections.clinicalDecision, /【理學檢查】/)
  assert.doesNotMatch(sections.clinicalDecision, /建議/)
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
  const terminologyCode = readFileSync(
    new URL('../src/components/TerminologyCode.vue', import.meta.url),
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
  assert.match(doctorView, /檢驗（抽血／驗尿） \/ 影像學決策/)
  assert.doesNotMatch(doctorView, /檢驗建議/)
  assert.match(terminologyCode, /AI 編碼結果，待醫師確認/)
  assert.doesNotMatch(terminologyCode, /AI 建議編碼/)
})
