import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildPatientPrefill,
  isDirectFhirEnabled,
  resolveFhirBaseUrl,
} from '../packages/shared/src/services/fhir.js'

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
