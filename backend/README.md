# 後端服務

`backend/` 是 FastAPI 應用、順序式問卷、SQLite repository、RAG 查詢服務與
FHIR／SNOMED 整合所在位置。舊 AMIE-inspired 引擎保留為明示回退選項，不是預設流程。

## 服務版本

目前版本：**v0.8.1（2026-08-18）**。

本次因主動撤除既有 AMIE／語意標籤能力並回到較小的實驗性功能面，版本線依專案
決策由 0 重新編碼。下方 `v1.x` 條目保留為舊能力線的歷史紀錄，不表示 `v0.3.0`
在 SemVer 上高於它們。

此版本號是依 `devlog/2026-07-27.md` 至 `devlog/2026-08-07.md` 回溯整理的
後端服務文件基線，目前沒有對應的 Git tag 或獨立 release；它也不表示其中的
疾病表、Safety 規則、問卷或其他臨床內容已取得臨床核准。

服務版本與下列既有版本機制彼此獨立，不可互相替代：

- API 的 `/v1` 是 HTTP 契約前綴，不是後端服務的 SemVer。
- SQLite schema version 是資料庫遷移版本；本基線於 2026-08-05 升至 version 6。
- RAG v2 是檢索索引與 collection 世代，可透過 `RAG_INDEX_VERSION` 選擇。
- Safety 規則、ClinicalFact catalog、疾病 profile 與問卷 schema／內容各有自己的
  revision、version 及審查狀態，發布時仍須遵循原有治理與稽核流程。

### v0.8.1 (2026-08-18)

- `questionnaire_data/tai/` 現在明確忽略本機產生的翻譯 manifest、問卷 JSON 與 UI
  文案，避免 `machine_translated_unreviewed` 產物被誤加入功能 commit；本機檔案不會
  被刪除，Backend 的 fail-closed 審核閘門也不變。
- 56 份 manifest source／output hashes 與目前檔案一致，但 UI 文案仍可見模型格式標記、
  重複翻譯與混語殘留；完整性驗證不等於語言或臨床正確性審核。
- 這項 ignore 規則不代表問卷已核准。完成合格台語與臨床逐題審查後，promotion 變更
  必須同時移除對應 ignore、記錄真實 reviewer／日期／範圍，並提交與審後內容一致的
  source／output hashes。
- 直接執行現有 validator 確認目前資產因 `machine_translated_unreviewed` 被拒絕；
  questionnaire localization 的 6 項審核閘門測試通過。

### v0.8.0 (2026-08-18)

- 固定問卷完成後的六段式總結改採 doctor-style 英文交班風格：EMR 使用
  Chief Complaint、Present Illness、Past History、Drug History 與 Allergy History，
  其餘段落直接列出診斷或檢查項目，不再要求或顯示 rationale。
- 防漏診題回傳的最多五個英文疾病會先經 Backend JSON schema 驗證，再以
  `focus_conditions` 明確傳入理學檢查、檢驗與影像三個後續 API request；不再依賴
  模型理解跨 request 的 “aforementioned five”。
- 保留六個 request 的固定順序、A／B／C 直接分區檢索、既有六段顯示標題、資料庫與
  HTTP 契約，以及任一題失敗便不建立病例的 fail-closed 行為。Prompt version 升為
  `fixed-questionnaire-doctor-style-english-v7`。
- 醫師 `structured_note` 與一般 RAG 對話維持繁體中文；`structured_note` 的防漏診文字
  會先通過 exact-key 驗證，再明確傳入理學檢查、檢驗與影像三個後續 request。
- 相關 prompt／問卷／RAG／醫師與背景報告測試 51 項通過；完整 Backend suite 執行
  399 項，其中 397 項通過，另 2 項只因未掛載外部 eHIS C# 原始碼而 error。

### v0.7.0 (2026-08-18)

- 六段式報告的 A／B／C 不再只是不同 query 關鍵字：Backend 現在直接把 A 綁定至
  `diagnosis|workup`、B 綁定至 `lab`、C 綁定至 `imaging`，並以 Chroma
  `clinical_stage` metadata filter 限制每次檢索。
- 固定問卷、醫師 `structured_note` 與舊背景結構化報告統一經由具名 A／B／C adapter
  取得 evidence；來源紀錄新增 `knowledge_base` 與 `clinical_stage` provenance。
- Prompt 不再要求模型自行尋找或選擇知識庫，只接收 Backend 已取回的
  `retrieved_evidence`。固定問卷 prompt version 升為
  `fixed-questionnaire-direct-abc-rag-v6`。
- A／B／C metadata 分區需要 `RAG_INDEX_VERSION=v2`；legacy 索引缺少可保證的 stage
  partition，因此保留舊有 purpose-query 相容檢索，來源明確標示
  `partition_mode=legacy_unpartitioned`，不會被誤記為已完成 metadata 分區。
- 本機 v2 Chroma 合成查詢確認 A 只回傳 `diagnosis|workup`、B 只回傳 `lab`、C 只回傳
  `imaging`。聚焦 RAG／prompt／問卷／醫師 session／報告測試共 49 項通過；完整
  Backend suite 397 項中 395 項通過，另 2 項只因未掛載外部 eHIS 原始碼而 error。

### v0.6.1 (2026-08-18)

- 移除 prompt 內「每次只回答一個問題／不得順帶完成其他段落」等分題用 meta 指令；
  每個 API request 直接帶入該次要回答的實際問題與專屬 response schema。
- 固定問卷與醫師 `structured_note` 改為依固定任務順序逐次呼叫模型 API，不再以
  `asyncio.gather` 同時發送六題；舊背景報告本來即為逐題呼叫，維持相同行為。
- 固定問卷 prompt version 升為 `fixed-questionnaire-sequential-prompts-rag-v5`，保留
  新舊報告生成方式的 provenance 區分。
- 每次回應的 exact-key／欄位驗證、全部成功才組裝保存、失敗不建立半成品病例等安全
  邊界不變。聚焦 prompt、問卷、醫師 session 與報告測試共 38 項通過。

### v0.6.0 (2026-08-17)

- 固定問卷完成後的六段式 Gemini 報告改為 EMR、初步鑑別、防漏診、理學檢查、
  檢驗與影像各自一個 prompt；每題只收到所需的 A／B／C 文獻區塊，prompt version
  升為 `fixed-questionnaire-section-prompts-rag-v4`。
- 醫師 `structured_note` 模式同步拆成六個獨立問題；舊 AMIE 背景結構化報告則將仍由
  模型負責的 EMR、理學檢查、檢驗與影像拆成四題，固定疾病排名仍由後端規則產生。
- 各題回應採 task-specific JSON 與 exact-key 驗證，全部成功後才依既有標題順序組裝；
  固定問卷任一題失敗時維持 503、保留 session 答案且不建立半成品病例。
- HTTP request／response、資料庫欄位、六段式顯示標題及前端契約不變。模型呼叫數增加，
  因此延遲、Gemini 配額與費用可能高於舊單次請求；輸出仍是未經醫師確認的臨床草稿。
- 聚焦 prompt、固定問卷、醫師 session 與疾病報告測試共 38 項通過；完整 Backend
  suite 393 項中 391 項通過，另 2 項只因未掛載外部 eHIS 原始碼而 error。

### v0.5.2 (2026-08-17)

- 台語問卷的 `clinically_reviewed` manifest 除了必須提供非空的 reviewer、日期與範圍，
  現在也會拒絕文件範例中的占位審查者／範圍及無效 ISO 日期，避免未完成的人工作業被
  誤認為正式簽核。
- 本機產生的 56 份機器翻譯仍標記為 `machine_translated_unreviewed`，未納入 Git；
  Backend 在缺少真正人工審查資產時維持 503 fail closed。此版本不核准任何問卷內容。
- 新增占位審查紀錄 regression test；完整 Backend suite 共 388 項，其中 386 項通過，
  另 2 項只因本機未掛載外部 eHIS C# 原始碼而 error。

### v0.5.1 (2026-08-13)

- 台語 manifest 驗證現在分別回報「格式／模型 provenance 錯誤」、「尚未人工審核」與
  「缺少 reviewer／日期／範圍」，避免把有效但尚未簽核的機器翻譯誤報為格式錯誤。
- 未經合格台語及臨床人員審查的資產仍維持 503 fail closed；此修正不放寬臨床發布門檻。

### v0.5.0 (2026-08-13)

- `/v1/chat` 新增向後相容的 optional `language`，支援 `mandarin` 與 `minnan`；語言在
  問診建立時鎖定並保存，後續 request 省略時沿用，明示切換則以 409 拒絕且不改狀態。
- 台語問卷由 `questionnaire_data/tai/` 的獨立 JSON 顯示資產載入。Backend 驗證來源與
  輸出 SHA-256、模型 provenance、題目結構及具 reviewer／日期／範圍的
  `clinically_reviewed` manifest；缺檔、未審、過期、破損或含保留分隔符時 fail closed
  回 503，不會靜默混用國語。
- 問卷 prompt、選項、快捷時間與單位可顯示台語，但 API 仍以國語 canonical value 驗證、
  保存與交付 Gemini，保留既有條件、FHIR 預填、semantic mapping 與病例相容性；回應另
  提供台語 `user_display` 供病患聊天泡泡顯示。
- 新增固定 revision 的 Taigi-Llama-2-Translator-7B 離線產生器與翻譯 manifest；模型
  產物一律先標示 `machine_translated_unreviewed`，不可因生成完成而自動上線。
- 聚焦 localization／問卷 pipeline／back navigation／輸入驗證與 OpenAPI tests 通過；
  OpenAPI contract 及開發版 frontend 型別已同步。

### v0.4.0 (2026-08-11)

- Backend Avatar client 新增 `AVATAR_ANIMATION_ENABLED`（預設 `true`）；status、warm-up
  與影片生成統一使用後端設定的有效模式，warm-up／synthesize request 都明確傳送
  `animation_enabled`，避免 Avatar service 容器預設值不同時誤載 MuseTalk。
- `/v1/avatar/status` 對瀏覽器回報後端有效的 `animation_enabled`、動畫模型與 loaded
  判定；靜態模式只要求 CosyVoice 已載入，動態模式仍要求 CosyVoice 與 MuseTalk。
- 此變更只影響 Avatar readiness，不改變病患問診、語音內容、字幕、授權或臨床決策；
  靜態模式仍透過原有受病患 session 保護的 MP4 API 提供醫師圖與本機語音。

### v0.3.0 (2026-08-10)

- Gemini 最終整理 prompt 參考 2026-07-06 初始版本 commit `d84901f` 的
  `STRUCTURED_NOTE_SYSTEM_PROMPT`／`build_structured_note_prompt`，產生 EMR、前三項
  初步鑑別、五項防漏診鑑別、理學檢查、檢驗與影像學決策的六段式報告。
- 固定問卷最後一題後，以新 RAG 分別檢索鑑別／危險徵兆、檢驗及影像三組文獻，再把
  全部題目、患者答案、院方預填資料與 A／B／C evidence blocks 一次送給 Gemini；
  RAG 不參與問卷路由、下一題或後端 Safety 規則。
- 依產品要求移除輸出中的「建議」：不再產生患者端建議段落，兩個臨床段落改為
  `【理學檢查】` 與 `【檢驗（抽血／驗尿）】`，parser 也會移除模型欄位中的該詞。
- Gemini 嚴格 JSON 經後端驗證及固定 renderer 組裝；RAG sources 一併保存。模型內容
  仍標示未經醫師確認，不代表正式診斷或已簽署醫囑。
- 更新 prompt／schema／渲染 regression assertions；固定問題順序、單次末端 Gemini
  呼叫、無後端 Safety／投票與失敗保留答案的行為不變。完整 backend suite 共
  376 項、374 項通過；其餘 2 項只因未掛載外部 `D:\ehis\eHIS` C# 原始碼而 error。

### v0.2.0 (2026-08-10)

- 預設流程仍由後端按 JSON 原始順序逐題顯示固定問卷；主訴僅以本機關鍵字選擇
  症狀問卷，無法分類時改問固定的 chief／basic／history 共通題，不再提前 handoff。
- `questionnaire` 路徑不執行原文字串或語意 Safety、AMIE、ClinicalFact、疾病票數、
  RAG 或逐題 LLM 呼叫，所有題目與輸入驗證均在本機完成。
- 最後一題通過驗證後，後端才以單一 Gemini request 傳送全部已回答的「題目＋患者
  答案」及院方預填欄位，要求嚴格 JSON EMR；結果以「Gemini 生成、未經醫師確認」
  標示後同步保存，不再啟動背景疾病評分或摘要流程。
- Gemini 回應逾時、失敗或格式不符時回傳 503，不核發問診編號也不產生臨床猜測；
  已填答案保留於 session，病人可重試最後一步。此流程會把完整問卷答案送至 Google
  Gemini，正式使用前必須由院方完成資料處理、同意、保存地區與隱私審查。
- 新增固定順序、單次完整 payload、無 Safety／AMIE／背景投票、未知主訴共通題、
  Gemini 格式失敗可重試及 EMR 持久化的 regression tests。完整 backend suite 共
  375 項、373 項通過；其餘 2 項只因未掛載外部 `D:\ehis\eHIS` C# 原始碼而 error。

### v0.1.0 (2026-08-10)

- 病患 runtime 預設改為 `questionnaire`：自由主訴只由本機關鍵字選擇一份核准問卷，
  之後依 `chief → basic → history → disease` 的 JSON 原始順序逐題詢問，只略過 FHIR
  已預填欄位及條件不成立題目。
- 新 pipeline 不呼叫 ChiefComplaintExtractor、AMIE engine、ClinicalFact 轉換或疾病
  票數；明確原文字串 Safety 規則仍保留，無單一路由時保存已收資料並轉交醫療人員。
- routine、urgent 與 unsupported handoff 都在核發編號時同步保存
  `【病歷摘要 EMR】`，只整理病人回答與院方預填資料，不產生疾病、診斷或臨床推論。
  背景摘要與醫師載入也不會為此類病例重建 disease votes。
- 新版 RAG collections、醫師文獻問答、Avatar gateway 與既有權限／tenant 邊界維持；
  RAG 不進入病患逐題流程或 deterministic EMR。`legacy` 設定值保留為
  `questionnaire` 相容別名，明示 `amie` 才會啟用舊引擎。
- 新增逐題順序、無語意／AMIE 呼叫、原文 Safety、EMR 持久化及背景不回算疾病票數的
  regression tests。完整 backend suite 共 374 項，其中產品測試通過；OpenAPI artifact
  已同步，另 2 項外部 eHIS static-contract 仍因未掛載 `D:\\ehis\\eHIS` 而無法執行。

### v1.6.0 (2026-08-10)

- 新增兩階段、可續跑的 provisional AMIE clinical-artifact pipeline：Gemini 先依
  問卷與初始 RAG 提出標準英文疾病名稱，再以每個疾病名稱分別查詢 RAG，最後逐疾病
  產生 ClinicalFact、exact-choice 語意映射、疾病 profile 與 Safety 候選。
- 嚴格 validator 要求「疾病名稱 → retrieval query → chunk → fact／semantic／clue」
  引用閉合；本機 compiler 只做可稽核的 citation evidence-pack 回填、code namespace
  重命名及移除無 choice option 可達的 fact，不自行創造臨床條件、權重或緊急規則。
- 完成 `20260810-gemini-disease-rag-v8` 的 49/49 隔離草稿：163 個疾病候選、431 個
  fact、344 個 choice 語意映射、118 個 profile 與 82 個 Safety 候選。Manifest 同時
  標示 45 個 profile 缺口、16 條無 Safety 路徑、6 條 evidence insufficient 與 8 個
  critical review notes，因此 `clinical_review_ready=false`、`runtime_eligible=false`。
- 產物只寫入 `questionnaire_drafts/clinical_artifacts/`，不修改 active questionnaire、
  Safety 或 disease data；病患 runtime 仍僅啟用 chest／headache／abdomen。模型輸出
  仍為 unverified provisional，沒有 clinical signoff 或 promotion 能力。
- 新增 7 項離線單元測試，涵蓋疾病名導向 retrieval、跨 artifact 引用、candidate
  runtime 隔離、citation 限縮修補、不可達 fact 裁切、code 引用同步及 urgent
  fail-closed stub；131 項 AMIE／問卷聚焦測試、Ruff／format、OpenAPI drift 與兩份
  frontend metadata drift check 通過。完整 backend suite 共 370 項、368 項通過；2 項
  仍只因未掛載外部 `D:\ehis\eHIS` C# 原始碼而 error。

### v1.5.0 (2026-08-10)

- 將病患問診的 AMIE／legacy 開場、返回上一題、輸入錯誤、section 轉場、一般完成、
  儘早就醫、人工轉交、重入完成問診，以及流程產生的摘要／轉交報告模板，集中到
  `questionnaire_data/ui/patient_messages.json`；`patient.py` 不再內嵌 `reply` 字串。
- 新增 `domain.patient_messages` 嚴格 loader：固定 schema／locale／完整 key 集合，並
  驗證每個模板的 placeholder 名稱；缺漏、未知文案或參數漂移會明確失敗，不會靜默
  回退成程式內預設文字。
- Safety／ClinicalFact 規則、LLM system prompt、audit reason 與 HTTP 例外仍保留在
  原負責模組，避免可編輯話術檔改變臨床決策、稽核語意或安全邊界。
- 43 項聚焦問卷、文案 schema、輸入驗證、返回上一題與 triage tests，以及本次檔案
  Ruff／format checks 通過。完整 backend suite 共 369 項，367 項通過；2 項仍只因
  未掛載外部 `D:\ehis\eHIS` C# 原始碼而 error，沒有本專案 assertion failure。

### v1.4.0 (2026-08-10)

- `/v1/avatar/speak` 新增向後相容的 `language` 欄位，允許 `mandarin`（預設）或
  `minnan`，並由私有 Avatar client 原樣傳給本機 CosyVoice3 服務。
- 新增受病患 session 保護的 `/v1/avatar/warmup`；啟用 Avatar 時依序預載
  Breeze ASR、CosyVoice3、MuseTalk／VAE 與嘴型音訊 encoder，任一模型載入失敗
  會以 503 明確拒絕啟用。
- Breeze ASR 新增可重複呼叫的 warm-up，已載入時不重建 pipeline；OpenAPI、後端
  client、route inventory 與授權 action 一併更新。
- 聚焦 backend tests、Ruff、OpenAPI export／drift 與 Docker GPU warm-up 驗證通過。

### v1.3.0 (2026-08-09)

- 每場問診記錄 `interview_length` 觀測值（各 section 題數、病歷預填題數、漏斗未問
  題數、預填覆蓋率），寫入 `amie_state` 與 `_amie`。僅保存欄位名與計數，不含任何
  答案或臨床內容；不改變任何選題、完診或安全決策。
- 新增 `scripts/measure_interview_length.py`，以合成且決定性的作答比較「提案中的
  單頁多選批次」與現行逐題流程。批次化本身未實作，因為它會改變 `next_question`
  契約與病人流程，屬待決策項目。
- 量測揭露兩項既有行為，已記錄於 `docs/funnel_clinical_signoff.md` 第 5、6 節並以
  測試鎖定，本版未修改臨床政策：
  - active 三痛問卷與共用病史有 78 個選項沒有 fact 對應
    （`chest.cardio` 16／16、`chest.surgery` 12／12、`history.chronic` 7／7 等）。
    這些選項不會影響疾病投票，但欄位仍可因 required／priority 政策而被詢問。
  - `smoke`／`chronic`／`past_meds` 不在任何路由的 `required_fields` 且 utility 恆為
    0；同一份胸痛問卷，合成作答選第一個選項時 18 題完診並問到三者，選最後一個
    選項時 6 題完診且三者皆未詢問。
- 驗證：`ruff check .` 通過；`ruff format --check` 對本次變更的 5 個 Python
  檔案通過；`unittest discover -s tests` 共 356 項，354 項通過。僅 2 項 eHIS
  static-contract 因未掛載外部 Windows 原始碼而 error，本專案內沒有產品 assertion
  failure。`pyright` 與 `lint-imports` 未安裝於 venv，本次未執行亦未安裝。

### v1.2.0 (2026-08-09)

- Safety rule loader 依原子檔案 signature 自動刷新，讓已啟動的多個 worker 在下一次
  問診即可讀到 publisher 寫入的新 revision，不再依賴單一 process 的 cache clear。
- Async 病患與醫師 routes 將同步 chief extraction、AMIE turn 及 LLM generation 移至
  bounded worker；可用 `CLINICAL_IO_CONCURRENCY` 與 `CLINICAL_IO_TIMEOUT_SECONDS`
  設定容量及逾時，病患逾時 fail closed 至人工 handoff。
- API error response 保留既有 `detail` 並加入 `error_code`、`correlation_id` 與 headers；
  validation 不反射輸入，internal exception 原文不會出現在 response 或 log。
- Consultation repository 的每個短生命週期 SQLite connection 現在於成功、rollback 與
  exception 路徑都確實關閉。
- 完整 backend suite 共 344 項，342 項通過；僅 2 項外部 eHIS static-contract tests
  因本機未掛載 `D:\\ehis\\eHIS` 而無法執行。Ruff、OpenAPI drift 及相關並行／錯誤／
  connection regression checks 通過。

### v1.1.0 (2026-08-09)

- 將 49 份尚未取得臨床簽核的結構化問卷保留為候選內容；runtime 僅啟用既有
  胸痛、頭痛、腹痛路由，缺少簽核時 fail closed，不把 provisional 內容送入病人流程。
- promotion CLI 現在驗證 reviewer、日期、來源與路由 catalog SHA-256、逐路由核准
  及 review note resolution，並保留稽核來源；frontend exporter 新增原子寫入、
  `--check`，且只有明示 `--frontend-v2` 才更新正式部署產物。
- 修正英文短字串路由誤判；多主訴問診改為逐路由計算疾病 assessment、frontier、
  must-not-miss 與完成條件，避免次要主訴尚未完成時提前結束。
- live ClinicalFact 成為語意事實的權威來源，避免 legacy 重建產生未限定路由的重複
  fact；同一 finding 的較新更正會取代舊狀態，衝突仍保留於 audit。
- 固定順序候選路由不再借用胸痛／頭痛／腹痛疾病表。未簽核的三個既有問卷選項
  已撤回，相關臨床政策仍記錄於 signoff 文件等待合格人員決定。
- 驗證包含 334 項 backend tests（332 通過；2 項因外部 eHIS 原始碼未掛載而無法
  執行）、Ruff、26 個變更 Python 檔格式檢查，以及兩份 frontend export drift 檢查。

### v1.0.0（2026-08-07）

這是目前第一個文件化的服務版本基線，涵蓋以下已記錄更新：

#### 2026-07-27

- 將主訴、基本資料、一般病史及胸痛、頭痛、腹痛問卷拆成具 schema 驗證、
  lazy loading 與快取的 JSON 動態問卷，並依自由主訴選擇問診路由。
- 統一 Groq／Gemini LLM provider，處理 Gemini thinking budget 與空回應重試，
  並更新問診、語音辨識、結構化回答及六段式報告流程。
- 建立 FHIR `$everything` 預填映射及合成病例；身分證字號只用於 FHIR 查詢，
  並排除本次 encounter diagnosis。
- 建立 RAG v2 語料清理、分類、versioned Chroma collections、RRF 合併及
  legacy／v2 評估工具；查詢翻譯會遮蔽直接識別資訊，失敗時回退多語檢索。

#### 2026-07-28

- 將 FastAPI 後端由單一入口拆分為 `app`、`domain`、`infrastructure`、
  `knowledge` 與 `scripts` 等分層模組。
- 導入 AMIE-inspired 狀態感知問診、具原文 evidence 的 ClinicalFact、動態選題、
  兩層確定性 Safety 判定及可稽核逐輪摘要；模型不直接決定 urgent／routine。
- 新增 SQLite consultation repository，支援病例建立、搜尋、分頁、刪除、摘要狀態
  與結構化報告快取；病例先保存並核發編號，再於背景產生摘要。
- 加入疼痛區域、輸入驗證、TW Core 術語參考與合成 FHIR 測試資料，並建立後端
  lint、型別、coverage、依賴方向及供應鏈檢查設定。

#### 2026-07-29

- 將主訴抽取收斂為 evidence-grounded 白名單流程，限制各症狀 route 的 fact，
  支援起始時間、持續時間、問卷預填及依病人情境過濾不適用選項。
- 建立胸痛、頭痛、腹痛的版本化固定疾病表；支持票、反對票、完整度、穩定排序、
  Safety 必問題、70% 停止條件及 24 輪上限均由程式決定，RAG 不參與病患端評分。
- 新增 Safety 規則管理 API，包含管理權杖、schema 驗證、版本衝突、原子更新與
  更新前稽核快照；LLM 助理只能產生待醫師確認的既有規則草稿。
- 建立 SNOMED CT RF2 驗證、HAPI 匯入、本機 FTS 索引、`$lookup` 代理及疾病 coding
  registry；同時支援 SMART OAuth 後的 FHIR 預填與同源 `/api` reverse proxy。

#### 2026-08-04

- 擴充疾病票數、ClinicalFact 與組合／原文 Safety 的獨立治理流程，加入 reviewer、
  `safety_rule_codes`、發布確認、差異稽核、原子寫入及失敗回復。
- 正式 API 統一採 `/v1` 前綴，保留未版本化相容別名但不納入 OpenAPI；補上具名
  response model、錯誤 envelope、OpenAPI 匯出及契約檢查。
- 重整醫師速覽：模型只壓縮既有病史；最多三個可能疾病及支持理由由 Safety
  觸發結果、固定疾病表票數與病人原始 evidence 組成，並明示不是正式診斷。

#### 2026-08-05

- 將病患問診 route 與規則治理後端拆成較小的服務／support 模組，保留原有 facade
  與測試介面。
- 加入確定性疾病候選漏斗，以支持票、區辨力、確認力及反證力排序問題；問卷
  policy schema version 2 新增候選票距與數量上限，稽核則記錄階段、候選與分數。
- SQLite schema 升至 version 6，採「看診日期＋掛號編號」形成永久
  `consultation_id`，加入每日 sequence、WAL contention retry、交易式舊資料遷移，
  並讓背景摘要、更新及刪除以 composite ID 精確定位。

#### 2026-08-06

- 新增 UCC RS256 JWT、scope 驗證、一次性病患邀請、Secure／HttpOnly session、
  CSRF 與機構／encounter 隔離；瀏覽器輸入的識別資料不直接作為授權依據。
- SQLite repository 新增 invitation、patient session、consultation access 與
  security audit 資料；安全日誌避免記錄 token、病歷內容及例外細節。
- CORS 改為明確 allowlist，正式環境可停用未版本化 API alias，並為病患問診、
  語音轉錄、病例查詢與醫師管理端點加入相應身分依賴。

#### 2026-08-07

- 病患 chat API 新增 `answer`／`back` action 與 `can_go_back`；每次有效作答前保存
  有限 session 快照，可回復上一題、問卷資料及 AMIE transcript，同時保留授權內容。
- 新增只接受 loopback TCP peer 的 `ALLOW_LOCAL_AUTH_BYPASS` 開發模式；正式 principal
  仍依院所隔離，且不信任 `Host` 或 forwarded header。
- 將 EMR 摘要固定為基本資料／主訴首行與恰好兩句其他病史，模型結果不安全或缺漏時
  由既有病史、用藥及過敏資料產生 deterministic fallback。
- 產生 52 類具來源 hash、模型及逐字來源的 provisional 問卷審查草稿；草稿不會載入
  runtime，未經醫療、安全、隱私與 UX 審查不得發布。
- `/v1/transcribe` 預設改用延遲載入的 Breeze-ASR-26，加入 ffmpeg 解碼、音訊長度、
  RMS 靜音門檻及 MIME 檢查；辨識文字需由病患確認後才送入問診。
- 新增沿用病患 session 的 Avatar status／speak gateway；回傳影片時不暴露私有
  Avatar service host，並同步更新 OpenAPI 契約。

## 目錄與責任

| 路徑 | 責任 |
| --- | --- |
| `main.py` | ASGI 入口，匯出 FastAPI `app` |
| `app/` | HTTP routes、request/response models、服務與 prompts |
| `domain/` | 問卷、疼痛位置與術語領域邏輯 |
| `infrastructure/` | LLM provider 與 SQLite repository |
| `amie/` | ClinicalFact、Safety、疾病表投票、選題與稽核流程 |
| `questionnaire_data/` | 主訴、基本資料、病史及三種疾病問卷 JSON |
| `knowledge/` | RAG 共用常數、檢索、taxonomy 與查詢翻譯 |
| `scripts/` | 清洗、分類、建庫、評估、OpenAPI 與術語 CLI |
| `terminology/` | TW Core packages、SNOMED CT installer 與本機索引 |
| `fhir_samples/` | 合成 FHIR 測試病例 |
| `tests/` | 後端單元與契約測試 |
| `data/` | 本機問診與稽核資料；由程式建立且不提交 Git |

RAG 流程請見 [knowledge/README.md](knowledge/README.md)，問卷格式請見
[questionnaire_data/README.md](questionnaire_data/README.md)，術語環境請見
[terminology/README.md](terminology/README.md)。

## 安裝

需求為 Python 3.12+。從本目錄建立虛擬環境並安裝 runtime dependencies：

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

專案根目錄的 `./scripts/bootstrap.sh` 可代為完成這些步驟；詳細選項請見
[../scripts/README.md](../scripts/README.md)。

## 環境變數

先複製範例：

```bash
cp .env.example .env
```

固定問卷完成後必須使用 Gemini 整理 EMR，因此即使其他 LLM 工作選用 Groq，仍需
設定 `GEMINI_API_KEY`：

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=你的_Gemini_API_Key
INTERVIEW_ENGINE=questionnaire
```

其他既有 LLM 工作可另外選 Groq：

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=你的_Groq_API_Key
GEMINI_API_KEY=你的_Gemini_API_Key
INTERVIEW_ENGINE=questionnaire
```

Gemini Key 可由 [Google AI Studio](https://aistudio.google.com/app/apikey) 申請，
Groq Key 可由 [Groq Console](https://console.groq.com/keys) 申請。

`LLM_PROVIDER` 省略時會優先使用 `GROQ_API_KEY`，沒有 Groq key 才使用
`GEMINI_API_KEY`。模型可用 `GEMINI_MODEL` 或 `GROQ_MODEL` 覆寫；預設分別為
`gemini-2.5-flash` 與 `llama-3.3-70b-versatile`。

常用設定：

| 變數 | 用途 |
| --- | --- |
| `INTERVIEW_ENGINE=questionnaire` | 預設：本機依序問固定題目，完成後以六個獨立 Gemini prompt 整理並驗證六段式報告 |
| `INTERVIEW_ENGINE=legacy` | `questionnaire` 的相容別名 |
| `INTERVIEW_ENGINE=simple` | `questionnaire` 的相容別名 |
| `INTERVIEW_ENGINE=amie` | 明示回退舊 AMIE／ClinicalFact／疾病票數流程；不建議作為新流程 |
| `AMIE_MAX_TURNS` | 可選的整體動態問診硬上限；未設定時依共用題與每條核准路由 policy 動態計算（最高 100） |
| `CLINICAL_IO_CONCURRENCY` | async route 的同步臨床／模型 worker 上限，預設 4、範圍 1–32 |
| `CLINICAL_IO_TIMEOUT_SECONDS` | 單次同步臨床／模型工作的 route 等待上限，預設 45 秒、範圍 5–180 秒 |
| `AMIE_DEBUG_TRACE=true` | 測試時顯示去除疾病票數與排名後的決策摘要 |
| `ASR_PROVIDER=breeze` | 使用本機 `MediaTek-Research/Breeze-ASR-26` 辨識錄音 |
| `BREEZE_ASR_DEVICE=auto` | 有 CUDA 時使用 GPU/FP16，否則使用 CPU/FP32 |
| `BREEZE_ASR_RELEASE_GPU_AFTER_TRANSCRIBE=false` | 保留 CUDA pipeline；整合部署在啟用 Avatar 時預載並重用 |
| `BREEZE_ASR_MODEL` | 覆寫 Hugging Face 模型 ID 或本機模型目錄 |
| `ASR_MAX_AUDIO_SECONDS` | 後端接受的單次錄音上限，預設 120 秒 |
| `ASR_MIN_AUDIO_RMS` | 靜音／過小音量門檻，預設 0.001，避免將靜音幻覺成病人回答 |
| `AVATAR_ENABLED=true` | 啟用私有網路上的本地 CosyVoice3 + MuseTalk 服務 |
| `AVATAR_SERVICE_URL` | Avatar 容器內網 URL；整合部署為 `http://avatar:8090` |
| `AVATAR_ANIMATION_ENABLED=true` | 預設使用 MuseTalk；設為 `false` 時請 Avatar service 產生靜態醫師圖 MP4，只需載入 CosyVoice |
| `AVATAR_TIMEOUT_SECONDS` | 首次載入與影片生成逾時，整合部署預設 600 秒 |
| `ALLOW_LOCAL_AUTH_BYPASS=true` | 只在 loopback 開發時略過病患 session 與 UCC Bearer；預設關閉 |
| `CONSULTATION_DB_PATH` | SQLite 路徑；相對路徑以 `backend/` 為基準 |
| `SAFETY_RULE_ADMIN_TOKEN` | 啟用規則中心編輯；未設定時維持唯讀 |
| `FHIR_BASE_URL` | HAPI FHIR terminology server URL |
| `RAG_INDEX_VERSION=v2` | 使用具 `clinical_stage` 分區的 RAG v2 collections；移除或設為 `legacy` 會使用具 provenance 的未分區相容檢索 |

若使用 `gemini-2.5-pro`，後端會為不可關閉的 thinking 預留 128 tokens，並將
可見回答額度另外加入 `max_output_tokens`；可用 `GEMINI_THINKING_BUDGET`
覆寫。模型因 `MAX_TOKENS` 沒有產生正文時，系統會提高上限重試一次。

`.env` 含有祕密，不得提交版本控制。

本機直接以 `http://127.0.0.1:5173` 開發舊版 `frontend/` 時，可在
`backend/.env` 設定 `ALLOW_LOCAL_AUTH_BYPASS=true`。後端只會對
`127.0.0.0/8` 或 `::1` 的直接連線略過病患 session 與 UCC Bearer；
判斷依據是無法由用戶偽造的 TCP peer IP，不是 `Host` header。非 loopback
來源、integration deployment 與正式環境仍強制完整驗證。本機舊版
`frontend/` 的開發身分不套用院所篩選，因此可讀取尚未寫入
`institution_id` 的舊病例；正式 Bearer 身分仍依院所隔離。

### Breeze 語音辨識

語音端點預設改用本機 Breeze-ASR-26，不再將病人錄音傳給
Gemini 或 Groq。系統需要 `ffmpeg`；Ubuntu/WSL 可先安裝：

```bash
sudo apt-get install ffmpeg
```

模型預設可延遲載入；啟用本機 Avatar 時，`/v1/avatar/warmup` 會先載入約
6 GB 權重，之後同一後端 process 會重用模型。本專案的 RTX 5060 Ti /
CUDA 12.8 開發機可安裝與參考專案相同的 wheel：

```bash
cd backend
venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cu128 \
  torch==2.11.0
```

`BREEZE_ASR_DEVICE=auto` 會自動選擇 GPU/FP16，否則回退 CPU/FP32；
部署機已確定有 GPU 時建議設為 `cuda`，未正確傳入 GPU 時會明確失敗，
避免不小心用 CPU 推論。整合部署在已驗證的 16 GB RTX 5060 Ti 設定
`BREEZE_ASR_RELEASE_GPU_AFTER_TRANSCRIBE=false`，讓 ASR 與 Avatar 模型常駐；
其他 GPU 必須先量測顯存，容量不足時可改回 `true`，以重新載入延遲換取顯存。
CPU 模式不受此設定影響。需要回退原有雲端辨識時設為 `ASR_PROVIDER=llm`。

瀏覽器端最長錄音 60 秒，辨識結果只會回填輸入框；病人需先確認或
修正文字才會送出問診答案。

### 本地語音與 Avatar

整合部署會以 `Fun-CosyVoice3-0.5B-2512` 合成 AI 回覆；預設再由 MuseTalk 1.5
依指定醫師圖產生唇形 MP4。`AVATAR_ANIMATION_ENABLED=false` 時，後端會在預載與
每次生成 request 明確要求靜態醫師圖 MP4，不載入 MuseTalk。模型服務不對 LAN 或公網發布；integration 開發設定
僅綁 host loopback。`/v1/avatar/status`、`/v1/avatar/warmup` 與
`/v1/avatar/speak` 都沿用病患 session 驗證。完整安裝、聲線替換與 GPU
調校說明見 [../avatar-service/README.md](../avatar-service/README.md)。

## 啟動與 API

```bash
uvicorn main:app --reload
```

後端預設位於 `http://127.0.0.1:8000`。正式 API 使用 `/v1` 前綴：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- 即時規格：`http://127.0.0.1:8000/openapi.json`
- 版本控制規格：`../docs/openapi.json`

修改 API model 或 route 後，更新 OpenAPI 與前端型別：

```bash
# backend/
python -m scripts.export_openapi
python -m scripts.export_openapi --check

# frontend/
cd ../frontend
npm run api:types
npm run api:check
```

產物 `frontend/src/generated/api.d.ts` 不應手動編輯。未加版本的舊路徑僅為
相容別名，不列入 OpenAPI；新程式一律使用 `/v1`。

## 問診與資料邊界

預設 `questionnaire` pipeline 只依自由主訴中的本機關鍵字選擇一份固定症狀問卷；
無法對應時使用固定的 chief／basic／history 共通題。選定後依問卷 JSON 原始順序
逐題詢問，保留條件題與 FHIR 預填略過。

- 下一題只由目前索引、問卷順序、條件與已預填欄位決定
- 不執行原文字串或語意 Safety、症狀抽取、ClinicalFact、疾病候選或票數
- 問卷進行中不呼叫 LLM，RAG 也不參與路由或下一題
- 最後一題完成後才檢索 RAG A／B／C 三組文獻，再以六個依序的 Gemini request
  分別處理 EMR、前三鑑別、防漏診、理學檢查、檢驗與影像
- Gemini 回傳英文六段式 EMR 與臨床決策草稿；經驗證的五個防漏診疾病會明確傳入
  後三個 request，輸出仍標示未經醫師確認，不代表正式診斷

每筆新病例會標記 `_interview_pipeline.engine=questionnaire`，並保存送往 Gemini 的
固定問卷答案、模型名稱與 prompt version；不建立 AMIE trace、ClinicalFact、
Safety 結果、疾病 assessment 或漏斗分數。舊引擎資料仍可讀取，但不會套到新病例。

此流程刻意將完整問卷回答交給 Google Gemini，而非去識別化查詢。這是外部資料邊界
變更：正式處理真實病人資料前，院方必須確認告知與同意、供應商契約、資料保存／訓練
政策、傳輸與保存地區及稽核要求。未完成這些審查時只能使用合成資料。

`amie/disease_data/{chest,headache,abdomen}.json` 是一次性 RAG＋離線 LLM
建表後提交版本控制的凍結產物，包含來源、corpus SHA-256、模型、不能漏診標記
及整數權重。目前是 `provisional`，不是患病機率或正式診斷。

fact 白名單、舊病例映射與 Safety 規則位於
`amie/rules/safety_rules.json`；必要欄位、選題策略、領先群票距與數量、停止門檻
及輪數上限位於 `questionnaire_data/*.json`。這裡的 AMIE 是依公開研究方法實作的流程，不是
Google 官方 AMIE 模型或服務，也不包含 self-play 訓練。

## FHIR 病歷預填

使用身分證字號由 FHIR 載入病歷時，姓名、性別、出生日期、血型及既有病史
不會重問；身分證字號不會送入 `/chat`、RAG 或外部模型。

`Patient/$everything` 中的 `Condition`、`Procedure`、`MedicationStatement`、
`MedicationRequest`、`AllergyIntolerance` 與 `QuestionnaireResponse` 會映射至
一般病史、分系統疾病史、手術史、用藥與過敏。本次就診的
`encounter-diagnosis` 不會被當成既往病史。

本機 FHIR／TW Core／SNOMED 環境請見
[terminology/README.md](terminology/README.md)，SMART OAuth 整合請見
[../smart-app/README.md](../smart-app/README.md)。

## 問診資料庫與測試病例

問診結果預設保存於 `data/consultations.db`，啟動時自動建立，不需 migration。
固定問卷最後一題完成後，Gemini 必須先成功回傳符合 schema 的病歷草稿，後端才會
同步保存完整問卷答案、模型輸出及 routine 五位數編號。新 `questionnaire` 病例不跑
背景摘要、不附加可能疾病或固定疾病表排名；舊 AMIE 病例仍依既有流程相容顯示。

Gemini 逾時、服務錯誤或輸出格式不符時，API 回 503、不建立病例也不核發編號；已填
答案仍保留於受驗證 session，病人可重試最後一步。資料庫含病人資料，不應提交、公開
或放置於未加密位置；正式環境仍需備份、身分驗證、授權與稽核政策。

醫師端輸入問診編號 `00000` 可載入預先建立的胸痛假病人。其初步評估是固定
測試文字，並有「測試用假病人資料」標示，不會被誤認為真實病例。

## 醫師端規則中心

規則中心可查看實際執行中的全局流程、三種疾病表版本、問卷停止政策、Safety
規則、觸發條件與鑑別標籤。Safety 的唯一來源是
`amie/rules/safety_rules.json`，不散落於 Python 程式。

預設為唯讀。設定高強度 `SAFETY_RULE_ADMIN_TOKEN` 並重新啟動後端後，醫師
才可驗證權杖並使用編輯功能：

- Safety 規則可依分類搜尋與選取，或由微調助理產生最多五個標籤的草稿
- LLM 不得新增／刪除 rule code，也不能直接儲存；草稿需通過完整 JSON 驗證
- 正式發布需要變更理由、指定確認文字、相同管理權杖及版本衝突檢查
- 舊版先寫入 `data/safety_rule_audit/`，再以原子方式更新

疾病治理只允許調整既有疾病的白名單 ClinicalFact、存在／不存在方向及 1–10
整數權重，不能新增或刪除疾病。每個 `must_not_miss` 疾病至少需綁定一組穩定
`safety_rule_codes`；只有明確綁定的緊急觸發器會標記 urgent。

進階 fact label 設定使用完整白名單；標為 Safety 的單一 fact 以 `present` 命中
時會直接標記 urgent。需要多條件、特定原文或 FHIR 風險才成立的規則則保留在
「組合與原文 Safety 規則」。fact label 透過獨立的
`PUT /doctor/rules/fact-labels` 發布；兩種流程都執行版本衝突、確認文字與稽核。

既有疾病可新增或移除白名單標籤並調整方向、權重；新標籤沿用該疾病既有來源
集合，臨床依據由發布醫師負責。穩定 rule code 不可更名或刪除。

發布疾病表時需提供審查醫師、變更理由與指定確認文字。後端會驗證疾病與線索
集合、處理版本衝突、標記 `reviewed`、產生新 `profile_version`，並把差異與舊版
保存至 `data/disease_profile_audit/`。目前的權杖只適合原型；正式部署必須改用
具醫師身分驗證、角色授權與集中稽核的管理服務。

## 開發品質檢查

```bash
pip install -r requirements-dev.txt

ruff check .
ruff format --check .
pyright --project pyproject.toml
lint-imports --config .importlinter
coverage run -m unittest discover -s tests
coverage report
vulture
pip-audit -r requirements.txt
```

在 repository 根目錄執行 `pre-commit install` 後，每次 commit 前會執行 Ruff、
Pyright 與分層架構檢查；也可手動執行：

```bash
pre-commit run --all-files
```

## 疑難排解

### 啟動時顯示 `[RAG] 未找到 chroma_db`

尚未建立本機索引。依 [RAG 文件](knowledge/README.md) 執行清洗、分類與 ingest，
或在專案根目錄執行 `./scripts/bootstrap.sh --with-rag`。

### `.env` 或資料庫不存在

`.env`、`data/`、`chroma_db/`、`clean_docs/` 與 `classified_docs/` 都是本機設定
或衍生資料，不會由 Git 還原。複製 `.env.example`，並依各子系統文件重建所需
資料即可。
