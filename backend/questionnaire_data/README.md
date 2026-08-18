# 問卷資料

問卷依用途拆成共用問卷、3 條目前核准的執行期路由，以及 49 份待簽核候選資料：

- `chief.json`：自由主訴入口
- `basic.json`：基本資料
- `history.json`：共用病史
- `chest.json`、`headache.json`、`abdomen.json`：既有三痛問卷；預設 runtime 依
  檔案順序逐題詢問，舊 `disease_vote` policy 只供明示啟用的 AMIE 相容流程
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

## 病患問診流程文案

題目本身仍由各問卷的 `questions[].prompt` 管理；開場、上一題、輸入錯誤、section
轉場、完成、儘早就醫與人工轉交等組裝文案，統一放在
[`ui/patient_messages.json`](ui/patient_messages.json)。要調整數位醫療助理的固定
話術時直接修改該檔，不需進入 `app/routes/patient.py`。

文案檔採固定 `schema_version: 1`、`locale: zh-TW` 與完整 key 集合。大括號內容是
程式提供的動態值，例如 `{prompt}`、`{queue_number}`、`{route_label}`；可以調整其
前後文字及位置，但不可刪除、改名或增加 placeholder。`domain.patient_messages`
會嚴格驗證所有 key 與 placeholder，避免問診進行到一半才因格式錯誤失敗。

修改後執行：

```bash
cd backend
venv/bin/python -m unittest tests.test_patient_messages tests.test_patient_back_navigation \
  tests.test_main_input_validation tests.test_patient_triage_payload tests.test_questionnaires
```

文案由 process cache 載入；本機 Uvicorn 或 Docker backend 必須重新啟動才會套用。
Avatar 朗讀的是組裝後的 `reply`，因此新的固定文案會一併生效。儘早就醫、安全轉交
等內容雖已資料化，仍屬臨床安全文案，修改後必須由合格人員審查；JSON 文案不得用來
改變 Safety 規則、問卷選題、路由 disposition 或完成條件。

預設 `questionnaire` pipeline 不讀取 `policy` 來選題或提前停止，只依組合後的
JSON 順序、`condition` 與 FHIR prefill 決定下一題，也不執行 semantic options、
ClinicalFact、Safety 或疾病票數。最後一題完成後，後端才將所有已回答題目的
`prompt` 與患者答案連同院方預填資料交給 Gemini；EMR、初步鑑別、防漏診、理學檢查、
檢驗與影像各使用一個獨立 prompt，逐題期間仍不會呼叫模型。完成時會以新 RAG 分別
取得鑑別／危險徵兆、檢驗、影像三組文獻，各任務只收到相關文獻；六題全部通過格式
驗證後才組裝與保存。六個模型 API request 由程式依固定順序逐一送出，不靠 prompt
文字要求模型自行分題。A／B／C 由 Backend 分別以 `diagnosis|workup`、`lab`、
`imaging` metadata filter 直接查詢 v2 Chroma，不由 prompt 要求模型自行找知識庫；
防漏診題產生的最多五個疾病會先經 schema 驗證，再以 `focus_conditions` 傳給理學檢查、
檢驗與影像三題。最後輸出為 doctor-style 英文內容，不顯示 rationale，並保留既有六段
中文標題供前端分段；任一題失敗不會建立半成品病例。疾病問卷仍
保留 `policy` 供舊 AMIE 相容流程；目前 schema
version 2 以
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

疾病名稱導向 Gemini＋RAG 產生的 fact／semantic／profile／Safety 提案不存放於本目錄，
而是隔離在 `questionnaire_drafts/clinical_artifacts/`。這些 overlay 不會回填此處仍為空的
candidate `semantic_options`，也不能由 questionnaire-only promoter 帶入 runtime；其
`complete` 僅代表生成檔案齊全，不是 clinical signoff。

## 產生台語問卷副本

[`translate_to_taigi.py`](translate_to_taigi.py) 會使用固定 revision 的
`Bohanlu/Taigi-Llama-2-Translator-7B`，依官方 `[TRANS] ... [HAN]` prompt 將本目錄
55 份問卷與 `ui/patient_messages.json` 的顯示文字轉為台語漢字，並把完整副本輸出到
`tai/`。原始國語 JSON 不會被修改；欄位 ID、policy、clinical code 與 semantic value
保持不變，引用選項文字的條件及 mapping key 則同步翻譯。

建議在獨立生成環境安裝 `torch`、`transformers`、`accelerate` 與 `sentencepiece`。
模型約 13.9 GB，第一次執行會由 Hugging Face 下載；CPU 可執行但耗時較長：

```bash
cd backend/questionnaire_data
python translate_to_taigi.py --dry-run
python translate_to_taigi.py --device cuda --batch-size 4
python translate_to_taigi.py --check
```

腳本逐批寫入 `tai/.translation-cache.json`，中斷後可直接重跑續傳；要忽略 cache 可加
`--force`。`tai/_translation_manifest.json` 會記錄來源與輸出 SHA-256、模型 revision、
生成參數與 CC BY-NC-SA 4.0 授權。所有生成內容皆為
`machine_translated_unreviewed`，正式使用前必須由合格的台語與臨床人員逐題審查，
不可因模型輸出而自動視為已發布或已核准。

Backend 只有在 `_translation_manifest.json` 的 `review_status` 改為
`clinically_reviewed`，且加入非空的 `review.reviewer`、`review.reviewed_on` 與
`review.scope` 後，才允許 `language=minnan` 建立問診 session。審查期間若修改任何
台語 JSON，須重新計算該檔 `output_sha256`；國語來源若有更新，則必須重新產生並重新
審查。問診開始後語言會鎖定；台語只用於 prompt／label／病患顯示，儲存的結構化答案
仍採原國語 canonical value。
