import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  formatEmrSummary,
  parseEmrFields,
  parseStructuredNoteBlocks,
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

test('parses clinician note fields without leaking later sections into PI', () => {
  const fields = parseEmrFields(`【病歷摘要 EMR】
CC（主訴）：
Exertional chest pain.

PI（現病史）：
Pain began two days ago and worsens with activity.

PH（過去病史）：
Hypertension.

Meds（用藥）：
Daily antihypertensive medication.

Allergy（過敏史）：
No known drug allergies.

【初步鑑別診斷】
Acute coronary syndrome`)

  assert.deepEqual(fields, {
    cc: 'Exertional chest pain.',
    pi: 'Pain began two days ago and worsens with activity.',
    ph: 'Hypertension.',
    meds: 'Daily antihypertensive medication.',
    allergy: 'No known drug allergies.',
  })
  assert.doesNotMatch(fields.pi, /Hypertension|medication|allergies/)
})

test('keeps seven-field English medical history sections isolated', () => {
  const fields = parseEmrFields(`【病歷摘要 EMR】
Chief Complaint:
A 36-year-old female patient presents with fever for two days.

Present Illness:
The fever is associated with chills.

Past History:
Not provided

Meds（用藥）：
Not provided

Allergy History:
The patient denies any known drug allergies.

Personal History:
The patient reports a history of smoking and recent sick contact.

Family History:
Family history was not provided.

【初步鑑別診斷】
Viral infection`)

  assert.deepEqual(fields, {
    cc: 'A 36-year-old female patient presents with fever for two days.',
    pi: 'The fever is associated with chills.',
    ph: 'Not provided',
    meds: 'Not provided',
    allergy: 'The patient denies any known drug allergies.',
    personal:
      'The patient reports a history of smoking and recent sick contact.',
    family: 'Family history was not provided.',
  })
  assert.doesNotMatch(fields.allergy, /Personal History|Family History|smoking/)
})

test('parses the six clinical questions into prominent block data', () => {
  const report = parseStructuredNoteBlocks(`【病歷摘要 EMR】
CC: Chest pain

【初步鑑別診斷（前3項最可能）】
1. Acute coronary syndrome

【防漏診鑑別 — 5個絕對不能漏掉的隱形殺手】
1. Aortic dissection

【理學檢查建議】
1. Bilateral blood pressure

【檢驗建議（抽血／驗尿）】
1. High-sensitivity troponin

【影像學決策】
1. Chest radiograph

模型：gemini-test｜Prompt：synthetic-v1

本分析尚未經醫師確認。`)

  assert.deepEqual(
    report.sections.map(({ key, title }) => ({ key, title })),
    [
      { key: 'emr', title: '病歷摘要 EMR' },
      { key: 'differential', title: '初步鑑別診斷' },
      { key: 'must-not-miss', title: '防漏診鑑別' },
      { key: 'physical', title: '理學檢查' },
      { key: 'laboratory', title: '檢驗（抽血／驗尿）' },
      { key: 'imaging', title: '影像學決策' },
    ],
  )
  assert.match(report.sections[2].question, /絕對不能漏掉/)
  assert.equal(report.sections[4].content, '1. High-sensitivity troponin')
  assert.match(report.footer, /synthetic-v1/)
  assert.match(report.footer, /尚未經醫師確認/)
})

test('preloaded report keeps EMR and clinical question cards together near the patient header', () => {
  const doctorView = readFileSync(
    new URL('../src/views/DoctorView.vue', import.meta.url),
    'utf8',
  )
  const structuredReport = readFileSync(
    new URL('../src/components/StructuredReport.vue', import.meta.url),
    'utf8',
  )
  const patientRecordCard = readFileSync(
    new URL('../src/components/PatientRecordCard.vue', import.meta.url),
    'utf8',
  )
  const terminologyCode = readFileSync(
    new URL('../src/components/TerminologyCode.vue', import.meta.url),
    'utf8',
  )

  assert.doesNotMatch(
    doctorView,
    /pushStructured\(record\.structured_note, record\.structured_sources, true\)/,
  )
  assert.match(doctorView, /:hide-emr="item\.hideEmr"/)
  assert.match(patientRecordCard, /class="patient-summary-report"/)
  assert.match(patientRecordCard, /:text="record\.structured_note"/)
  assert.match(patientRecordCard, /hide-emr/)
  assert.match(
    structuredReport,
    /六段式臨床問題總結/,
  )
  assert.match(structuredReport, /splitStructuredNote\(props\.text\)\.clinicalDecision/)
  assert.match(structuredReport, /class="question-grid"/)
  assert.match(structuredReport, /class="question-card"/)
  assert.match(structuredReport, /section\.question/)
  assert.match(structuredReport, /AI 臨床決策/)
  assert.match(doctorView, /檢驗（抽血／驗尿） \/ 影像學決策/)
  assert.doesNotMatch(doctorView, /檢驗建議/)
  assert.match(terminologyCode, /AI 編碼結果，待醫師確認/)
  assert.doesNotMatch(terminologyCode, /AI 建議編碼/)
})
