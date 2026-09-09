import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const component = readFileSync(
  new URL('../src/components/PatientRecordCard.vue', import.meta.url),
  'utf8',
)
const physicianSummary = readFileSync(
  new URL('../src/components/PhysicianSummary.vue', import.meta.url),
  'utf8',
)
const fhirSubmissionDialog = readFileSync(
  new URL('../src/components/FhirSubmissionDialog.vue', import.meta.url),
  'utf8',
)

test('patient record follows the approved clinical document hierarchy', () => {
  const complaintIndex = component.indexOf('class="complaint"')
  const redFlagIndex = component.indexOf('class="red-flag-banner"')
  const snapshotIndex = component.indexOf('class="snapshot-grid"')
  const reportIndex = component.indexOf('class="patient-summary-report"')
  const summaryIndex = component.indexOf('class="emr-summary"')
  const physicianSummaryIndex = component.indexOf('class="physician-summary"')
  const evidenceIndex = component.indexOf('class="clinical-evidence-disclosure"')

  assert.ok(complaintIndex >= 0)
  assert.ok(redFlagIndex > complaintIndex)
  assert.ok(snapshotIndex > complaintIndex)
  assert.ok(reportIndex > snapshotIndex)
  assert.ok(summaryIndex > reportIndex)
  assert.ok(physicianSummaryIndex > summaryIndex)
  assert.ok(evidenceIndex > physicianSummaryIndex)
  assert.match(component, /出生日期 \{\{ clinical\.identity\.birthDate \}\}/)
  assert.match(
    component,
    /class="identity-highlight identity-demographics"[\s\S]*?<dt>基本資料<\/dt>/,
  )
  assert.match(
    component,
    /class="identity-highlight identity-category"[\s\S]*?<dt>主訴分類<\/dt>/,
  )
  assert.match(
    component,
    /\.identity-meta \.identity-highlight dd \{[\s\S]*?font-size: clamp\(16px,/,
  )
  assert.match(component, /\.identity-meta > \.identity-category \{[\s\S]*?background: #eef9f6/)
  assert.match(
    component,
    /@media \(max-width: 700px\) \{[\s\S]*?\.identity-meta \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\)/,
  )
  assert.match(component, /RAG 病歷／文獻摘要/)
  assert.match(component, /Gemini 生成 · 待醫師確認/)
  assert.match(component, /class="emr-summary-trigger"/)
  assert.match(component, /class="emr-summary-preview"/)
  assert.match(component, /record\.structured_sources\.length.*項來源/s)
  assert.match(component, /\.emr-summary\[open\] \.emr-summary-action svg/)
  assert.match(component, /:rows="physicianSummaryRows"/)
  assert.match(component, /parseEmrFields\(props\.record\.structured_note\)/)
  assert.match(component, /key: 'Drug History'/)
  assert.match(component, /key: 'Allergy History'/)
  assert.match(component, /key: 'Personal History'/)
  assert.match(component, /key: 'Family History'/)
  assert.doesNotMatch(component, /value: props\.record\.summary/)
  assert.match(physicianSummary, /Draft/)
  assert.match(physicianSummary, /v-for="\(row, index\) in editableRows"/)
  assert.match(physicianSummary, /<b>\{\{ row\.key \}\}<\/b>/)
  assert.match(physicianSummary, /class="summary-editor"/)
  assert.match(physicianSummary, /@input="handleSummaryInput\(row, \$event\)"/)
  assert.match(physicianSummary, /@click="confirmRow\(row\)"/)
  assert.match(physicianSummary, /v-if="row\.confirmed"/)
  assert.match(physicianSummary, /送出並儲存至 FHIR/)
  assert.match(physicianSummary, /@click="openFhirSubmissionDialog"/)
  assert.match(physicianSummary, /:disabled="!canOpenSubmission"/)
  assert.match(physicianSummary, /if \(!allRowsConfirmed\.value\)/)
  assert.match(physicianSummary, /api\.createFhirComposition/)
  assert.match(physicianSummary, /<FhirSubmissionDialog/)
  assert.doesNotMatch(
    physicianSummary,
    /window\.open|about:blank|document\.write/,
  )
  assert.match(component, /:record="record"/)
  assert.match(component, /<StructuredReport/)
  assert.match(component, /hide-emr/)
  assert.equal(component.match(/record\.report/g)?.length, 1)
})

test('FHIR confirmation dialog keeps its middle content vertically scrollable', () => {
  assert.match(
    fhirSubmissionDialog,
    /grid-template-rows: auto minmax\(0, 1fr\) auto/,
  )
  assert.match(
    fhirSubmissionDialog,
    /\.dialog-content \{[\s\S]*?min-height: 0;[\s\S]*?overflow-y: auto;/,
  )
  assert.match(fhirSubmissionDialog, /touch-action: pan-y/)
  assert.match(fhirSubmissionDialog, /max-height: 94dvh/)
})
