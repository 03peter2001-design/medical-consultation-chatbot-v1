import assert from 'node:assert/strict'
import test from 'node:test'

import {
  areAllSummaryRowsConfirmed,
  buildFhirCompositionRequest,
  confirmEditableSummaryRows,
  createEditableSummaryRows,
  updateEditableSummaryRow,
} from '../src/services/physicianSummary.js'

test('physician edits invalidate the single whole-record confirmation', () => {
  const sourceRows = [
    {
      key: 'Chief Complaint',
      label: '主訴',
      value: 'Original AI summary',
      source: 'Gemini 彙整 · 待醫師確認',
    },
    {
      key: 'Past History',
      label: '過去病史',
      value: 'No known history',
      source: 'Gemini 彙整 · 待醫師確認',
    },
  ]
  const rows = createEditableSummaryRows(sourceRows)
  const [editableRow] = rows

  assert.equal(editableRow.value, 'Original AI summary')
  assert.equal(editableRow.originalValue, 'Original AI summary')
  assert.equal(editableRow.confirmed, false)

  updateEditableSummaryRow(editableRow, 'Physician-edited summary')
  assert.equal(editableRow.value, 'Physician-edited summary')
  assert.equal(editableRow.confirmed, false)
  assert.equal(confirmEditableSummaryRows(rows), true)
  assert.equal(rows.every((row) => row.confirmed), true)

  updateEditableSummaryRow(editableRow, 'Second edit', rows)
  assert.equal(rows.some((row) => row.confirmed), false)
  assert.equal(sourceRows[0].value, 'Original AI summary')
})

test('the whole record cannot be confirmed when any summary row is empty', () => {
  const rows = createEditableSummaryRows([
    { key: 'Chief Complaint', value: 'Headache' },
    { key: 'Past History', value: 'Initial history' },
  ])

  updateEditableSummaryRow(rows[1], '   ', rows)

  assert.equal(confirmEditableSummaryRows(rows), false)
  assert.equal(rows.some((row) => row.confirmed), false)
  assert.equal(confirmEditableSummaryRows([]), false)
})

test('one action confirms every row and enables the FHIR preview', () => {
  const rows = createEditableSummaryRows([
    { key: 'Chief Complaint', value: 'Headache' },
    { key: 'Past History', value: 'Diabetes' },
  ])

  assert.equal(areAllSummaryRowsConfirmed(rows), false)
  confirmEditableSummaryRows(rows)
  assert.equal(areAllSummaryRowsConfirmed(rows), true)

  updateEditableSummaryRow(rows[0], 'Updated headache', rows)
  assert.equal(areAllSummaryRowsConfirmed(rows), false)
  assert.equal(areAllSummaryRowsConfirmed([]), false)
})

test('FHIR write request contains only the reviewed sections and optimistic version', () => {
  const rows = createEditableSummaryRows([
    { key: 'Chief Complaint', label: '主訴', value: 'Headache' },
    { key: 'Present Illness', label: '現病史', value: 'One hour' },
  ])
  confirmEditableSummaryRows(rows)

  assert.deepEqual(
    buildFhirCompositionRequest(rows, '2026-08-25T00:00:00Z'),
    {
      expected_updated_at: '2026-08-25T00:00:00Z',
      sections: [
        {
          key: 'Chief Complaint',
          label: '主訴',
          value: 'Headache',
          confirmed: true,
        },
        {
          key: 'Present Illness',
          label: '現病史',
          value: 'One hour',
          confirmed: true,
        },
      ],
    },
  )
})
