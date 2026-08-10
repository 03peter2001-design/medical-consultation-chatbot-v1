# 問卷資料

問卷依用途拆成共用問卷、3 條目前核准的執行期路由，以及 49 份待簽核候選資料：

- `chief.json`：自由主訴入口
- `basic.json`：基本資料
- `history.json`：共用病史
- `chest.json`、`headache.json`、`abdomen.json`：既有三痛問卷，使用
  `disease_vote` 與核准的 ClinicalFact／Safety 規則
- 其餘 49 份：由 `docs/疾病問卷.txt` 產生的 `source_structured_provisional`
  candidate，使用 `fixed_order` 並保留來源 SHA、pipeline 與模型 provenance；
  未經臨床簽核時不會加入 `DISEASE_ROUTES`、主訴分類或病患問卷
- `domain/questionnaire_routes.json`：所有路由的顯示名稱、可驗證關鍵字與
  入口處置（`questionnaire`、`handoff`、`urgent`）

後端啟動時載入 `chief`、`basic`、`history`；只有已核准疾病問卷會在主訴路由
完成後 lazy-load，並由 `domain/questionnaires.py` 快取。candidate 檔案仍會接受
schema／來源完整性測試，但 `build_questionnaire` 對它們 fail closed。

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

JSON 格式、重複欄位、輸入型態、選項設定、條件欄位順序與路由目錄同步性
會在載入時驗證；格式錯誤時後端會直接回報檔名與問題欄位，不會靜默略過。

疾病問卷另有 `policy`。目前 schema version 2 保留固定疾病表投票，並以
`priority_fields`、`required_fields`、一般問題作為選題層級；同層問題再依當輪
ClinicalFact 建立的疾病漏斗排序。`frontier_vote_margin` 定義領先群與第一名可容許
的淨票差，`frontier_max_candidates` 限制有支持票時最多追蹤的候選數。無支持票時
仍會用全部疾病進行廣泛區辨。`coverage_threshold` 與 `max_turns` 只控制完成與轉交，
不參與漏斗候選篩選。

`source_structured_provisional` 只表示來源結構已驗證，並不表示已完成獨立臨床
審查。候選路由的 keywords、`disposition`、`clinical_domain` 與題目內容均不會因
檔案存在而上線；必須先用具 reviewer、日期、問卷來源與 route catalog hash、逐路由核准與 review-note
處理紀錄的 signoff manifest 重新 promotion，輸出 `clinically_approved` 文件後，
才會在下一次啟動成為執行期路由。
