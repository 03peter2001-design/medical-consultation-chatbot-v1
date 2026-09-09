import assert from 'node:assert/strict'
import test from 'node:test'

import {
  areAllSummaryRowsConfirmed,
  buildFhirCompositionRequest,
  confirmEditableSummaryRow,
  createEditableSummaryRows,
  updateEditableSummaryRow,
} from '../src/services/physicianSummary.js'

test('physician edits are reflected in the shared summary row and require reconfirmation', () => {
  const sourceRows = [
    {
      key: 'Chief Complaint',
      label: '主訴',
      value: 'Original AI summary',
      source: 'Gemini 彙整 · 待醫師確認',
    },
  ]
  const [editableRow] = createEditableSummaryRows(sourceRows)

  assert.equal(editableRow.value, 'Original AI summary')
  assert.equal(editableRow.originalValue, 'Original AI summary')
  assert.equal(editableRow.confirmed, false)

  updateEditableSummaryRow(editableRow, 'Physician-edited summary')
  assert.equal(editableRow.value, 'Physician-edited summary')
  assert.equal(editableRow.confirmed, false)
  assert.equal(confirmEditableSummaryRow(editableRow), true)
  assert.equal(editableRow.confirmed, true)

  updateEditableSummaryRow(editableRow, 'Second edit')
  assert.equal(editableRow.confirmed, false)
  assert.equal(sourceRows[0].value, 'Original AI summary')
})

test('an empty physician summary row cannot be confirmed', () => {
  const [editableRow] = createEditableSummaryRows([
    { key: 'Past History', value: 'Initial history' },
  ])

  updateEditableSummaryRow(editableRow, '   ')

  assert.equal(confirmEditableSummaryRow(editableRow), false)
  assert.equal(editableRow.confirmed, false)
})

test('FHIR preview remains unavailable until every summary row is confirmed', () => {
  const rows = createEditableSummaryRows([
    { key: 'Chief Complaint', value: 'Headache' },
    { key: 'Past History', value: 'Diabetes' },
  ])

  assert.equal(areAllSummaryRowsConfirmed(rows), false)
  confirmEditableSummaryRow(rows[0])
  assert.equal(areAllSummaryRowsConfirmed(rows), false)
  confirmEditableSummaryRow(rows[1])
  assert.equal(areAllSummaryRowsConfirmed(rows), true)

  updateEditableSummaryRow(rows[0], 'Updated headache')
  assert.equal(areAllSummaryRowsConfirmed(rows), false)
  assert.equal(areAllSummaryRowsConfirmed([]), false)
})

test('FHIR write request contains only the reviewed sections and optimistic version', () => {
  const rows = createEditableSummaryRows([
    { key: 'Chief Complaint', label: '主訴', value: 'Headache' },
    { key: 'Present Illness', label: '現病史', value: 'One hour' },
  ])
  rows.forEach(confirmEditableSummaryRow)

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
