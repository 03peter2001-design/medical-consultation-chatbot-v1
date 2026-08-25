# AI 預問診系統（Medical Consultation Chatbot）

AI 輔助預問診系統。病患可透過預設啟用的本機 Avatar，以文字或語音完成胸痛、
頭痛或腹痛的逐題結構化問診；醫師可依問診編號查看原始回答、結構化電子病歷與摘要。

本專案目前是研究與合成資料開發原型，不是醫療器材，也不提供正式診斷。
疾病票數、完整度與排序均不代表患病機率，正式臨床使用仍需醫師審查、院方整合、
身分與權限管理、稽核及資料治理。

目前預設流程會在固定問卷結束後，把全部題目、患者答案與院方預填欄位送往 Google
Gemini，結合本機 RAG 文獻產生六段式 EMR 與臨床決策草稿。內容未經醫師確認，
不代表正式診斷或已簽署醫囑；未完成院方的告知同意、供應商契約、資料保存地區與
隱私審查前，不得用於真實病人資料。

## 系統總覽

- **病患端**：自由主訴、FHIR 病歷預填、逐題問卷、疼痛位置標記及預設本機 Avatar
- **順序式問診**：主訴只以本機關鍵字選擇固定問卷，之後依 JSON 原始順序提問；
  不執行 AMIE、症狀語意抽取、Safety、ClinicalFact 或疾病票數
- **醫師端**：病例搜尋、問卷原始回答、Gemini 生成 EMR、醫師速覽、SNOMED CT
  查詢與舊病例相容的規則／分析畫面
- **本機資料層**：SQLite 保存問診結果，Chroma 保存版本化 RAG collections
- **FHIR／SMART**：支援 TW Core 開發環境、SNOMED CT 匯入及本機 SMART on FHIR
  合成病例流程
- **RAG**：不參與病患問卷路由、下一題或 Safety；v2 索引在固定問卷完成後提供
  A（診斷／理檢）、B（檢驗）、C（影像）三個 metadata 分區的檢索證據，legacy
  索引則保留具 provenance 的相容檢索，再交由 Gemini 產生六段式報告

```text
病患端：病人主訴 → 本機關鍵字選擇固定問卷 → 依 JSON 順序逐題詢問
                  → 程式查詢 RAG A／B／C → 逐題送入 Gemini → 驗證後保存六段式報告

醫師端：中文問題 → 去識別化與醫療術語英文化
                → 本機 embedding／Chroma 檢索 → LLM 整理來源片段
```

## 服務版本

下表是依 `devlog/` 回溯整理的「目前文件基線版本」，並不代表過去已建立
同名 Git tag 或已完成正式臨床發布。各服務 README 在對應版本下保留按日期
整理的詳細更新內容；未來發布時再依 SemVer 分別遞增，不強制所有服務
使用相同版本號。

| 服務／可部署產物 | 目前版本 | 基線日期 | 本版重點 | 詳細記錄 |
| --- | --- | --- | --- | --- |
| Backend API（含 Breeze ASR） | `0.11.3` | 2026-08-20 | Gemini 標準 JSON Schema 相容修正，無工具呼叫停用 AFC | [backend/README.md](backend/README.md#服務版本) |
| 開發版 Vue frontend | `0.9.0` | 2026-08-20 | `/ai-consult/` SMART EHR Launch、OAuth callback 與 FHIR resources 載入 | [frontend/README.md](frontend/README.md#服務版本) |
| 正式部署 Doctor frontend | `2.1.1` | 2026-09-09 | Doctor API 與 401 token refresh retry 強制略過瀏覽器快取 | [frontend-v2/README.md](frontend-v2/README.md#service-versions) |
| 正式部署 Patient frontend | `2.1.0` | 2026-08-11 | 問診主畫面常駐醫師 Avatar、朗讀字幕與可恢復有聲播放的控制 | [frontend-v2/README.md](frontend-v2/README.md#service-versions) |
| Local Avatar service | `1.2.0` | 2026-08-11 | 新增可由 Backend 逐請求覆寫、完全跳過 MuseTalk 的靜態醫師 CosyVoice 模式 | [avatar-service/README.md](avatar-service/README.md#服務版本) |
| SMART on FHIR sandbox app | `1.0.0` | 2026-08-05 | SMART OAuth launch、FHIR 預填、同源 API proxy、合成病人 seed 與本機驗證 | [smart-app/README.md](smart-app/README.md#服務版本) |
| Integration deployment bundle | `1.6.0` | 2026-09-11 | B01 掛號患者 QR 邀請與 Gemini 擷取／推理／RAG 翻譯模型分流 | [integration-deployment/README.md](integration-deployment/README.md#service-version) |

`frontend-v2/packages/shared` 是 doctor／patient 共用程式庫，不是獨立服務；
`smart-deployment/` 是 SMART sandbox 的 proxy 設定，跟隨 SMART app
`1.0.0` 基線維護。Doctor app 目前為 `2.1.1`，Patient app 維持 `2.1.0`。
HAPI FHIR、PostgreSQL、TW Core 與 SNOMED installer 是外部或
建置元件，使用各自上游版本；目前矩陣與更新說明見
[FHIR／術語服務](backend/terminology/README.md#外部元件版本矩陣)。

服務 SemVer 與下列版本維持獨立，避免將部署版本誤當成臨床內容核准或
資料相容保證：

- API contract major（例如 `/v1`）
- SQLite `user_version`
- RAG index version
- Safety／ClinicalFact／疾病表 revision
- 問卷與來源資料 schema version
- 模型、FHIR Implementation Guide 與 SNOMED CT 來源版本

## 快速開始

需求：Git、Bash、Python 3.12+、Node.js 18+、ffmpeg；FHIR／SMART 流程另需 Docker 與
Docker Compose v2。Windows 建議使用 WSL2。

```bash
git clone git@github.com:03peter2001-design/medical-consultation-chatbot-v1.git
cd medical-consultation-chatbot-v1
./scripts/bootstrap.sh
```

第一次執行時，腳本會建立後端虛擬環境、安裝前後端依賴、建置 Vue frontend，
並準備本機 HAPI FHIR／TW Core（不需要 FHIR 時可加 `--skip-fhir`）。接著填妥
`backend/.env` 中的 `GEMINI_API_KEY`；固定問卷會在最後一次把全部題目與答案交給
Gemini 整理病歷，因此即使其他 LLM 工作使用 Groq，這個 key 仍是必要設定。

需要建立完整 RAG 索引時執行：

```bash
./scripts/bootstrap.sh --with-rag
```

本機開發可分別啟動：

```bash
# Terminal 1
cd backend
source venv/bin/activate
uvicorn main:app --reload

# Terminal 2
cd frontend
npm run dev
```

預設入口：

- 病患端：`http://localhost:5173/#/`
- 醫師端：`http://localhost:5173/#/doctor`
- SNOMED CT：`http://localhost:5173/#/doctor/terminology/snomed`
- API 文件：`http://127.0.0.1:8000/docs`

完整的環境需求、建制選項與快取行為請見 [建制腳本說明](scripts/README.md)。

## 專案目錄

```text
.
├── backend/               FastAPI、AMIE、RAG、SQLite 與術語整合
├── frontend/              Vue 3 + Vite 病患端與醫師端
├── scripts/               一鍵建制與 SMART 啟動腳本
├── smart-app/             SMART launch 頁面與正式前端容器設定
├── smart-deployment/      SMART／FHIR 本機 proxy 設定
├── docs/                  OpenAPI、研究文件與工作規劃
├── devlog/                依日期整理的開發紀錄
├── pic/                   圖片素材
├── compose.fhir.yml       HAPI FHIR、PostgreSQL、TW Core、SNOMED services
└── compose.smart.yml      完整 SMART 開發環境
```

`index.html` 與 `doctor.html` 是 Vue 重構前的相容版本；目前開發入口位於
`frontend/`。`SMART-APP-Exercise-1/`、`package/` 為外部範例／套件資料，
不屬於主要應用程式碼。

## 文件索引

| 主題 | 文件 |
| --- | --- |
| 後端安裝、環境變數、API、資料庫、AMIE、規則中心與品質檢查 | [backend/README.md](backend/README.md) |
| Vue 路由、前端設定、FHIR 預填與 D-ID | [frontend/README.md](frontend/README.md) |
| RAG 語料清洗、分類、建庫、評估與雙語檢索 | [backend/knowledge/README.md](backend/knowledge/README.md) |
| RAG 原始語料的用途與不可變原則 | [backend/docs/README.md](backend/docs/README.md) |
| 問卷 JSON 格式與載入規則 | [backend/questionnaire_data/README.md](backend/questionnaire_data/README.md) |
| Safety 規則結構 | [backend/amie/rules/README.md](backend/amie/rules/README.md) |
| HAPI FHIR、TW Core 與 SNOMED CT | [backend/terminology/README.md](backend/terminology/README.md) |
| SMART on FHIR 本機整合流程 | [smart-app/README.md](smart-app/README.md) |
| SMART／FHIR proxy 設定 | [smart-deployment/README.md](smart-deployment/README.md) |
| 自動建制與啟動腳本 | [scripts/README.md](scripts/README.md) |
| OpenAPI、研究資料與開發規劃 | [docs/README.md](docs/README.md) |
| 正式 SMART 臨床應用構想 | [future.md](future.md) |

## Code review 待辦（尚未完成）

以下是專案整體 code review 建立的追蹤清單。未勾選項目仍須符合「完成條件」並
留下自動化驗證證據；已勾選項目保留原始問題與完成證據，避免之後回歸。

### Critical

- [ ] **優先建立跨主訴的一般化 Safety 規則，不受三種症狀路由限制**
  - **問題**：目前問診與 Safety 規則主要圍繞胸痛、頭痛、腹痛建置；全域原文規則與語意 finding 覆蓋仍不完整。例如「我胸悶。吐血」不會觸發安全條款，只有明確寫成「大量吐血」才命中 `major_bleeding`。不屬於三種問卷的危險症狀也可能因落入 `other` 而缺少足夠的安全保護。
  - **影響**：明確且跨科別的急症警訊可能被當成一般問診繼續處理；Safety 的保護範圍錯誤地受到疾病問卷路由與有限關鍵字約束。
  - **建置原則**：一般化 Safety 必須在疾病路由與問卷選擇之前執行，並獨立涵蓋跨主訴危險徵象；以版本化、可稽核、經醫療專業審查的概念與同義詞規則，同時支援確定性原文偵測及 evidence-grounded 結構化偵測，不依賴 LLM 單獨判斷。
  - **主要檔案／元件**：`backend/amie/rules/safety_rules.json`、`backend/amie/safety.py`、`backend/amie/chief_complaint.py`、`backend/app/routes/patient.py`、Safety 規則治理與黃金測試集。
  - **完成條件**：建立不綁定 chest／headache／abdomen 的通用急症 catalog；補齊吐血／嘔血等明確出血表述及必要同義詞、否定與組合條件；無論最後 route 為何皆先執行通用 Safety；加入「我胸悶。吐血」、單獨危險症狀、同義改寫、否定句及易混淆反例的回歸測試，並經醫療專業人員審核後才能標記完成。

- [x] **為醫師 API 建立完整的身分驗證、授權與 CORS 邊界**
  - **問題**：醫師病例查詢、讀取、刪除、聊天與部分規則中心 API 未完整驗證醫師身分與資源權限，後端同時允許任意 CORS origin。
  - **影響**：未授權使用者可能存取或刪除病歷；過度寬鬆的跨網域設定會擴大 PHI 外洩與管理操作被濫用的風險。
  - **主要檔案／元件**：`backend/app/factory.py`、`backend/app/routes/doctor.py`、醫師端 API client 與部署環境設定。
  - **完成條件**：所有醫師路由預設拒絕匿名請求、依角色與資源範圍授權；CORS 僅允許明確清單，且通過未登入、跨角色、跨來源與正常流程整合測試。
  - **完成證據（2026-08-09 review）**：doctor router 已統一套用 UCC scope dependency，consultation repository 查詢依 institution／encounter 隔離；CORS 只有設定明確 `CORS_ALLOWED_ORIGINS` 時才啟用。完整後端測試中相關 authentication、scope、tenant 與 invitation acceptance tests 通過。

- [x] **關閉可藉 URL query 更改 backend／FHIR 端點的資料外送通道**
  - **問題**：`?backend=` 與 `?fhir=` 可將瀏覽器的 API 目的地改為任意 HTTP(S) 主機。
  - **影響**：惡意連結可能誘使用者將病歷、身分資料或規則管理 token 傳送至攻擊者端點。
  - **主要檔案／元件**：`frontend/src/services/backend.js`、`frontend/src/services/fhir.js`、`frontend/src/services/smart.js`、SMART／FHIR proxy 設定。
  - **完成條件**：正式環境完全忽略 query override；開發模式若保留此功能，必須明確啟用並限定 allowlist；自動化測試證明 PHI 與授權 header 不會送往任意網域。
  - **完成證據（2026-08-09）**：production／預設忽略 backend、backendPort、FHIR 與 direct-FHIR query；開發覆寫同時需要 build-time flag 與 exact-origin allowlist，跨 origin backend 一律不帶 cookie。開發版與 `frontend-v2` shared FHIR regression tests 覆蓋惡意 origin、同源 proxy 與 production 關閉行為。

### High

- [x] **讓已發布的 Safety 規則即時對所有問診工作者生效**
  - **問題**：部分 Safety 設定在 module import 時載入，規則中心發布新版後可能仍需重啟 process。
  - **影響**：管理畫面顯示的 revision 可能與實際執行分流不一致，使新增的危險警訊沒有即時保護病人。
  - **主要檔案／元件**：`backend/app/services/patient_interview.py`、`backend/amie/rule_config.py`、`backend/amie/engine.py`、規則發布服務。
  - **完成條件**：發布後不需重啟即可在新問診中觀察新 revision，且多 worker 整合測試證明每個 worker 使用相同版本。
  - **完成證據（2026-08-09）**：Safety loader 以原子檔案的 device／inode／size／mtime
    signature 選擇 cache；publisher replace 後，各 worker 下一次讀取會自動驗證並載入新
    revision。spawn 的雙 worker regression test 證明兩個既有 process 都能由同一份舊
    version 切換至新 version，無需呼叫 process-local `cache_clear` 或重啟。

- [ ] **將治理後的規則設定與 revision 持久化**
  - **問題**：Safety、ClinicalFact 與疾病表治理結果以容器內 JSON 為主，重建或水平擴展後可能與 audit revision 失去一致性。
  - **影響**：已審核且發布的醫療規則可能遺失、回退或在不同 instance 間分歧，稽核記錄也無法證明當時執行內容。
  - **主要檔案／元件**：`backend/app/services/rule_management.py`、`backend/app/services/rule_management_support/`、`backend/amie/rules/`、`backend/amie/disease_profiles.py`。
  - **完成條件**：使用 durable store，啟動時驗證 active revision 與 audit 相符；容器重建、多 instance 及回復測試均保留已發布版本與完整稽核鏈。

- [ ] **強化病人與醫師 session 識別碼及共用狀態儲存**
  - **問題**：session ID 由 client 提供且可預測，session store 僅是單一 Python process 內的 dictionary。
  - **影響**：可能發生 session 碰撞、接管或跨 worker 狀態丟失；重啟後未完成問診與醫師對話也會消失。
  - **主要檔案／元件**：`backend/app/runtime.py`、`backend/app/routes/patient.py`、`backend/app/routes/doctor.py`、`backend/app/models.py`。
  - **完成條件**：由 server 產生高熵且不可枚舉的 ID，將狀態放入共用且有 TTL 的 store；通過 session fixation／碰撞、過期、重啟與多 worker 測試。

- [x] **以「看診日期＋掛號編號」保留可溯源歷史**
  - **問題**：掛號編號每日重用，而讀取、寫入或刪除流程若只用編號辨識，無法穩定指向單一歷史病例。
  - **影響**：醫師可能看到錯誤病人、將摘要寫到別筆病例，或刪除同號但不同日的紀錄。
  - **主要檔案／元件**：`backend/infrastructure/consultation_repository.py`、`backend/app/routes/doctor.py`、`frontend/src/views/DoctorView.vue`、`frontend/src/services/clinicalRecord.js`。
  - **完成條件**：編號即掛號編號；緊急掛號每日從 `000` 起、一般掛號每日從 `10000` 起；不使用 UUID 或獨立永久病例 ID，病例唯一鍵為 `consultation_date + registration_number`；醫師端可用日期＋掛號編號看見並精確開啟例如「昨日的 001」及其病人，且跨日同號的查詢、摘要寫入與刪除測試不會操作錯誤紀錄。
  - **完成證據（2026-08-09 review）**：repository 已以
    `consultation_date + display_number` unique index 與 `YYYY-MM-DD:NNN/NNNNN`
    composite ID 實作；跨日 sequence、同號歧義拒絕、報告更新與刪除隔離測試通過。
    Doctor UI 的開啟與刪除操作使用 composite ID，畫面同時顯示日期及掛號編號。

- [ ] **以跨 process 交易保護規則發布與 audit**
  - **問題**：發布 lock 僅在單一 process 內生效，設定檔、revision 與 audit 的寫入不是一個跨 process 原子交易。
  - **影響**：同時發布可丟失更新、產生無對應 audit 的 active config，或留下沒有真正生效的 audit 紀錄。
  - **主要檔案／元件**：`backend/app/services/rule_management_support/publisher.py`、`backend/app/services/rule_management_support/common.py`、持久化儲存與 audit 目錄。
  - **完成條件**：採用跨 process lock 或資料庫交易，將 expected revision 檢查、config 更新與 audit 視為單一交易；並行發布與中途失敗測試證明不會出現部分寫入。

- [x] **無損保留 Safety 條件的 `all_findings` 與 `any_findings`**
  - **問題**：當同一規則同時含有 `all_findings` 與 `any_findings` 時，前端 draft model 只保留其中一組，存檔 round-trip 會遺失資料。
  - **影響**：醫師即使沒有刻意修改該條件，重新發布也可改變 Safety 觸發邏輯，導致漏報或過度警示。
  - **主要檔案／元件**：`frontend/src/composables/safetyRuleGovernance.js`、`frontend/src/components/safety-governance/SafetyImplementationEditor.vue`、`backend/app/models.py`。
  - **完成條件**：前端 model 可同時表達、編輯與序列化兩組條件；以同時含兩組的 fixture 完成 load → edit/no-op → publish round-trip 測試，且後端執行語意不變。
  - **完成證據（2026-08-09）**：editor draft 現分別保存兩組 finding selection，切換
    operator 不會刪除另一組；round-trip fixture 同時載入兩組、修改其中一組並驗證發布
    payload 仍保留兩者。Backend 原有 structured evaluator 依序以 AND／OR 語意計算兩組。

### Medium

- [ ] **禁止靜默截斷臨床輸入與證據**
  - **問題**：多處 validator 與轉換邏輯以固定字數或數量直接截斷病人回答、evidence 及問卷資料，但未告知使用者或下游流程。
  - **影響**：具分流價值的句尾或後續答案可能消失，摘要與決策也無法區分「未提供」和「已被系統截斷」。
  - **主要檔案／元件**：`backend/app/models.py`、`backend/amie/clinical_facts.py`、`backend/amie/chief_complaint.py`、`backend/amie/engine.py`。
  - **完成條件**：對超限輸入明確拒絕、分頁／分段或保留可觀測的 truncation metadata；邊界值與長輸入測試證明重要臨床內容不會無警示消失。

- [ ] **為背景摘要建立 durable job 與失敗復原機制**
  - **問題**：醫師摘要使用 process-local background task，process 重啟或任務失敗後沒有可靠的重試與接續處理。
  - **影響**：病例可長時間停留在 `summary_pending`，或只留下不完整摘要，醫師不知道是否會自動復原。
  - **主要檔案／元件**：`backend/app/routes/patient.py`、`backend/app/services/consultation_service.py`、`backend/app/services/consultation_reporting.py`、`backend/infrastructure/consultation_repository.py`。
  - **完成條件**：任務與 retry state 持久化，支援冪等重試、死信／人工重跑與逾時監測；在摘要生成中止 process 後，整合測試可自動完成或明確標記可處理失敗。

- [x] **避免在 async route 內同步等待 LLM**
  - **問題**：部分 `async` FastAPI 路由直接呼叫同步 LLM client。
  - **影響**：慢速或卡住的 model request 會阻塞 event loop，拖慢其他病人問診和醫師請求。
  - **主要檔案／元件**：`backend/app/routes/patient.py`、`backend/app/routes/doctor.py`、`backend/infrastructure/llm.py`。
  - **完成條件**：改用真正 async client 或有界限的 thread／job queue，加入 timeout、cancellation 與 concurrency limit；並行慢速 LLM 測試證明 health check 與無關 API 仍可在預期時間內回應。
  - **完成證據（2026-08-09）**：病患 chief extraction／AMIE turn 與醫師聊天的同步模型
    工作改由 bounded clinical worker 執行，預設最多 4 個、45 秒 timeout；逾時採病患
    handoff 或醫師端穩定 503；同一病患 interview 的 request 另以 per-session async lock
    序列化。測試覆蓋 event-loop responsiveness、health endpoint、timeout、並行容量上限
    及同 session 競態。

- [x] **對外統一錯誤格式，不回傳內部 exception 原文**
  - **問題**：部分 API 將 `str(error)` 直接放入 HTTP response。
  - **影響**：回應可暴露內部服務地址、查詢細節、檔案路徑或第三方錯誤內容，並讓前端難以穩定處理錯誤。
  - **主要檔案／元件**：`backend/app/routes/doctor.py`、`backend/app/routes/system.py`、`backend/app/services/rag.py`、全域 exception handler。
  - **完成條件**：client 僅收到穩定 error code、安全文案與 correlation ID，完整 exception 僅出現在受保護 log；以敏感錯誤字串的測試證明 response 不會洩漏原文。
  - **完成證據（2026-08-09）**：HTTP、request validation 與未處理 exception 統一加入
    `error_code`、`correlation_id` 及相同 response headers；validation 不再反射 rejected
    input，服務錯誤改用安全文案。受保護 log 只記 correlation、path 與 exception type，
    不記可能含 PHI／credential 的 exception 原文；敏感連線字串 regression test 通過。

- [ ] **加強 prompt trust boundary 與 injection 防護**
  - **問題**：病人原話、FHIR 內容與 RAG 片段被嵌入 prompt，但不可信資料與系統指令的邊界不夠完整。
  - **影響**：惡意或意外文本可干擾摘要、翻譯與醫師問答規則，造成不可靠輸出、資料越界或敏感資訊暴露。
  - **主要檔案／元件**：`backend/app/prompts/doctor.py`、`backend/app/prompts/report.py`、`backend/app/services/consultation_reporting.py`、`backend/knowledge/translation.py`。
  - **完成條件**：不可信內容以明確結構與欄位傳入、不可覆寫 system policy，輸出通過 schema／允許清單驗證；prompt injection regression suite 覆蓋病人、FHIR 與 RAG 來源。

- [x] **確實關閉每個 SQLite connection**
  - **問題**：`sqlite3.Connection` 的 context manager 只處理 commit／rollback，不保證關閉 connection；現有 repository 因此出現 `ResourceWarning`。
  - **影響**：長時間執行可累積 file descriptor、lock 與記憶體資源，增加 SQLite busy／locked 與作業系統資源耗盡風險。
  - **主要檔案／元件**：`backend/infrastructure/consultation_repository.py`、其他直接使用 `sqlite3.connect` 的後端模組。
  - **完成條件**：所有 connection 在成功與 exception 路徑均確實 `close`；重複 repository 操作測試在啟用 `ResourceWarning` 為 error 時通過，並不留下額外開啟的檔案描述元。
  - **完成證據（2026-08-09）**：repository 所有短連線皆以 `closing(connection)` 包覆，
    並保留 SQLite context 的 commit／rollback 語意；tracking regression test 驗證查詢成功
    與 synthetic SQL exception 後都會呼叫 `close`，完整 repository suite 通過。

- [ ] **修正 Safety 編輯器的 hidden selection 與非同步取消 race**
  - **問題**：過濾後隱藏的已選特徵可能仍被發布；使用者取消編輯或切換群組後，較早的規則助理 request 仍可回寫新狀態。
  - **影響**：醫師在畫面上看不到實際將發布的完整條件，或已放棄的 AI 草稿之後又出現，導致誤發布 Safety 邏輯。
  - **主要檔案／元件**：`frontend/src/composables/safetyRuleGovernance.js`、`frontend/src/components/safety-governance/SafetyImplementationEditor.vue`、`frontend/src/components/safety-governance/SafetyDraftAssistant.vue`。
  - **完成條件**：編輯器始終顯示已選但不符當前過濾的數量並可一次清除；取消、切群組或 unmount 會 abort／忽略舊 request；component 測試覆蓋 out-of-order response 與 hidden selection 發布預覽。
  - **進度（2026-08-09）**：已顯示兩組 operator 的選取數量、目前 filter 隱藏數量及
    一次清除操作；切群組、取消或 scope dispose 會 abort 並以 sequence guard 忽略舊
    response，純函式／composable regression 與 production build 通過。尚缺 Vue mount
    component test，因此依原完成條件維持未勾選。

### Quality／測試與 CI

- [ ] **補齊 Vue mount、瀏覽器互動、視覺與 CI 品質門檻**
  - **問題**：現有前端測試主要覆蓋純函式，缺少關鍵 Vue component mount、真實瀏覽器互動／responsive 與視覺 regression，CI 也未強制所有品質檢查。
  - **影響**：props／emit 接線、focus、keyboard、race condition、小螢幕版面與 CSS 回歸可通過 unit test 及 build 後才在使用者端出現。
  - **主要檔案／元件**：`frontend/src/components/`、`frontend/src/views/`、`frontend/tests/`、`package.json` 測試腳本與 CI workflow。
  - **完成條件**：重要病人問診、醫師病例、Safety／疾病治理流程具有 component mount 與瀏覽器 E2E；關鍵 viewport 通過 accessibility 與視覺 regression；CI 必須通過 backend tests、frontend tests、build、lint、OpenAPI contract 與前端 API contract 後才能合併。

## 目前狀態

胸痛、頭痛、腹痛問卷、確定性疾病表投票、RAG v2、SMART OAuth launch context
與規則治理原型均已可運行。待辦重點是醫療專業審查、正式身分與權限整合、
FHIR 回寫治理，以及疾病表權重與 SNOMED CT coding 的醫師校準；詳見
[開發文件](docs/README.md)。

## TODOs

- 引入閩南語、客家語等語音模型
- 選擇的選項要能取消
- 點選疼痛位置的左右要放大
- 回到上一題的功能
- 設定好另一台電腦當後端，測試在ucc上面的效果
