# 問卷資料

問卷依用途拆成六份 JSON：

- `chief.json`：自由主訴入口
- `basic.json`：基本資料
- `history.json`：共用病史
- `chest.json`：胸痛問卷
- `headache.json`：頭痛問卷
- `abdomen.json`：腹痛問卷

後端啟動時載入 `chief`、`basic`、`history`；疾病問卷會在主訴路由完成
後才載入，並由 `backend/questionnaires.py` 快取。

每個問題至少需要：

```json
{
  "field": "欄位名稱",
  "prompt": "顯示問題",
  "kind": "text"
}
```

支援的 `kind` 為 `text`、`choice`、`date`、`duration`。選擇題必須提供
`options`；時間題必須提供 `quick_options` 與 `units`。條件題可使用：

```json
{
  "condition": {
    "field": "前一個欄位",
    "contains_any": ["觸發文字"]
  }
}
```

JSON 格式、重複欄位、輸入型態與選項設定會在載入時驗證；格式錯誤時後端
會直接回報檔名與問題欄位，不會靜默略過。
