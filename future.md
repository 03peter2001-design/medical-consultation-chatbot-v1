# 開發端與 SMART 臨床應用端拆分計畫

> 文件狀態：未來概念規劃，尚未進入實作，實際執行需配合院方系統與政策確認。
> 本文件不代表目前系統已具備正式院方登入、健保卡驗證或正式醫療環境部署能力。
> README 摘要請見 [未來展望：正式 SMART 臨床應用](README.md#未來展望正式-smart-臨床應用)。

## 摘要

- 先維持單一 repository，拆成兩個可獨立建置、部署的產品：
  - `frontend`：還原並保留 SMART 整合前的原始開發端。
  - `clinical-frontend`：正式應用端，共用程式碼但分別編譯為 Patient Shell 與 Clinician Shell。
- FastAPI 維持一份程式碼，依 `development`／`clinical` profile 啟動不同路由、設定、Session 與資料庫。
- 病患主動登入、填寫並送出問診；醫師只查看已送出的個案，不建立或派送病患表單。
- SMART Launcher `8090` 僅作為本機 EHR／授權沙盒，不納入正式醫院介面。

## 專案與部署結構

- 開發端保留 SMART 整合前的原始 UI、API 行為與測試資料流程；搬移目前新增的 SMART 程式時，不覆蓋或丟棄其他未提交修改。
- `clinical-frontend` 使用 `APP_SHELL=patient|clinician` 分別編譯，避免把醫師功能打包進病患端：
  - 開發端：`http://127.0.0.1:5173`
  - Patient Shell：`http://127.0.0.1:5174`
  - Clinician Shell：`http://127.0.0.1:5175`
  - 本機 SMART Launcher：`http://127.0.0.1:8090`
- 建立獨立的 development／clinical Compose 設定。兩套後端使用不同環境變數、資料庫、Session 與 volume，不共用病患資料。
- Clinical profile 不掛載原本未驗證的 `/doctor` 路由；Development profile 保留原始行為。
- 等臨床端 API 契約穩定後，`frontend` 與 `clinical-frontend` 可直接移至不同 repository，不在第一階段拆 Git 歷史。

## 身分驗證與安全管線

- 醫師支援兩種入口：
  - 從院方 EHR 進入：SMART EHR Launch，取得目前的 Practitioner、Patient、Encounter context。
  - 直接開啟醫師端：導向院方 OIDC／SSO；沒有 Patient context 時顯示完整待處理佇列。
- 病患從 Patient Shell 主動進入 SMART/OIDC 流程；驗證完成後讀取本人 FHIR 資料、完成問診並送出。
- 使用 Authorization Code、PKCE、`state`、`nonce`、issuer allowlist、JWKS 與 ID token 驗證，並採用 `openid fhirUser` 取得 FHIR 身分。流程遵循 [SMART App Launch](https://hl7.org/fhir/smart-app-launch/STU2.2/app-launch.html) 與 [Launch Context／Scopes](https://hl7.org/fhir/smart-app-launch/scopes-and-launch-context.html)。
- 改成後端 BFF 模式：
  - FHIR access/refresh token 只存在後端 Session。
  - 瀏覽器只持有 Secure、HttpOnly、SameSite Session cookie。
  - 前端不再使用 `fhirclient` 直接讀取 `$everything`，也不將 token 放入 storage、網址或 log。
- 新增分眾驗證介面：
  - `/api/patient/auth/start|callback|session|logout`
  - `/api/clinician/auth/oidc/start`
  - `/api/clinician/auth/smart/start`
  - `/api/clinician/auth/callback|session|logout`
  - `AUTH_MODE=mock` 時才啟用本機病患、醫師、規則管理員模擬帳號；production 設定禁止啟用。
- Session 回傳統一為 `AuthSession`，包含 audience、subject、顯示名稱、roles、issuer、fhirUser，以及可選的 patient/encounter context。
- 權限角色：
  - `patient`：只能操作自己的問診。
  - `clinician`：可查看個案、使用 RAG/AMIE、SNOMED。
  - `rule_admin`：額外允許修改規則中心。
- 院方透過設定提供 issuer、client ID、redirect URI、claim 名稱與 group-to-role mapping；claims 無法映射時預設拒絕登入。
- 本機使用記憶體 Session adapter；正式部署強制改用相同介面的 Redis adapter。
- Clinical API 使用精確 CORS allowlist、CSRF token、Session TTL、登出失效與 API 端角色檢查。原本的規則管理 token 只保留在 Development profile。

## 臨床工作流程與資料

- Patient Shell 僅呈現病患身分確認、FHIR 資料預填、問診與送出結果，不顯示醫師入口、開發資訊、FHIR resource count 或管理工具。
- 病患完成送出後，個案才會出現在 Clinician Shell；尚未完成的草稿不進入醫師佇列。
- Clinician Shell 保留現有視覺風格及功能，增加登入頁、醫師名稱／院所／角色、登出、目前 Patient／Encounter context。
- EHR Launch 選定病患時：
  - 先以 `issuer + encounter_id` 找到已送出個案。
  - 找不到時再列出相同 `issuer + patient_id` 的近期個案。
  - 完全沒有個案時顯示「目前沒有病患送出的個案」，不建立表單、不產生交接連結。
- Consultation schema 新增 nullable 欄位：
  - `fhir_issuer`
  - `fhir_patient_id`
  - `fhir_encounter_id`
  - `auth_subject`
- 為 issuer/patient 與 issuer/encounter 建立索引；既有資料仍可用 queue number 查詢，不將 Development 資料搬入 Clinical 資料庫。
- FHIR 讀取 scope 改為可設定的最小權限，涵蓋實際預填使用的 Patient、Encounter、Condition、Observation、AllergyIntolerance、MedicationRequest／MedicationStatement、Procedure、QuestionnaireResponse。
- RAG、Gemini 英文術語翻譯、本機向量檢索、AMIE、SNOMED 與規則中心邏輯維持不變，只加上 Clinical API 權限保護。本階段不實作 FHIR write-back、健保卡驗證或醫師主動派送表單。

## 測試與驗收

- 驗證 PKCE、state、nonce、issuer、JWKS、audience、過期 token、錯誤 callback 與缺少 claim 時皆能安全失敗。
- 驗證病患、醫師、規則管理員的 API 權限隔離，以及 CSRF、CORS、cookie path/屬性和登出失效。
- 確認 access token 不出現在 local/session storage、DOM、網址、前端 bundle log 或後端一般 log。
- E2E 驗收：
  - 病患登入、FHIR 預填、完成問診後才出現在醫師佇列。
  - 醫師 OIDC 登入能看到待處理佇列。
  - SMART EHR Launch 能依 Patient／Encounter 自動定位既有個案。
  - 選到尚未送出問診的病患時只顯示空狀態。
  - Patient Shell 無法載入 Clinician 路由或 API。
  - Clinician 無 `rule_admin` 時無法修改規則。
- 對 Development profile 跑完整既有回歸測試，確認 `5173` 的原始功能與 SMART 整合前一致。
- 分別建置 patient 與 clinician bundle，確認兩個 origin 可獨立部署，且 Patient bundle 不包含醫師頁面。
- 沿用現有外觀，本階段不製作 ImageGen 視覺概念稿；重點是完成可替換院方設定的標準驗證與部署管線。
