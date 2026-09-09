import assert from 'node:assert/strict'
import test from 'node:test'

import {
  PATIENT_IDENTIFIER_TYPES,
  SYNTHEA_DEFAULT_ID_SYSTEM,
  buildFhirPatientContext,
  buildPatientPrefill,
  findPatientBySyntheaDefaultId,
  isDirectFhirEnabled,
  isPatientIdentifierFormat,
  normalizePatientIdentifier,
  resolveFhirBaseUrl,
} from '../packages/shared/src/services/fhir.js'

function jsonResponse(payload, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => payload,
  }
}

test('shared FHIR service ignores production and unallowlisted query overrides', () => {
  const location = {
    search: '?directFhir=1&fhir=https://attacker.example/r4',
    protocol: 'https:',
    hostname: 'patient.example.test',
  }

  assert.equal(
    resolveFhirBaseUrl(location, 'https://fhir.example.test/r4', {
      developmentMode: false,
      queryOverrideEnabled: 'true',
      queryOverrideOrigins: 'https://attacker.example',
    }),
    'https://fhir.example.test/r4',
  )
  assert.equal(
    resolveFhirBaseUrl(location, 'https://fhir.example.test/r4', {
      developmentMode: true,
      queryOverrideEnabled: 'true',
      queryOverrideOrigins: 'https://fhir.example.test',
    }),
    'https://fhir.example.test/r4',
  )
  assert.equal(isDirectFhirEnabled(location, 'false', false, 'true'), false)
})

test('shared FHIR service preserves a configured relative proxy base', () => {
  assert.equal(
    resolveFhirBaseUrl(
      {
        search: '?fhir=https://attacker.example/r4',
        protocol: 'https:',
        hostname: 'patient.example.test',
      },
      '/fhir-proxy/',
    ),
    '/fhir-proxy',
  )
})

test('shared FHIR service accepts only an explicit allowlisted development origin', () => {
  const location = {
    search: '?fhir=http://localhost:8181/fhir',
    protocol: 'http:',
    hostname: 'localhost',
  }

  assert.equal(
    resolveFhirBaseUrl(location, '', {
      developmentMode: true,
      queryOverrideEnabled: 'true',
      queryOverrideOrigins: 'http://localhost:8181',
    }),
    'http://localhost:8181/fhir',
  )
})

test('shared FHIR history keeps Dementia but excludes an approved current symptom', () => {
  const currentEncounterCondition = (text) => ({
    resourceType: 'Condition',
    category: [{ text: 'Current encounter symptom' }],
    code: { text },
  })
  const prefill = buildPatientPrefill({
    patient: {
      name: [{ text: 'Synthetic boundary patient' }],
      gender: 'female',
      birthDate: '1940-01-01',
    },
    resources: [
      currentEncounterCondition('Dementia'),
      currentEncounterCondition('Fever'),
    ],
  })

  assert.match(prefill.chronic, /Dementia/)
  assert.doesNotMatch(prefill.chronic, /Fever/)
})

test('shared FHIR service validates and queries Synthea identifiers', async () => {
  const defaultId = 'c85baeef-9dbd-d06f-791d-5e1e3f24a8bf'
  let request
  const patient = await findPatientBySyntheaDefaultId(defaultId.toUpperCase(), {
    baseUrl: 'http://localhost:8081/fhir',
    fetchImpl: async (url, options) => {
      request = { url, options }
      return jsonResponse({
        resourceType: 'Bundle',
        entry: [{ resource: { resourceType: 'Patient', id: 'synthea-patient' } }],
      })
    },
  })

  assert.equal(patient.id, 'synthea-patient')
  assert.equal(
    request.options.body.get('identifier'),
    `${SYNTHEA_DEFAULT_ID_SYSTEM}|${defaultId}`,
  )
  assert.equal(
    normalizePatientIdentifier(
      PATIENT_IDENTIFIER_TYPES.SYNTHEA_DEFAULT_ID,
      defaultId.toUpperCase(),
    ),
    defaultId,
  )
  assert.equal(
    isPatientIdentifierFormat(PATIENT_IDENTIFIER_TYPES.SYNTHEA_DEFAULT_ID, defaultId),
    true,
  )
})

test('shared FHIR service builds only the narrow patient context', () => {
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
})
