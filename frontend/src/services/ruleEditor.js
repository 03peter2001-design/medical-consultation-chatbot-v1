export function getRuleSaveChecks({
  authorized,
  editing,
  selectedCount,
  changeNote,
  confirmation,
  confirmationText,
}) {
  return [
    {
      id: 'authorization',
      label: '管理權杖已驗證',
      complete: Boolean(authorized),
    },
    {
      id: 'selection',
      label: '至少選取一個 Safety 標籤並開啟草稿',
      complete: Boolean(editing) && Number(selectedCount) > 0,
    },
    {
      id: 'change_note',
      label: '變更理由至少 4 個字',
      complete: String(changeNote || '').trim().length >= 4,
    },
    {
      id: 'confirmation',
      label: `確認文字為「${confirmationText || ''}」`,
      complete:
        Boolean(confirmationText) &&
        String(confirmation || '').trim() === confirmationText,
    },
  ]
}

export function getRuleSaveValidationError(checks) {
  const missing = checks
    .filter((check) => !check.complete)
    .map((check) => check.label)
  return missing.length ? `尚未完成：${missing.join('、')}` : ''
}
