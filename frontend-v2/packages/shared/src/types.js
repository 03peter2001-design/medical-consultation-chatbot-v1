/**
 * @typedef {Object} Invitation
 * @property {string} invite_id
 * @property {string} public_url
 * @property {string} expires_at
 * @property {'active'|'consumed'|'expired'|'revoked'} status
 */

/**
 * @typedef {Object} DoctorBootstrap
 * @property {string} access_token
 * @property {string} csrf_token
 * @property {string[]} scopes
 * @property {string=} expires_at
 * @property {Record<string, unknown>=} doctor
 * @property {Record<string, unknown>=} encounter
 */

/**
 * @typedef {Object} PhysicianSummarySection
 * @property {string} key
 * @property {string} label
 * @property {string} value
 * @property {true} confirmed
 */

/**
 * @typedef {Object} FhirPatientContextResponse
 * @property {string} issuer
 * @property {string} patient_id
 * @property {string=} encounter_id
 */

/**
 * @typedef {Object} FhirSubmissionResponse
 * @property {string} resource_id
 * @property {string} version_id
 * @property {string} submitted_at
 */

/**
 * @typedef {Object} FhirCompositionCreateRequest
 * @property {string} expected_updated_at
 * @property {PhysicianSummarySection[]} sections
 */

/**
 * @typedef {FhirSubmissionResponse & {
 *   status: 'created'|'existing',
 *   patient_reference: string,
 *   encounter_reference?: string
 * }} FhirCompositionCreateResponse
 */

/**
 * Fields added to the doctor consultation response by the FHIR write-back
 * workflow. This supplements the existing untyped clinical record payload.
 * @typedef {Object} ConsultationFhirFields
 * @property {string} updated_at
 * @property {FhirPatientContextResponse|null=} fhir_context
 * @property {FhirSubmissionResponse|null=} fhir_submission
 * @property {PhysicianSummarySection[]=} fhir_summary_sections
 */

/**
 * @typedef {Object} PatientSession
 * @property {string} status
 * @property {string=} expires_at
 * @property {Record<string, unknown>=} consultation
 */

export {}
