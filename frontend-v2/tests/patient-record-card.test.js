import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

import {
  formatEmrSummary,
  parseEmrFields,
} from '../packages/shared/src/services/structuredNote.js'

const root = path.resolve(import.meta.dirname, '..')

test('EMR card keeps its original structured record labels', async () => {
  const component = await readFile(
    path.join(root, 'packages/shared/src/components/PatientRecordCard.vue'),
    'utf8',
  )

  assert.match(component, /<small>結構化病歷重點<\/small>/)
  assert.match(
    component,
    /<h3 id="emr-summary-title">病歷摘要 EMR<\/h3>/,
  )
})

test('patient basics appear before two sentences about other EMR history', () => {
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

test('doctor record exposes reviewed FHIR summary with an explicit capability gate', async () => {
  const component = await readFile(
    path.join(root, 'packages/shared/src/components/PatientRecordCard.vue'),
    'utf8',
  )
  const physicianSummary = await readFile(
    path.join(root, 'packages/shared/src/components/PhysicianSummary.vue'),
    'utf8',
  )
  const doctorView = await readFile(
    path.join(root, 'apps/doctor/src/views/DoctorView.vue'),
    'utf8',
  )

  assert.match(component, /record\.fhir_summary_sections/)
  assert.match(component, /:can-write-fhir="canWriteFhir"/)
  assert.match(physicianSummary, /props\.canWriteFhir/)
  assert.match(physicianSummary, /!hasFhirContext/)
  assert.match(physicianSummary, /alreadySubmitted/)
  assert.match(physicianSummary, /services\/doctorBackend\.js/)
  assert.match(
    doctorView,
    /doctorSession\.hasScope\('consultation:fhir-write'\)/,
  )
  assert.match(doctorView, /:can-write-fhir="canWriteFhir"/)
})

test('seven-section EMR parser keeps multiline clinician summary fields separate', () => {
  assert.deepEqual(
    parseEmrFields(`【病歷摘要 EMR】
Chief Complaint: Chest pressure
Present Illness: Started today
with sweating
Past History: Hypertension
Drug History: Aspirin
Allergy History: NKDA
Personal History: Never smoked
Family History: Father had CAD

【初步鑑別診斷】
ACS`),
    {
      cc: 'Chest pressure',
      pi: 'Started today\nwith sweating',
      ph: 'Hypertension',
      meds: 'Aspirin',
      allergy: 'NKDA',
      personal: 'Never smoked',
      family: 'Father had CAD',
    },
  )
})
