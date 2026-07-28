# AMIE 規則檔

`safety_rules.json` 是目前主訴解析與安全分流的單一規則來源，包含：

- 問卷路由關鍵詞與 LLM 可用的 finding 代碼
- 少量高特異性原文 fallback 規則
- LLM 語意正規化準則與標準概念定義
- 結構化語意規則
- FHIR 病史欄位與風險比對模式
- 否定詞與否定判斷範圍

Python 僅負責載入、驗證及執行規則。修改 JSON 後需重啟後端，規則才會
重新載入。

`raw_rules` 不應窮舉所有口語、同義詞或錯字；它只保留在模型不可用時仍
必須直接辨識的明確表達。一般自然語言由 `semantic_extraction` 正規化，
再交由 `structured_rules` 判斷。若語意抽取失敗，系統會轉交醫療人員，
不會靜默當成 routine。

語意 Safety 會在入口主訴及後續每一輪臨床回答執行；姓名、生日等基本
身分欄位不會送入這個抽取流程。

問卷的標準選項可在各 `questionnaire_data/*.json` 題目下使用
`semantic_options` 直接映射為 onset、severity、new_or_changed 或
findings。這些答案不需要再次呼叫 LLM 做語意抽取；只有自由文字、
「其他」及無法驗證為標準選項的輸入才會呼叫抽取器。

## 結構化條件

每一筆 `structured_rules[].when` 內的條件是 AND 關係。可用條件：

- `primary_in`
- `severity_in`
- `onset_in`
- `new_or_changed_in`
- `all_findings` / `any_findings`
- `all_risks` / `any_risks`

例如「頭痛、程度 severe，且存在任一視覺 finding」：

```json
{
  "code": "semantic_severe_headache_visual_change",
  "label": "劇烈頭痛合併視覺異常",
  "level": "urgent",
  "when": {
    "primary_in": ["headache"],
    "severity_in": ["severe"],
    "any_findings": ["blurred_vision", "diplopia", "vision_loss"]
  }
}
```

規則檔會在啟動時驗證。不存在的 route、finding、FHIR risk、重複 code、
無效正規表示式或不支援的條件都會阻止服務啟動，以避免錯誤規則靜默上線。
