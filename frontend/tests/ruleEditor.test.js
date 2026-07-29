import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getRuleSaveChecks,
  getRuleSaveValidationError,
} from '../src/services/ruleEditor.js'

function completeInput(overrides = {}) {
  return {
    authorized: true,
    editing: true,
    selectedCount: 1,
    changeNote: '更新視力異常規則',
    confirmation: '更新安全規則',
    confirmationText: '更新安全規則',
    ...overrides,
  }
}

test('allows surrounding confirmation whitespace like the backend', () => {
  const checks = getRuleSaveChecks(
    completeInput({ confirmation: '  更新安全規則  ' }),
  )

  assert.equal(checks.every((check) => check.complete), true)
  assert.equal(getRuleSaveValidationError(checks), '')
})

test('reports every missing rule-save requirement', () => {
  const checks = getRuleSaveChecks(
    completeInput({
      selectedCount: 0,
      changeNote: '短',
      confirmation: '錯誤文字',
    }),
  )

  assert.equal(checks[0].complete, true)
  assert.equal(checks[1].complete, false)
  assert.equal(checks[2].complete, false)
  assert.equal(checks[3].complete, false)
  assert.equal(
    getRuleSaveValidationError(checks),
    '尚未完成：至少選取一個 Safety 標籤並開啟草稿、變更理由至少 4 個字、確認文字為「更新安全規則」',
  )
})
