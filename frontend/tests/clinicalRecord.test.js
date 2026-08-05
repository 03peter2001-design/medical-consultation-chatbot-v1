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
    legacy_differential_hypotheses: [
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
  assert.equal(result.differentials.length, 0)
  assert.equal(result.legacyDifferentials[0].condition, '顱內出血')
  assert.equal(result.legacyDifferentials[0].coding.code, '1386000')
  assert.equal(result.historyFacts[0].codings[0].code, '38341003')
  assert.equal(result.terminologyReference.version, '1.0.0')
  assert.equal(result.timeline.length, 1)
  assert.equal(result.timeline[0].question, '請描述最不舒服的症狀')
  assert.equal(result.timeline[0].actionLabel, '結束問診')
  assert.equal(result.timeline[0].sourceLabel, 'Safety 規則')
  assert.equal(result.timeline[0].extractedFacts[0].label, '伴隨症狀')
  assert.match(result.timeline[0].reason, /停止追問/)
})

test('maps safety-triggered conditions separately from disease votes', () => {
  const result = buildClinicalRecord({
    type: 'chest',
    triage_level: 'urgent',
    patient_data: {
      reason: '胸痛而且冒冷汗',
    },
    disease_assessment: {
      status: 'safety_triggered',
      method: 'unit_vote_v1',
      top: [],
      ranked: [],
      safety_triggered_conditions: [
        {
          name: '急性冠心症（含心肌梗塞）',
          profile_id: 'acute_coronary_syndrome',
          coding: [
            {
              system: 'http://snomed.info/sct',
              code: '394659003',
              display: 'ACS - Acute coronary syndrome',
              verified: true,
            },
            {
              system: 'http://snomed.info/sct',
              code: '22298006',
              display: 'Myocardial infarction',
              verified: true,
            },
          ],
          source: 'safety_rule',
          triggered_by: [
            {
              rule_code: 'chest_diaphoresis',
              rule_label: '胸部不適合併冒冷汗',
              evidence: '冒冷汗',
            },
          ],
        },
      ],
    },
  })

  assert.equal(result.differentials.length, 0)
  assert.equal(result.safetyTriggeredConditions.length, 1)
  assert.equal(
    result.safetyTriggeredConditions[0].id,
    'acute_coronary_syndrome',
  )
  assert.equal(
    result.safetyTriggeredConditions[0].triggers[0].evidence,
    '冒冷汗',
  )
  assert.equal(
    result.safetyTriggeredConditions[0].coding.code,
    '394659003',
  )
  assert.deepEqual(
    result.safetyTriggeredConditions[0].codings.map(
      (coding) => coding.code,
    ),
    ['394659003', '22298006'],
  )
  assert.equal(
    result.safetyTriggeredConditions[0].coding.source,
    'snomed-registry',
  )
})

test('maps disease funnel audit details for the clinician timeline', () => {
  const result = buildClinicalRecord({
    type: 'chest',
    patient_data: { reason: '走路時胸悶' },
    amie_trace: [
      {
        turn: 1,
        question: { field: 'reason', prompt: '請描述症狀' },
        answer: '走路時胸悶',
        result: { clinical_facts: [], disease_assessment: { top: [] } },
        decision: {
          action: 'ask',
          source: 'deterministic_disease_vote',
          selected_next_field: 'associated',
          next_question: '是否有其他不舒服？',
          selection_phase: 'confirm',
          selection_tier: 'safety_priority',
          candidate_frontier: [
            {
              id: 'acute_coronary_syndrome',
              name: '急性冠心症',
              net_votes: 2,
              support_votes: 2,
              coverage: 0.33,
            },
          ],
          target_fact_codes: ['diaphoresis', 'nausea'],
          funnel_score: {
            discrimination_score: 0,
            confirmation_score: 2,
            refutation_score: 0,
          },
        },
      },
    ],
  })

  const event = result.timeline[0]
  assert.equal(event.selectionPhase, 'confirm')
  assert.equal(event.selectionTier, 'safety_priority')
  assert.equal(event.candidateFrontier[0].name, '急性冠心症')
  assert.equal(event.candidateFrontier[0].netVotes, 2)
  assert.deepEqual(
    event.targetFacts.map((item) => item.code),
    ['diaphoresis', 'nausea'],
  )
  assert.deepEqual(event.funnelScore, {
    discrimination: 0,
    confirmation: 2,
    refutation: 0,
  })
})

test('shows facts from every selected symptom pipeline', () => {
  const result = buildClinicalRecord({
    type: 'headache',
    patient_data: {
      types: ['headache', 'abdomen'],
      onset: '1天前',
      location: '前額',
      abdomen__onset: '3小時前',
      abdomen__location: '右下腹',
    },
  })

  assert.equal(result.identity.type, '頭痛、腹痛')
  assert.deepEqual(
    result.symptomFacts.map(({ label, value }) => ({ label, value })),
    [
      { label: '頭痛 · 發作時間', value: '1天前' },
      { label: '頭痛 · 症狀位置', value: '前額' },
      { label: '腹痛 · 發作時間', value: '3小時前' },
      { label: '腹痛 · 症狀位置', value: '右下腹' },
    ],
  )
})

test('reuses an unambiguous source FHIR coding for a legacy audit entry', () => {
  const result = buildClinicalRecord({
    clinical_codings: [
      {
        field: 'chronic',
        system: 'http://snomed.info/sct',
        code: '38341003',
        display: 'Hypertensive disorder',
        source: 'fhir',
      },
    ],
    patient_data: {
      chronic: '高血壓',
    },
    legacy_differential_hypotheses: [
      {
        condition: '高血壓',
        supporting_evidence: ['既往病史'],
        opposing_evidence: [],
      },
    ],
  })

  assert.equal(result.legacyDifferentials[0].coding.code, '38341003')
  assert.equal(result.legacyDifferentials[0].coding.source, 'fhir')
})

test('does not guess a legacy audit coding when source codings are ambiguous', () => {
  const result = buildClinicalRecord({
    clinical_codings: [
      {
        field: 'chronic',
        system: 'http://snomed.info/sct',
        code: '38341003',
        display: 'Hypertensive disorder',
        source: 'fhir',
      },
      {
        field: 'chronic',
        system: 'http://snomed.info/sct',
        code: '44054006',
        display: 'Diabetes mellitus type 2',
        source: 'fhir',
      },
    ],
    patient_data: {
      chronic: '高血壓、第二型糖尿病',
    },
    legacy_differential_hypotheses: [
      {
        condition: '高血壓',
        supporting_evidence: [],
        opposing_evidence: [],
      },
    ],
  })

  assert.equal(result.legacyDifferentials[0].coding, null)
})

test('shows a validated AI-suggested SNOMED coding only in legacy audit', () => {
  const result = buildClinicalRecord({
    legacy_differential_hypotheses: [
      {
        condition: '胸痛',
        coding: {
          system: 'http://snomed.info/sct',
          code: '29857009',
          display: 'Chest pain',
          source: 'ai-suggested',
        },
        supporting_evidence: ['活動時胸悶'],
        opposing_evidence: [],
      },
    ],
  })

  assert.deepEqual(result.legacyDifferentials[0].coding, {
    field: '',
    system: 'http://snomed.info/sct',
    code: '29857009',
    display: 'Chest pain',
    source: 'ai-suggested',
  })
})

test('maps deterministic disease votes separately from coverage', () => {
  const item = {
    id: 'acute_coronary_syndrome',
    name: '急性冠心症',
    coding: null,
    must_not_miss: true,
    review_status: 'provisional',
    net_votes: 2,
    support_votes: 3,
    oppose_votes: 1,
    coverage: 0.75,
    supporting: [
      { fact: 'chest_pressure', evidence: '胸口像被壓住' },
    ],
    opposing: [
      { fact: 'chest_wall_tenderness', evidence: '按壓會痛' },
    ],
    missing_facts: ['diaphoresis'],
  }
  const result = buildClinicalRecord({
    disease_assessment: {
      profile_version: 'chest-v1',
      method: 'unit_vote_v1',
      status: 'ready',
      provisional: true,
      computed_from: 'live',
      top: [item],
      ranked: [item],
      must_not_miss: [item],
    },
  })

  assert.equal(result.differentials[0].condition, '急性冠心症')
  assert.equal(result.differentials[0].netVotes, 2)
  assert.equal(result.differentials[0].coverage, 0.75)
  assert.equal(result.mustNotMiss[0].mustNotMiss, true)
  assert.equal(result.diseaseAssessment.method, 'unit_vote_v1')
  assert.equal(result.diseaseAssessment.provisional, true)
})
