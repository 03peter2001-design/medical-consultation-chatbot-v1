import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

import { formatEmrSummary } from '../packages/shared/src/services/structuredNote.js'

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
