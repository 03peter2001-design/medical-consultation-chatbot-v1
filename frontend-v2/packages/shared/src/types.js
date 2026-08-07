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
 * @typedef {Object} PatientSession
 * @property {string} status
 * @property {string=} expires_at
 * @property {Record<string, unknown>=} consultation
 */

export {}
