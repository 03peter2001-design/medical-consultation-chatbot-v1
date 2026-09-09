import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  PATIENT_IDENTIFIER_TYPES,
  SYNTHEA_DEFAULT_ID_SYSTEM,
  TAIWAN_ID_SYSTEM,
  buildPatientPrefill,
  buildFhirPatientContext,
  findPatientByNationalId,
  findPatientBySyntheaDefaultId,
  isDirectFhirEnabled,
  isNationalIdFormat,
  isSyntheaDefaultIdFormat,
  loadPatientByNationalId,
  loadPatientBySyntheaDefaultId,
  normalizeNationalId,
  normalizeSyntheaDefaultId,
  patientAge,
  patientDisplayName,
  resolveFhirBaseUrl,
} from '../src/services/fhir.js'

const startOverlaySource = readFileSync(
  new URL('../src/components/StartConsultationOverlay.vue', import.meta.url),
  'utf8',
)
const patientViewSource = readFileSync(
  new URL('../src/views/PatientView.vue', import.meta.url),
  'utf8',
)

function jsonResponse(payload, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => payload,
  }
}

test('resolves the HAPI base URL from the frontend hostname', () => {
  assert.equal(
    resolveFhirBaseUrl(
      {
        search: '',
        protocol: 'http:',
        hostname: '192.168.1.20',
      },
      '',
    ),
    'http://192.168.1.20:8080/fhir',
  )
})

test('preserves a configured same-origin FHIR proxy path', () => {
  assert.equal(
    resolveFhirBaseUrl(
      {
        search: '?fhir=https://attacker.example/fhir',
        protocol: 'https:',
        hostname: 'app.example.test',
      },
      '/fhir-proxy/',
    ),
    '/fhir-proxy',
  )
})

test('supports an explicitly enabled and allowlisted development FHIR override', () => {
  const location = {
    search: '?directFhir=1&fhir=http://localhost:8181/fhir/',
    protocol: 'http:',
    hostname: 'localhost',
  }
  assert.equal(isDirectFhirEnabled(location, 'true', true, 'true'), true)
  assert.equal(isDirectFhirEnabled(location, 'false', false), false)
  assert.equal(
    resolveFhirBaseUrl(location, '', {
      developmentMode: true,
      queryOverrideEnabled: 'true',
      queryOverrideOrigins: 'http://localhost:8181',
    }),
    'http://localhost:8181/fhir',
  )
})

test('ignores FHIR query overrides by default', () => {
  const location = {
    search: '?directFhir=1&fhir=https://attacker.example/fhir',
    protocol: 'https:',
    hostname: 'app.example.test',
  }
  assert.equal(resolveFhirBaseUrl(location, ''), 'https://app.example.test:8080/fhir')
  assert.equal(isDirectFhirEnabled(location, 'false', false, 'true'), false)
})

test('ignores FHIR query overrides outside development even when allowlisted', () => {
  const location = {
    search: '?fhir=https://fhir.example.test/r4',
    protocol: 'https:',
    hostname: 'app.example.test',
  }
  assert.equal(
    resolveFhirBaseUrl(location, 'https://configured.example/fhir', {
      developmentMode: false,
      queryOverrideEnabled: 'true',
      queryOverrideOrigins: 'https://fhir.example.test',
    }),
    'https://configured.example/fhir',
  )
})

test('ignores an unallowlisted development FHIR origin', () => {
  const location = {
    search: '?fhir=https://attacker.example/r4',
    protocol: 'https:',
    hostname: 'app.example.test',
  }
  assert.equal(
    resolveFhirBaseUrl(location, 'https://fhir.example.test/r4', {
      developmentMode: true,
      queryOverrideEnabled: 'true',
      queryOverrideOrigins: 'https://fhir.example.test',
    }),
    'https://fhir.example.test/r4',
  )
})

test('normalizes and validates the synthetic national ID', () => {
  assert.equal(normalizeNationalId(' a000000000 '), 'A000000000')
  assert.equal(isNationalIdFormat('A000000000'), true)
  assert.equal(isNationalIdFormat('SYN-CHEST-001'), false)
})

test('normalizes and validates a Synthea Default ID', () => {
  const defaultId = 'c85baeef-9dbd-d06f-791d-5e1e3f24a8bf'
  assert.equal(normalizeSyntheaDefaultId(` ${defaultId.toUpperCase()} `), defaultId)
  assert.equal(isSyntheaDefaultIdFormat(defaultId), true)
  assert.equal(isSyntheaDefaultIdFormat(`${defaultId}0`), false)
  assert.equal(isSyntheaDefaultIdFormat('syn-chest-001'), false)
})

test('offers an explicit Synthea identifier mode in the direct FHIR UI', () => {
  assert.match(startOverlaySource, /Synthea Default ID/)
  assert.match(startOverlaySource, /v-model="identifierType"/)
  assert.match(startOverlaySource, /@input="updatePatientIdentifier"/)
  assert.match(patientViewSource, /loadPatientByIdentifier/)
  assert.match(patientViewSource, /v-model:synthea-default-id/)
})

test('builds the narrow FHIR context persisted with a consultation', () => {
  assert.deepEqual(
    buildFhirPatientContext({
      patient: { id: 'patient-1' },
      smart: { patientId: 'patient-1', encounterId: 'encounter-1' },
    }),
    {
      patient_id: 'patient-1',
      encounter_id: 'encounter-1',
      source: 'smart',
    },
  )
  assert.deepEqual(
    buildFhirPatientContext({ patient: { id: 'patient-2' } }),
    { patient_id: 'patient-2', source: 'direct' },
  )
})

test('searches Patient.identifier using the TW Core national ID system', async () => {
  let request
  const patient = await findPatientByNationalId('A000000000', {
    baseUrl: 'http://localhost:8080/fhir',
    fetchImpl: async (url, options) => {
      request = { url, options }
      return jsonResponse({
        resourceType: 'Bundle',
        total: 1,
        entry: [
          {
            resource: {
              resourceType: 'Patient',
              id: 'syn-chest-001',
            },
          },
        ],
      })
    },
  })

  assert.equal(patient.id, 'syn-chest-001')
  assert.equal(request.url, 'http://localhost:8080/fhir/Patient/_search')
  assert.equal(request.options.method, 'POST')
  assert.equal(
    request.options.body.get('identifier'),
    `${TAIWAN_ID_SYSTEM}|A000000000`,
  )
})

test('searches Patient.identifier using the Synthea Default ID system', async () => {
  const defaultId = 'c85baeef-9dbd-d06f-791d-5e1e3f24a8bf'
  let request
  const patient = await findPatientBySyntheaDefaultId(defaultId.toUpperCase(), {
    baseUrl: 'http://localhost:8081/fhir',
    fetchImpl: async (url, options) => {
      request = { url, options }
      return jsonResponse({
        resourceType: 'Bundle',
        total: 1,
        entry: [
          {
            resource: {
              resourceType: 'Patient',
              id: 'hapi-assigned-patient-id',
            },
          },
        ],
      })
    },
  })

  assert.equal(patient.id, 'hapi-assigned-patient-id')
  assert.equal(request.url, 'http://localhost:8081/fhir/Patient/_search')
  assert.equal(request.options.method, 'POST')
  assert.equal(
    request.options.body.get('identifier'),
    `${SYNTHEA_DEFAULT_ID_SYSTEM}|${defaultId}`,
  )
})

test('rejects an invalid Synthea Default ID before contacting HAPI', async () => {
  let fetchCalled = false
  await assert.rejects(
    findPatientBySyntheaDefaultId('not-a-uuid', {
      fetchImpl: async () => {
        fetchCalled = true
        return jsonResponse({})
      },
    }),
    /Synthea Default ID 格式/,
  )
  assert.equal(fetchCalled, false)
})

test('fails closed when a Synthea Default ID is missing or duplicated', async () => {
  const defaultId = 'c85baeef-9dbd-d06f-791d-5e1e3f24a8bf'
  await assert.rejects(
    findPatientBySyntheaDefaultId(defaultId, {
      fetchImpl: async () => jsonResponse({ resourceType: 'Bundle', total: 0 }),
    }),
    /Synthea Default ID.*查無|\u67e5無.*Synthea Default ID/,
  )
  await assert.rejects(
    findPatientBySyntheaDefaultId(defaultId, {
      fetchImpl: async () =>
        jsonResponse({
          resourceType: 'Bundle',
          entry: [
            { resource: { resourceType: 'Patient', id: 'one' } },
            { resource: { resourceType: 'Patient', id: 'two' } },
          ],
        }),
    }),
    /找到 2 位病人/,
  )
})

test('loads the patient compartment after resolving the Patient id', async () => {
  const urls = []
  const result = await loadPatientByNationalId('A000000000', {
    baseUrl: 'http://localhost:8080/fhir',
    fetchImpl: async (url) => {
      urls.push(url)
      if (url.endsWith('/Patient/_search')) {
        return jsonResponse({
          resourceType: 'Bundle',
          entry: [
            {
              resource: {
                resourceType: 'Patient',
                id: 'syn-chest-001',
                name: [{ text: '合成胸痛測試病人' }],
              },
            },
          ],
        })
      }
      return jsonResponse({
        resourceType: 'Bundle',
        entry: [
          {
            resource: {
              resourceType: 'Patient',
              id: 'syn-chest-001',
            },
          },
          {
            resource: {
              resourceType: 'Encounter',
              id: 'syn-chest-001',
            },
          },
        ],
      })
    },
  })

  assert.equal(result.resources.length, 2)
  assert.match(urls[1], /Patient\/syn-chest-001\/\$everything/)
})

test('loads Synthea patient data using the HAPI Patient id returned by search', async () => {
  const defaultId = 'c85baeef-9dbd-d06f-791d-5e1e3f24a8bf'
  const urls = []
  await loadPatientBySyntheaDefaultId(defaultId, {
    baseUrl: 'http://localhost:8081/fhir',
    fetchImpl: async (url) => {
      urls.push(url)
      if (url.endsWith('/Patient/_search')) {
        return jsonResponse({
          resourceType: 'Bundle',
          entry: [
            {
              resource: {
                resourceType: 'Patient',
                id: 'server-patient-123',
              },
            },
          ],
        })
      }
      return jsonResponse({ resourceType: 'Bundle', entry: [] })
    },
  })

  assert.match(urls[1], /Patient\/server-patient-123\/\$everything/)
  assert.doesNotMatch(urls[1], new RegExp(defaultId))
  assert.equal(
    PATIENT_IDENTIFIER_TYPES.SYNTHEA_DEFAULT_ID,
    'synthea-default-id',
  )
})

test('formats patient identity data for the intake flow', () => {
  const patient = {
    name: [{ use: 'official', text: '合成胸痛測試病人' }],
    birthDate: '1968-04-12',
  }
  assert.equal(patientDisplayName(patient), '合成胸痛測試病人')
  assert.equal(patientAge(patient.birthDate, new Date(2026, 6, 27)), 58)
})

test('builds a backend prefill and marks missing FHIR blood type', () => {
  const prefill = buildPatientPrefill({
    patient: {
      name: [{ text: '合成測試病人' }],
      gender: 'male',
      birthDate: '1968-04-12',
    },
    resources: [
      {
        resourceType: 'QuestionnaireResponse',
        item: [
          {
            linkId: 'history',
            answer: [
              {
                valueString:
                  '有高血壓，吸菸約30年；否認已知冠心症病史',
              },
            ],
          },
          {
            linkId: 'allergy',
            answer: [{ valueString: '否認已知藥物過敏' }],
          },
        ],
      },
    ],
  })

  assert.equal(prefill.name, '合成測試病人')
  assert.equal(prefill.gender, '男性')
  assert.equal(prefill.birth_date, '1968-04-12')
  assert.equal(prefill.blood_type, 'FHIR 未提供')
  assert.equal(prefill.smoke, '吸菸約30年')
  assert.equal(prefill.chronic, '有高血壓')
  assert.match(prefill.cardio, /有高血壓/)
  assert.match(prefill.cardio, /否認已知冠心症病史/)
  assert.equal(prefill.allergy, '否認已知藥物過敏')
})

test('reads ABO blood type from a FHIR observation', () => {
  const prefill = buildPatientPrefill({
    patient: {
      name: [{ text: '測試病人' }],
      gender: 'female',
      birthDate: '1990-01-01',
    },
    resources: [
      {
        resourceType: 'Observation',
        code: {
          coding: [
            {
              system: 'http://loinc.org',
              code: '882-1',
              display: 'ABO and Rh group [Type] in Blood',
            },
          ],
        },
        valueCodeableConcept: {
          coding: [{ code: 'AB', display: 'AB' }],
        },
      },
    ],
  })
  assert.equal(prefill.blood_type, 'AB型')
  assert.deepEqual(prefill.clinical_codings, [
    {
      field: 'blood_type',
      system: 'http://loinc.org',
      code: '882-1',
      display: 'ABO and Rh group [Type] in Blood',
      source: 'fhir',
    },
  ])
})

test('maps FHIR conditions procedures and medications to questionnaire fields', () => {
  const problem = (text) => ({
    resourceType: 'Condition',
    category: [
      {
        coding: [{ code: 'problem-list-item' }],
      },
    ],
    code: { text },
  })
  const prefill = buildPatientPrefill({
    patient: {
      name: [{ text: '病史測試病人' }],
      gender: 'female',
      birthDate: '1980-01-01',
    },
    resources: [
      problem('高血壓'),
      problem('癲癇'),
      problem('腎結石'),
      {
        resourceType: 'Condition',
        category: [
          {
            text: '本次就醫確認之症狀',
            coding: [{ code: 'encounter-diagnosis' }],
          },
        ],
        code: { text: '本次胸痛' },
      },
      {
        resourceType: 'Procedure',
        status: 'completed',
        category: { text: 'Surgical procedure' },
        code: { text: 'Coronary artery bypass grafting' },
      },
      {
        resourceType: 'MedicationStatement',
        status: 'active',
        medicationCodeableConcept: { text: '阿斯匹靈' },
      },
      {
        resourceType: 'MedicationStatement',
        status: 'completed',
        medicationCodeableConcept: { text: '抗組織胺' },
      },
    ],
  })

  assert.match(prefill.chronic, /高血壓/)
  assert.match(prefill.chronic, /癲癇/)
  assert.match(prefill.chronic, /腎結石/)
  assert.doesNotMatch(prefill.chronic, /本次胸痛/)
  assert.equal(prefill.cardio, '高血壓')
  assert.equal(prefill.neuro, '癲癇')
  assert.equal(prefill.abdomen_hx, '腎結石')
  assert.equal(prefill.surgery, 'Coronary artery bypass grafting')
  assert.equal(prefill.current_meds, '阿斯匹靈')
  assert.equal(prefill.past_meds, '抗組織胺')
})

test('excludes approved current symptoms but preserves current chronic diagnoses', () => {
  const currentEncounterCondition = (text) => ({
    resourceType: 'Condition',
    category: [{ text: '本次就醫確認之症狀' }],
    code: { text },
  })
  const prefill = buildPatientPrefill({
    patient: {
      name: [{ text: '合成病史邊界測試病人' }],
      gender: 'female',
      birthDate: '1940-01-01',
    },
    resources: [
      currentEncounterCondition('Dementia'),
      currentEncounterCondition('本次發燒'),
    ],
  })

  assert.match(prefill.chronic, /Dementia/)
  assert.doesNotMatch(prefill.chronic, /本次發燒/)
})

test('preserves CodeableConcept text with a source FHIR disease coding', () => {
  const prefill = buildPatientPrefill({
    patient: {
      name: [{ text: '病史編碼測試病人' }],
      gender: 'male',
      birthDate: '1980-01-01',
    },
    resources: [
      {
        resourceType: 'Condition',
        category: [
          {
            coding: [{ code: 'problem-list-item' }],
          },
        ],
        code: {
          text: '高血壓',
          coding: [
            {
              system: 'http://snomed.info/sct',
              code: '38341003',
              display: 'Hypertensive disorder',
            },
          ],
        },
      },
    ],
  })

  assert.equal(prefill.clinical_codings[0].code, '38341003')
  assert.equal(prefill.clinical_codings[0].text, '高血壓')
})

test('keeps past encounter neuro diagnoses and maps neuro surgery', () => {
  const prefill = buildPatientPrefill({
    patient: {
      name: [{ text: '神經病史測試病人' }],
      gender: 'male',
      birthDate: '1970-01-01',
    },
    resources: [
      {
        resourceType: 'Condition',
        category: [
          { coding: [{ code: 'encounter-diagnosis' }] },
        ],
        code: {
          coding: [
            {
              system: 'http://snomed.info/sct',
              code: '230690007',
              display: 'Stroke',
            },
          ],
        },
      },
      {
        resourceType: 'Condition',
        code: {
          coding: [
            {
              system: 'http://snomed.info/sct',
              code: '37796009',
            },
          ],
        },
      },
      {
        resourceType: 'Procedure',
        status: 'completed',
        code: { text: 'Clipping of intracranial aneurysm' },
      },
    ],
  })

  assert.match(prefill.neuro, /Stroke/)
  assert.match(prefill.neuro, /37796009/)
  assert.equal(prefill.surgery, 'Clipping of intracranial aneurysm')
  assert.ok(
    prefill.clinical_codings.some(
      (coding) =>
        coding.field === 'neuro' &&
        coding.system === 'http://snomed.info/sct' &&
        coding.code === '230690007',
    ),
  )
})
