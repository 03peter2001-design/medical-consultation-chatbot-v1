export function createEditableSummaryRows(rows = []) {
  return rows.map((row) => {
    const value = String(row?.value ?? '')
    return {
      ...row,
      value,
      originalValue: value,
      confirmed: row?.confirmed === true,
    }
  })
}

export function buildFhirCompositionRequest(rows = [], updatedAt = '') {
  if (!areAllSummaryRowsConfirmed(rows)) {
    throw new Error('請先確認所有醫師摘要欄位。')
  }
  const expectedUpdatedAt = String(updatedAt || '').trim()
  if (!expectedUpdatedAt) throw new Error('病例版本資訊不完整，請重新載入。')
  return {
    expected_updated_at: expectedUpdatedAt,
    sections: rows.map((row) => ({
      key: String(row.key || '').trim(),
      label: String(row.label || '').trim(),
      value: String(row.value || '').trim(),
      confirmed: true,
    })),
  }
}

export function updateEditableSummaryRow(row, value, rows = [row]) {
  row.value = String(value ?? '')
  rows.forEach((summaryRow) => {
    summaryRow.confirmed = false
  })
}

export function confirmEditableSummaryRows(rows = []) {
  if (!rows.length || rows.some((row) => !row.value.trim())) return false
  rows.forEach((row) => {
    row.confirmed = true
  })
  return true
}

export function areAllSummaryRowsConfirmed(rows = []) {
  return rows.length > 0 && rows.every((row) => row.confirmed)
}
