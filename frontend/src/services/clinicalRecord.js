import {
  codingKey,
  normalizeCoding,
  resolveConditionCoding,
} from './terminology.js'

const TYPE_LABELS = {
  chest: '胸痛',
  headache: '頭痛',
  abdomen: '腹痛',
  other: '其他',
}

const FIELD_LABELS = {
  onset: '發作時間',
  start_type: '發作型態',
  location: '症狀位置',
  worst_ever: '嚴重程度',
  quality: '疼痛性質',
  aggravate: '加重因素',
  relieve: '緩解因素',
  associated: '伴隨症狀',
  risk_flags: '風險因子',
  smoke: '吸菸史',
  chronic: '慢性病史',
  past_meds: '過去用藥',
  current_meds: '目前用藥',
  allergy: '過敏史',
  cardio: '心血管病史',
  neuro: '神經病史',
  abdomen_hx: '腹部病史',
  surgery: '手術史',
}

const FINDING_LABELS = {
  altered_consciousness: '意識改變',
  fever: '發燒',
  focal_neurologic_symptom: '局部神經學症狀',
  gait_unsteadiness: '步態不穩',
  nausea: '噁心',
  neck_stiffness: '頸部僵硬',
  recent_head_trauma: '近期頭部外傷',
  speech_difficulty: '言語困難',
  vision_loss: '視力異常',
  visual_change_unspecified: '視覺改變',
  vomiting: '嘔吐',
}

const DECISION_SOURCE_LABELS = {
  safety_rule: 'Safety 規則',
  semantic_safety_fail_closed: '語意安全保守轉交',
  route_guard: '主訴路由守門',
  deterministic_flow: '確定性流程',
  deterministic_fallback: '確定性 fallback',
  gemini_planner: 'Gemini 規劃器',
  gemini_planner_with_rag: 'Gemini 規劃器＋RAG',
}

const ACTION_LABELS = {
  ask: '繼續追問',
  complete: '結束問診',
  handoff: '轉交醫療人員',
}

function isPresent(value) {
  return (
    value !== null &&
    value !== undefined &&
    String(value).trim() !== ''
  )
}

function isClearAnswer(value) {
  return /^(沒有|否認|以上皆無|未曾|不清楚|無\b)/.test(
    String(value).trim(),
  )
}

function labeledFacts(data, keys, codings = []) {
  return keys
    .filter((key) => isPresent(data[key]))
    .map((key) => ({
      key,
      label: FIELD_LABELS[key] || key,
      value: String(data[key]),
      tone: isClearAnswer(data[key]) ? 'clear' : 'neutral',
      codings: codings.filter((coding) => coding.field === key),
    }))
}

function findingLabel(finding) {
  return FINDING_LABELS[finding.code] || finding.evidence || finding.code
}

export function buildClinicalRecord(record = {}) {
  const data = record.patient_data || {}
  const chief = record.chief_assessment || {}
  const extraction = chief.extraction || {}
  const amie = record.amie_state || {}
  const redFlags = amie.red_flags || chief.safety_flags || []
  const trace = record.amie_trace || []
  const fallbackTimeline = amie.evidence_timeline || []
  const codings = (record.clinical_codings || [])
    .map((coding) => normalizeCoding(coding))
    .filter(Boolean)
    .filter(
      (coding, index, all) =>
        all.findIndex(
          (candidate) => codingKey(candidate) === codingKey(coding),
        ) === index,
    )
  const differentials = (amie.differential_hypotheses || []).map(
    (hypothesis) => {
      const coding = resolveConditionCoding(
        hypothesis.condition,
        hypothesis.coding,
      )
      return { ...hypothesis, coding }
    },
  )

  return {
    identity: {
      name: data.name || '姓名未提供',
      queueNumber: record.queue_number || '—',
      gender: data.gender || '未提供',
      age: isPresent(data.age) ? `${data.age}歲` : '年齡未提供',
      bloodType: data.blood_type || '血型未提供',
      type: TYPE_LABELS[record.type] || record.type || '未分類',
      triage: record.triage_level === 'urgent' ? '優先處理' : '一般處理',
      urgent: record.triage_level === 'urgent',
      bloodTypeCodings: codings.filter(
        (coding) => coding.field === 'blood_type',
      ),
    },
    complaint: data.reason || record.reason || '主訴未提供',
    redFlags: redFlags.map((flag) => ({
      label: flag.label || flag.code || '警訊',
      evidence: flag.evidence || '',
    })),
    findings: (extraction.findings || [])
      .filter((finding) => finding.status !== 'absent')
      .map((finding) => ({
        code: finding.code,
        label: findingLabel(finding),
        evidence: finding.evidence || '',
      })),
    symptomFacts: labeledFacts(
      data,
      [
        'onset',
        'start_type',
        'location',
        'worst_ever',
        'quality',
        'aggravate',
        'relieve',
        'associated',
        'risk_flags',
      ],
      codings,
    ),
    historyFacts: labeledFacts(
      data,
      [
        'smoke',
        'chronic',
        'past_meds',
        'current_meds',
        'allergy',
        'cardio',
        'neuro',
        'abdomen_hx',
        'surgery',
      ],
      codings,
    ),
    differentials,
    terminologyReference: record.terminology_reference || null,
    knowledgeGaps: amie.knowledge_gaps || [],
    timeline: trace.length
      ? trace.map((event) => {
          const decision = event.decision || {}
          const result = event.result || {}
          return {
            turn: event.turn,
            field: event.question?.field || '',
            question: event.question?.prompt || '',
            answer: event.answer || '',
            extractedFacts: Object.entries(
              result.extracted_facts || {},
            ).map(([field, value]) => ({
              field,
              label: FIELD_LABELS[field] || field,
              value: String(value),
            })),
            triage:
              result.triage_level === 'urgent' ? 'urgent' : 'routine',
            actionLabel:
              ACTION_LABELS[decision.action] || decision.action || '未記錄',
            sourceLabel:
              DECISION_SOURCE_LABELS[decision.source] ||
              decision.source ||
              '未記錄',
            selectedNextField: decision.selected_next_field || '',
            nextQuestion: decision.next_question || '',
            needsRetrieval: Boolean(decision.needs_retrieval),
            retrievalQuery: decision.retrieval_query || '',
            reason: event.reason || '',
            modelError: event.model_error || '',
          }
        })
      : fallbackTimeline.map((event) => ({
          turn: event.turn,
          field: '',
          question: '',
          answer: event.answer_excerpt || '',
          extractedFacts: Object.entries(
            event.extracted_facts || {},
          ).map(([field, value]) => ({
            field,
            label: FIELD_LABELS[field] || field,
            value: String(value),
          })),
          triage: 'routine',
          actionLabel: '舊版紀錄',
          sourceLabel: '舊版 evidence timeline',
          selectedNextField: '',
          nextQuestion: '',
          needsRetrieval: false,
          retrievalQuery: '',
          reason: event.audit_reason || '',
          modelError: '',
        })),
  }
}
