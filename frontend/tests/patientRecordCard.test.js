import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const component = readFileSync(
  new URL('../src/components/PatientRecordCard.vue', import.meta.url),
  'utf8',
)

test('structured EMR summary is prominent and directly follows the complaint', () => {
  const complaintIndex = component.indexOf('class="complaint"')
  const summaryIndex = component.indexOf('class="emr-summary"')
  const nextDashboardSectionIndex = component.indexOf('class="red-flag-banner"')

  assert.ok(complaintIndex >= 0)
  assert.ok(summaryIndex > complaintIndex)
  assert.ok(nextDashboardSectionIndex > summaryIndex)
  assert.match(component, /<small>結構化病歷重點<\/small>/)
  assert.match(component, /<h3 id="emr-summary-title">病歷摘要 EMR<\/h3>/)
  assert.equal(component.match(/record\.report/g)?.length, 1)
})
