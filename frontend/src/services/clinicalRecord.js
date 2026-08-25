import {
  codingKey,
  normalizeCoding,
  resolveConditionCoding,
  resolveConditionCodings,
} from './terminology.js'
import {
  QUESTIONNAIRE_FIELD_LABELS,
  QUESTIONNAIRE_ROUTE_FIELDS,
  QUESTIONNAIRE_ROUTE_LABELS,
} from '../data/questionnaireRoutes.js'

const TYPE_LABELS = {
  ...QUESTIONNAIRE_ROUTE_LABELS,
  other: '其他',
}

const FIELD_LABELS = {
  onset: '發作時間',
  start_type: '發作型態',
  location: '症狀位置',
  worst_ever: '嚴重程度',
  severity: '嚴重程度',
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
  onset_sudden: '突然發作',
  onset_gradual: '逐漸發作',
  severity_mild: '輕微',
  severity_moderate: '中等',
  severity_severe: '劇烈',
  chest_pressure: '胸部壓迫感',
  exertional_trigger: '活動誘發',
  diaphoresis: '冒冷汗',
  syncope: '昏厥',
  dyspnea: '呼吸急促',
  tearing_pain: '撕裂樣疼痛',
  pain_radiates_back: '疼痛延伸至背部',
  pleuritic_pain: '呼吸相關胸痛',
  hemoptysis: '咳血',
  tachycardia: '心跳過速',
  reproducible_tenderness: '可重現壓痛',
  localized_pain: '局部疼痛',
  movement_trigger: '動作誘發',
  burning_pain: '灼熱痛',
  meal_related: '進食相關',
  acid_regurgitation: '胃酸逆流',
  palpitations: '心悸',
  dizziness_unspecified: '頭暈',
  cough_sputum: '咳嗽有痰',
  positional_relief: '姿勢改變緩解',
  recent_infection: '近期感染',
  stress_trigger: '壓力誘發',
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
  unilateral_headache: '單側頭痛',
  bilateral_headache: '雙側頭痛',
  occipital_neck_pain: '後腦及頸部疼痛',
  diffuse_headache: '全頭疼痛',
  pulsating_headache: '搏動性頭痛',
  pressure_band_headache: '緊束壓迫型頭痛',
  cough_valsalva_trigger: '咳嗽或用力加重',
  activity_aggravation: '活動加重',
  photophobia: '畏光',
  phonophobia: '畏聲',
  dark_quiet_relief: '黑暗安靜環境緩解',
  neck_massage_relief: '按摩頭頸部緩解',
  cancer_history: '癌症病史',
  immunocompromised: '免疫功能低下',
  anticoagulant_use: '使用抗凝血藥物',
  pregnancy_postpartum: '懷孕或產後',
  migraine_history: '偏頭痛病史',
  aneurysm_history: '腦動脈瘤病史',
  colicky_abdominal_pain: '陣發性腹痛',
  constant_abdominal_pain: '持續性腹痛',
  periumbilical_to_rlq: '肚臍周圍轉移至右下腹',
  abdominal_pain_to_back: '腹痛延伸至背部',
  fasting_worse: '空腹加重',
  ruq_pain: '右上腹痛',
  rlq_pain: '右下腹痛',
  llq_pain: '左下腹痛',
  diffuse_abdominal_pain: '全腹痛',
  flank_pain: '腰脅部疼痛',
  lower_abdominal_pain: '下腹痛',
  diarrhea: '腹瀉',
  constipation: '便秘',
  bloody_stool: '血便',
  hematuria: '血尿',
  missed_period: '月經過期',
  vaginal_discharge: '陰道分泌物增加',
  sick_contacts: '群聚腸胃症狀',
  gallstones_history: '膽結石病史',
  kidney_stones_history: '腎結石病史',
  bowel_obstruction_history: '腸阻塞病史',
  pancreatitis_history: '胰臟炎病史',
  abdominal_aortic_aneurysm_history: '腹主動脈瘤病史',
  prior_abdominal_surgery: '腹部手術史',
  peritoneal_irritation: '腹膜刺激徵象',
}

const DECISION_SOURCE_LABELS = {
  safety_rule: 'Safety 規則',
  semantic_safety_fail_closed: '語意安全保守轉交',
  route_guard: '主訴路由守門',
  deterministic_flow: '確定性流程',
  deterministic_fallback: '確定性 fallback',
  gemini_planner: 'Gemini 規劃器',
  gemini_planner_with_rag: 'Gemini 規劃器＋RAG',
  deterministic_disease_vote: '固定疾病表投票',
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
  const routes = Array.isArray(data.types) && data.types.length
    ? data.types
    : [record.type].filter(Boolean)
  const routeLabels = routes.map((route) => TYPE_LABELS[route] || route)
  const chief = record.chief_assessment || {}
  const extraction = chief.extraction || {}
  const amie = record.amie_state || {}
  const diseaseAssessment =
    record.disease_assessment || amie.disease_assessment || {}
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
  const symptomFacts = routes.flatMap((route, routeIndex) => {
    const prefix = routeIndex === 0 ? '' : `${route}__`
    const routeFields = QUESTIONNAIRE_ROUTE_FIELDS[route] || []
    const routeFieldLabels = QUESTIONNAIRE_FIELD_LABELS[route] || {}
    return labeledFacts(
      data,
      routeFields.map((field) => `${prefix}${field}`),
      codings,
    ).map((fact) => ({
      ...fact,
      label: routes.length > 1
        ? `${TYPE_LABELS[route] || route} · ${
            FIELD_LABELS[fact.key.replace(prefix, '')] ||
            routeFieldLabels[fact.key.replace(prefix, '')] ||
            fact.key.replace(prefix, '')
          }`
        : FIELD_LABELS[fact.key] || routeFieldLabels[fact.key] || fact.key,
    }))
  })
  const mapAssessment = (item) => {
    const conditionCodings = resolveConditionCodings(
      item.name,
      item.coding,
      codings,
      data,
    )
    return {
      id: item.id,
      condition: item.name,
      coding: conditionCodings[0] || null,
      codings: conditionCodings,
      netVotes: Number(item.net_votes || 0),
      supportVotes: Number(item.support_votes || 0),
      opposeVotes: Number(item.oppose_votes || 0),
      coverage: Number(item.coverage || 0),
      provisional: item.review_status === 'provisional',
      mustNotMiss: Boolean(item.must_not_miss),
      supporting_evidence: (item.supporting || []).map(
        (clue) => clue.evidence || clue.fact,
      ),
      opposing_evidence: (item.opposing || []).map(
        (clue) => clue.evidence || clue.fact,
      ),
      missingFacts: (item.missing_facts || []).map(
        (fact) => FINDING_LABELS[fact] || fact,
      ),
    }
  }
  const allDifferentials = (diseaseAssessment.ranked || []).map(
    mapAssessment,
  )
  const differentials = (diseaseAssessment.top || []).map(mapAssessment)
  const mustNotMiss = (diseaseAssessment.must_not_miss || []).map(
    mapAssessment,
  )
  const safetyTriggeredConditions = (
    diseaseAssessment.safety_triggered_conditions || []
  ).map((item) => {
    const conditionCodings = resolveConditionCodings(
      item.name,
      item.coding,
      codings,
      data,
    )
    return {
      id: item.profile_id || '',
      condition: item.name,
      coding: conditionCodings[0] || null,
      codings: conditionCodings,
      source: item.source || 'safety_rule',
      triggers: (item.triggered_by || []).map((trigger) => ({
        ruleCode: trigger.rule_code || '',
        ruleLabel: trigger.rule_label || '',
        evidence: trigger.evidence || '',
      })),
    }
  })
  const legacyDifferentials = (
    record.legacy_differential_hypotheses || []
  ).map((hypothesis) => {
      const coding = resolveConditionCoding(
        hypothesis.condition,
        hypothesis.coding,
        codings,
        data,
      )
      return { ...hypothesis, coding }
    })

  return {
    identity: {
      name: data.name || '姓名未提供',
      queueNumber: record.queue_number || '—',
      birthDate: data.birth_date || '未提供',
      gender: data.gender || '未提供',
      age: isPresent(data.age) ? `${data.age}歲` : '年齡未提供',
      bloodType: data.blood_type || '血型未提供',
      type: routeLabels.join('、') || '未分類',
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
    symptomFacts,
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
    allDifferentials,
    mustNotMiss,
    safetyTriggeredConditions,
    legacyDifferentials,
    diseaseAssessment: {
      status: diseaseAssessment.status || 'unavailable',
      profileVersion: diseaseAssessment.profile_version || '',
      method: diseaseAssessment.method || '',
      provisional: Boolean(diseaseAssessment.provisional),
      computedFrom: diseaseAssessment.computed_from || '',
    },
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
            clinicalFacts: (result.clinical_facts || []).map((fact) => ({
              code: fact.code,
              label: FINDING_LABELS[fact.code] || fact.code,
              status: fact.status,
              evidence: fact.evidence || '',
            })),
            diseaseVotes: (
              result.disease_assessment?.top || []
            ).map((item) => ({
              id: item.id,
              name: item.name,
              netVotes: item.net_votes,
              coverage: item.coverage,
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
            questionUtility: Number(decision.question_utility || 0),
            selectionPhase: decision.selection_phase || '',
            selectionTier: decision.selection_tier || '',
            candidateFrontier: (decision.candidate_frontier || []).map(
              (item) => ({
                id: item.id,
                name: item.name || item.id,
                netVotes: Number(item.net_votes || 0),
                supportVotes: Number(item.support_votes || 0),
                coverage: Number(item.coverage || 0),
              }),
            ),
            targetFacts: (decision.target_fact_codes || []).map((code) => ({
              code,
              label: FINDING_LABELS[code] || code,
            })),
            funnelScore: {
              discrimination: Number(
                decision.funnel_score?.discrimination_score || 0,
              ),
              confirmation: Number(
                decision.funnel_score?.confirmation_score || 0,
              ),
              refutation: Number(
                decision.funnel_score?.refutation_score || 0,
              ),
            },
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
          clinicalFacts: event.clinical_facts || [],
          diseaseVotes: event.disease_votes || [],
          triage: 'routine',
          actionLabel: '舊版紀錄',
          sourceLabel: '舊版 evidence timeline',
          selectedNextField: '',
          nextQuestion: '',
          needsRetrieval: false,
          retrievalQuery: '',
          questionUtility: 0,
          selectionPhase: '',
          selectionTier: '',
          candidateFrontier: [],
          targetFacts: [],
          funnelScore: {
            discrimination: 0,
            confirmation: 0,
            refutation: 0,
          },
          reason: event.audit_reason || '',
          modelError: '',
        })),
  }
}
