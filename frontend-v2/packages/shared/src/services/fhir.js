import { buildFhirClinicalCodings } from './terminology.js'

export const TAIWAN_ID_SYSTEM = 'http://www.moi.gov.tw'

const runtimeLocation =
  typeof window === 'undefined'
    ? { search: '', protocol: 'http:', hostname: '127.0.0.1' }
    : window.location

function parseBoolean(value, fallback = false) {
  if (value == null || value === '') return fallback
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase())
}

export function resolveFhirBaseUrl(
  locationLike = runtimeLocation,
  configuredBaseUrl = import.meta.env?.VITE_FHIR_BASE_URL,
) {
  const params = new URLSearchParams(locationLike.search || '')
  const override = params.get('fhir')?.trim()
  const requested = override || configuredBaseUrl?.trim()

  if (requested) {
    const candidate = /^https?:\/\//i.test(requested)
      ? requested
      : `http://${requested}`
    try {
      const url = new URL(candidate)
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        return url.toString().replace(/\/+$/, '')
      }
    } catch {
      console.warn('忽略無效的 FHIR base URL：', requested)
    }
  }

  const protocol = locationLike.protocol === 'https:' ? 'https:' : 'http:'
  const hostname = locationLike.hostname || '127.0.0.1'
  return `${protocol}//${hostname}:8080/fhir`
}

export function isDirectFhirEnabled(
  locationLike = runtimeLocation,
  configuredValue = import.meta.env?.VITE_ENABLE_DIRECT_FHIR,
  developmentMode = import.meta.env?.DEV === true,
) {
  const allowed = parseBoolean(configuredValue, developmentMode)
  if (!allowed) return false

  const params = new URLSearchParams(locationLike.search || '')
  if (params.has('directFhir')) {
    return parseBoolean(params.get('directFhir'))
  }
  return true
}

export function normalizeNationalId(value) {
  return String(value || '')
    .trim()
    .toUpperCase()
}

export function isNationalIdFormat(value) {
  return /^[A-Z][0-9]{9}$/.test(normalizeNationalId(value))
}

function fhirErrorMessage(payload, fallback) {
  const diagnostics = payload?.issue
    ?.map((issue) => issue.diagnostics || issue.details?.text)
    .filter(Boolean)
    .join('；')
  return diagnostics || fallback
}

async function readFhirResponse(response) {
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(
      fhirErrorMessage(payload, `FHIR API 回傳 HTTP ${response.status}`),
    )
  }
  return payload
}

export async function findPatientByNationalId(
  nationalId,
  {
    baseUrl = resolveFhirBaseUrl(),
    fetchImpl = fetch,
  } = {},
) {
  const normalizedId = normalizeNationalId(nationalId)
  if (!isNationalIdFormat(normalizedId)) {
    throw new Error('身分證字號格式應為 1 個英文字母加 9 個數字。')
  }

  const body = new URLSearchParams({
    identifier: `${TAIWAN_ID_SYSTEM}|${normalizedId}`,
  })
  const response = await fetchImpl(`${baseUrl}/Patient/_search`, {
    method: 'POST',
    headers: {
      Accept: 'application/fhir+json',
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  })
  const bundle = await readFhirResponse(response)
  const matches = (bundle.entry || [])
    .map((entry) => entry.resource)
    .filter((resource) => resource?.resourceType === 'Patient')

  if (matches.length === 0) {
    throw new Error(`查無身分證字號 ${normalizedId} 的測試病人。`)
  }
  if (matches.length > 1) {
    throw new Error(
      `身分證字號 ${normalizedId} 找到 ${matches.length} 位病人，請由管理人員處理重複資料。`,
    )
  }
  return matches[0]
}

async function loadPatientEverything(
  patientId,
  {
    baseUrl = resolveFhirBaseUrl(),
    fetchImpl = fetch,
  } = {},
) {
  if (!patientId) throw new Error('FHIR Patient.id 不可為空。')
  const response = await fetchImpl(
    `${baseUrl}/Patient/${encodeURIComponent(patientId)}/$everything?_count=100`,
    {
      headers: { Accept: 'application/fhir+json' },
    },
  )
  return readFhirResponse(response)
}

export async function loadPatientByNationalId(
  nationalId,
  options = {},
) {
  const patient = await findPatientByNationalId(nationalId, options)
  const bundle = await loadPatientEverything(patient.id, options)
  return {
    patient,
    bundle,
    resources: (bundle.entry || [])
      .map((entry) => entry.resource)
      .filter(Boolean),
  }
}

export function patientDisplayName(patient) {
  const officialName =
    patient?.name?.find((name) => name.use === 'official') || patient?.name?.[0]
  return (
    officialName?.text ||
    [officialName?.family, ...(officialName?.given || [])]
      .filter(Boolean)
      .join(' ') ||
    '未命名病人'
  )
}

export function patientAge(birthDate, now = new Date()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(birthDate || '')) return null
  const [year, month, day] = birthDate.split('-').map(Number)
  let age = now.getFullYear() - year
  const beforeBirthday =
    now.getMonth() + 1 < month ||
    (now.getMonth() + 1 === month && now.getDate() < day)
  if (beforeBirthday) age -= 1
  return age >= 0 && age <= 130 ? age : null
}

function conceptText(concept) {
  return (
    concept?.text ||
    concept?.display ||
    concept?.coding?.find((coding) => coding.display)?.display ||
    concept?.coding?.[0]?.code ||
    concept?.code ||
    ''
  )
}

function questionnaireAnswerText(answer) {
  if (!answer) return ''
  return (
    answer.valueString ||
    answer.valueCode ||
    conceptText(answer.valueCoding) ||
    String(answer.valueBoolean ?? '')
  )
}

function flattenQuestionnaireItems(items = []) {
  return items.flatMap((item) => [
    item,
    ...flattenQuestionnaireItems(item.item || []),
    ...(item.answer || []).flatMap((answer) =>
      flattenQuestionnaireItems(answer.item || []),
    ),
  ])
}

function observationCodeIncludes(resource, expectedCodes) {
  return (resource?.code?.coding || []).some((coding) =>
    expectedCodes.includes(coding.code),
  )
}

function normalizeBloodType(value) {
  const normalized = String(value || '').toUpperCase().replace(/\s+/g, '')
  if (normalized.includes('AB')) return 'AB型'
  if (/(^|[^A-Z])A([^A-Z]|$)/.test(normalized)) return 'A型'
  if (/(^|[^A-Z])B([^A-Z]|$)/.test(normalized)) return 'B型'
  if (/(^|[^A-Z])O([^A-Z]|$)/.test(normalized)) return 'O型'
  return ''
}

function uniqueClinicalValues(values) {
  return [...new Set(values.flatMap((value) => value || []).filter(Boolean))]
}

function joinClinicalValues(values) {
  return uniqueClinicalValues(values).join('、')
}

function splitHistoryStatements(value) {
  return String(value || '')
    .split(/[，,；;。]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function isNegatedHistory(value) {
  return /否認|沒有|無已知|未曾|並無|不曾/.test(String(value || ''))
}

function isSmokingHistory(value) {
  return /吸菸|抽菸|戒菸|smok/i.test(String(value || ''))
}

function conditionIsHistorical(resource) {
  if (resource?.resourceType !== 'Condition') return false
  const verificationCodes = (resource.verificationStatus?.coding || []).map(
    (coding) => coding.code,
  )
  if (
    verificationCodes.some((code) =>
      ['refuted', 'entered-in-error'].includes(code),
    )
  ) {
    return false
  }

  const categoryText = (resource.category || [])
    .map((category) => [
      conceptText(category),
      ...(category.coding || []).map((coding) => coding.display || ''),
    ])
    .flat()
    .join(' ')
  const conditionText = conceptText(resource.code)
  const explicitlyCurrentSymptom =
    /本次|此次|current encounter/i.test(categoryText) &&
    /胸痛|頭痛|腹痛|chest pain|headache|abdominal pain/i.test(
      conditionText,
    )

  // encounter-diagnosis 也可能是過去住院確診的中風等疾病；
  // 只排除明確標示為本次就醫症狀的項目。
  return !explicitlyCurrentSymptom
}

function medicationText(resource) {
  return (
    conceptText(resource?.medicationCodeableConcept) ||
    resource?.medicationReference?.display ||
    ''
  )
}

function procedureIsSurgical(resource) {
  if (
    resource?.resourceType !== 'Procedure' ||
    resource.status !== 'completed'
  ) {
    return false
  }
  const procedureCategories = resource.category
    ? Array.isArray(resource.category)
      ? resource.category
      : [resource.category]
    : []
  const text = [
    conceptText(resource.code),
    ...procedureCategories.map(conceptText),
  ]
    .join(' ')
    .toLowerCase()
  return /手術|切除|置換|支架|引流|繞道|植入|消融|介入|夾閉|栓塞|開顱|融合|surg|operation|ectomy|otomy|bypass|stent|implant|replacement|repair|ablation|drainage|cabg|clipping|embolization|craniotomy|shunt|endarterectomy|angioplasty|spinal fusion/.test(
    text,
  )
}

const CONDITION_ROUTE_TERMS = {
  cardio: [
    '高血壓', '心絞痛', '心臟衰竭', '心肌梗塞', '心律不整',
    '主動脈剝離', '肺栓塞', '肺高壓', '心包膜積水', '氣喘',
    '肺癌', '慢性阻塞型肺病', '支氣管擴張', '氣胸', '中風',
    'hypertension', 'angina', 'heart failure', 'myocardial infarction',
    'arrhythm', 'aortic dissection', 'pulmonary embol',
    'pulmonary hypertension', 'pericardial effusion', 'asthma',
    '冠心症', 'coronary artery disease', 'coronary heart disease',
    'lung cancer', 'copd', 'bronchiectasis', 'pneumothorax', 'stroke',
  ],
  neuro: [
    '中風', '腦動脈瘤', '腦出血', '腦膜炎', '腦炎', '腦部腫瘤',
    '癲癇', '偏頭痛', '顳動脈炎', 'stroke', 'cerebral aneurysm',
    'intracranial hemorrhage', 'brain hemorrhage', 'meningitis',
    'encephalitis', 'brain tumor', 'epilepsy', 'migraine',
    'temporal arteritis',
  ],
  abdomen_hx: [
    '肝膽結石', '膽結石', '腎結石', '盲腸炎', '闌尾炎', '腸阻塞',
    '胰臟炎', '腹主動脈瘤', '紫質症', '糖尿病酮酸中毒',
    'gallstone', 'cholelithiasis', 'kidney stone', 'renal stone',
    'appendicitis', 'bowel obstruction', 'intestinal obstruction',
    'pancreatitis', 'abdominal aortic aneurysm', 'porphyria',
    'diabetic ketoacidosis',
  ],
}

const CONDITION_ROUTE_CODES = {
  cardio: new Set([
    '38341003', // Hypertension
    '194828000', // Angina
    '84114007', // Heart failure
    '22298006', // Myocardial infarction
    '49436004', // Atrial fibrillation
    '230690007', // Stroke
  ]),
  neuro: new Set([
    '230690007', // Stroke
    '128608001', // Cerebral aneurysm
    '1386000', // Intracranial hemorrhage
    '7180009', // Meningitis
    '45170000', // Encephalitis
    '84757009', // Epilepsy
    '37796009', // Migraine
  ]),
  abdomen_hx: new Set([
    '235919008', // Gallstone
    '95570007', // Renal calculus
    '74400008', // Appendicitis
    '81060008', // Intestinal obstruction
    '75694006', // Pancreatitis
    '233985008', // Abdominal aortic aneurysm
  ]),
}

function matchesConditionRoute(value, route, codes = []) {
  const normalized = String(value || '').toLowerCase()
  return (
    CONDITION_ROUTE_TERMS[route].some((term) =>
      normalized.includes(term.toLowerCase()),
    ) ||
    codes.some((code) => CONDITION_ROUTE_CODES[route].has(code))
  )
}

export function buildPatientPrefill({
  patient,
  resources = [],
} = {}) {
  if (!patient) return null

  const gender = {
    male: '男性',
    female: '女性',
    other: '其他',
    unknown: '不便透露',
  }[patient.gender]
  const name = patientDisplayName(patient)
  const birthDate = patient.birthDate || ''

  const bloodObservation = resources.find(
    (resource) =>
      resource?.resourceType === 'Observation' &&
      observationCodeIncludes(resource, ['882-1', '883-9']),
  )
  const bloodType = normalizeBloodType(
    conceptText(bloodObservation?.valueCodeableConcept) ||
      bloodObservation?.valueString,
  )

  const questionnaireItems = resources
    .filter(
      (resource) => resource?.resourceType === 'QuestionnaireResponse',
    )
    .flatMap((resource) => flattenQuestionnaireItems(resource.item))
  const answerFor = (...linkIds) => {
    const expected = new Set(linkIds.map((value) => value.toLowerCase()))
    return questionnaireItems
      .filter((candidate) =>
        expected.has(String(candidate.linkId || '').toLowerCase()),
      )
      .flatMap((item) => item.answer || [])
      .map(questionnaireAnswerText)
      .filter(Boolean)
      .join('、')
  }

  const historyAnswer = answerFor(
    'history',
    'medical-history',
    'past-medical-history',
  )
  const allergyResources = resources
    .filter((resource) => resource?.resourceType === 'AllergyIntolerance')
    .map((resource) => conceptText(resource.code))
    .filter(Boolean)
  const medicationResources = resources.filter((resource) =>
    ['MedicationStatement', 'MedicationRequest'].includes(
      resource?.resourceType,
    ),
  )
  const activeMedications = medicationResources
    .filter(
      (resource) =>
        ['active', 'on-hold', 'intended'].includes(resource.status),
    )
    .map(medicationText)
    .filter(Boolean)
  const pastMedications = medicationResources
    .filter((resource) =>
      ['completed', 'stopped'].includes(resource.status),
    )
    .map(medicationText)
    .filter(Boolean)
  const historicalConditionResources = resources.filter(
    conditionIsHistorical,
  )
  const historicalConditions = historicalConditionResources
    .map((resource) => conceptText(resource.code))
    .filter(Boolean)
  const historyValues = uniqueClinicalValues([
    ...splitHistoryStatements(historyAnswer),
    ...historicalConditions,
  ])
  const chronicHistoryValues = historyValues.filter(
    (value) => !isSmokingHistory(value) && !isNegatedHistory(value),
  )
  const smokingHistoryValues = historyValues.filter(isSmokingHistory)
  const procedures = resources
    .filter(procedureIsSurgical)
    .map((resource) => conceptText(resource.code))
    .filter(Boolean)
  const clinicalCodings = buildFhirClinicalCodings(resources, {
    includeCondition: conditionIsHistorical,
    conditionFields: (resource) => {
      const value = conceptText(resource.code)
      const codes = (resource.code?.coding || []).map(
        (coding) => coding.code,
      )
      return [
        'chronic',
        ...['cardio', 'neuro', 'abdomen_hx'].filter((route) =>
          matchesConditionRoute(value, route, codes),
        ),
      ]
    },
    includeProcedure: procedureIsSurgical,
  })

  const prefill = {
    source: 'fhir',
    clinical_codings: clinicalCodings,
    name: name === '未命名病人' ? undefined : name,
    gender,
    birth_date: birthDate || undefined,
    blood_type: bloodType || undefined,
    chronic: joinClinicalValues(chronicHistoryValues) || undefined,
    smoke: joinClinicalValues(smokingHistoryValues) || undefined,
    past_meds:
      joinClinicalValues([
        ...pastMedications,
        answerFor('past-meds', 'past-medications', 'medication-history'),
      ]) || undefined,
    current_meds:
      joinClinicalValues([
        ...activeMedications,
        answerFor('medication', 'current-medications'),
      ]) || undefined,
    allergy:
      joinClinicalValues([
        ...allergyResources,
        answerFor('allergy', 'allergies'),
      ]) || undefined,
    cardio:
      joinClinicalValues([
        ...historicalConditionResources
          .filter((resource) =>
            matchesConditionRoute(
              conceptText(resource.code),
              'cardio',
              (resource.code?.coding || []).map((coding) => coding.code),
            ),
          )
          .map((resource) => conceptText(resource.code)),
        ...historyValues.filter((value) =>
          matchesConditionRoute(value, 'cardio', []),
        ),
        answerFor(
          'cardio',
          'cardiac-history',
          'cardiopulmonary-history',
        ),
      ]) || undefined,
    neuro:
      joinClinicalValues([
        ...historicalConditionResources
          .filter((resource) =>
            matchesConditionRoute(
              conceptText(resource.code),
              'neuro',
              (resource.code?.coding || []).map((coding) => coding.code),
            ),
          )
          .map((resource) => conceptText(resource.code)),
        ...historyValues.filter((value) =>
          matchesConditionRoute(value, 'neuro', []),
        ),
        answerFor('neuro', 'neurological-history'),
      ]) || undefined,
    abdomen_hx:
      joinClinicalValues([
        ...historicalConditionResources
          .filter((resource) =>
            matchesConditionRoute(
              conceptText(resource.code),
              'abdomen_hx',
              (resource.code?.coding || []).map((coding) => coding.code),
            ),
          )
          .map((resource) => conceptText(resource.code)),
        ...historyValues.filter((value) =>
          matchesConditionRoute(value, 'abdomen_hx', []),
        ),
        answerFor(
          'abdomen-hx',
          'abdomen_hx',
          'abdominal-history',
        ),
      ]) || undefined,
    surgery:
      joinClinicalValues([
        ...procedures,
        answerFor(
          'surgery',
          'surgical-history',
          'procedure-history',
        ),
      ]) || undefined,
  }

  // 核心人口學資料完整時不重問基本問卷；缺少血型時保留明確標記。
  if (prefill.name && prefill.gender && prefill.birth_date) {
    prefill.blood_type ||= 'FHIR 未提供'
  }
  return prefill
}

export const fhirBaseUrl = resolveFhirBaseUrl()
export const directFhirEnabled = isDirectFhirEnabled()
