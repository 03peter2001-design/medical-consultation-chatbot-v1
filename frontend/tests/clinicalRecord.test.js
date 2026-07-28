import assert from 'node:assert/strict'
import test from 'node:test'

import { buildClinicalRecord } from '../src/services/clinicalRecord.js'

test('builds a scannable clinical record from structured patient data', () => {
  const result = buildClinicalRecord({
    queue_number: '261',
    type: 'headache',
    triage_level: 'urgent',
    clinical_codings: [
      {
        field: 'blood_type',
        system: 'http://loinc.org',
        code: '882-1',
        display: 'ABO and Rh group [Type] in Blood',
        source: 'fhir',
      },
      {
        field: 'chronic',
        system: 'http://snomed.info/sct',
        code: '38341003',
        display: 'Hypertensive disorder',
        source: 'fhir',
      },
    ],
    terminology_reference: {
      package: 'tw.gov.mohw.twcore',
      version: '1.0.0',
    },
    patient_data: {
      name: '測試病人',
      gender: '男',
      age: '58',
      blood_type: 'O型',
      reason: '頭痛到眼前發黑',
      onset: '1天前',
      chronic: '高血壓',
      allergy: '否認已知藥物過敏',
    },
    chief_assessment: {
      extraction: {
        findings: [
          {
            code: 'vision_loss',
            status: 'present',
            evidence: '眼前發黑',
          },
        ],
      },
      safety_flags: [
        {
          code: 'semantic_vision_loss',
          label: '突發視力喪失',
          evidence: '眼前發黑',
        },
      ],
    },
    amie_state: {
      differential_hypotheses: [
        {
          condition: '顱內出血',
          coding: {
            system: 'http://snomed.info/sct',
            code: '1386000',
            display: 'Intracranial hemorrhage',
            source: 'fhir',
          },
          supporting_evidence: ['高血壓'],
          opposing_evidence: ['無局部無力'],
        },
      ],
    },
    amie_trace: [
      {
        turn: 1,
        question: {
          field: 'reason',
          prompt: '請描述最不舒服的症狀',
        },
        answer: '頭痛到眼前發黑',
        result: {
          extracted_facts: { associated: '眼前發黑' },
          triage_level: 'urgent',
          red_flags: [
            {
              code: 'semantic_vision_loss',
              label: '突發視力喪失',
            },
          ],
        },
        decision: {
          action: 'complete',
          source: 'safety_rule',
          selected_next_field: null,
          next_question: null,
          needs_retrieval: false,
        },
        reason: 'Safety 層命中視力警訊，因此停止追問。',
        model_error: '',
      },
    ],
  })

  assert.deepEqual(result.identity, {
    name: '測試病人',
    queueNumber: '261',
    gender: '男',
    age: '58歲',
    bloodType: 'O型',
    type: '頭痛',
    triage: '優先處理',
    urgent: true,
    bloodTypeCodings: [
      {
        field: 'blood_type',
        system: 'http://loinc.org',
        code: '882-1',
        display: 'ABO and Rh group [Type] in Blood',
        source: 'fhir',
      },
    ],
  })
  assert.equal(result.redFlags[0].label, '突發視力喪失')
  assert.equal(result.findings[0].label, '視力異常')
  assert.equal(result.historyFacts[1].tone, 'clear')
  assert.equal(result.differentials[0].condition, '顱內出血')
  assert.equal(result.differentials[0].coding.code, '1386000')
  assert.equal(result.historyFacts[0].codings[0].code, '38341003')
  assert.equal(result.terminologyReference.version, '1.0.0')
  assert.equal(result.timeline.length, 1)
  assert.equal(result.timeline[0].question, '請描述最不舒服的症狀')
  assert.equal(result.timeline[0].actionLabel, '結束問診')
  assert.equal(result.timeline[0].sourceLabel, 'Safety 規則')
  assert.equal(result.timeline[0].extractedFacts[0].label, '伴隨症狀')
  assert.match(result.timeline[0].reason, /停止追問/)
})
