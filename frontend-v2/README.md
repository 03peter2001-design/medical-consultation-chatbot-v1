# Frontend V2

This workspace produces two deliberately isolated Vue applications from the
same clinical component library.

## Service versions

The initial versions were reconstructed from the existing `devlog/` records and
do not have matching Git tags; newer entries continue that documented release
line. They do not by themselves mean that a build was released, deployed, or
clinically approved. The doctor and patient apps are independently
versioned services, and this deployment line also evolves independently from
`frontend/`. API `/v1`, database schemas, disease profiles, and Safety rules keep
their own versions or revisions.

### Doctor app

#### v2.2.0 (2026-09-09)

- 新增七段醫師摘要的逐欄編輯與確認流程；任何修改都會撤銷該欄確認狀態，七段全部
  確認後才可進入 FHIR 送出預覽。
- 串接既有 `POST /v1/doctor/consultations/{consultation_id}/fhir-composition`，要求
  `consultation:fhir-write` scope、可信任 Patient context 與病例版本，並把送出結果明確
  標示為 `preliminary` Composition，不視為電子簽章或臨床核准。
- 保留正式版 UCC bootstrap、CSRF 與 encounter 綁定的邀請流程；未帶入開發版僅允許
  loopback legacy principal 的 SMART Doctor Launcher。若 UCC 尚未核發 FHIR scope、
  `fhirUser` 或可信任 FHIR context，寫入操作會安全停用。
- Node 22 的 14 個 frontend-v2 測試檔及 Doctor production build 通過。

#### v2.1.1 (2026-09-09)

- Doctor API request 與 401 refresh retry 一律使用瀏覽器 `no-store` cache mode，避免首次
  UCC 驗證的暫時性錯誤被同一病例清單 URL 重用；refresh 後仍以新的 Bearer token 重試。
- 回歸測試驗證初次 401、token refresh、第二次請求 header 與兩次 no-store 行為；Patient
  app 不引用這個 doctor API client，因此 Patient 版本維持 v2.1.0。

#### v2.1.0 (2026-08-09)

- Preserved readable route and field labels when rendering candidate or historical
  questionnaire records, without activating provisional questionnaires at runtime.
- Verified the doctor production bundle and the shared behavior test suite with
  Node 22.

#### v2.0.0 (2026-08-07)

- **2026-08-06 — Isolated UCC doctor application**
  - Introduced the separately built doctor app at `/ai-consult/`, exposing only
    the doctor workspace and rules routes.
  - Added UCC bootstrap for a short-lived access token kept only in memory, with
    doctor requests isolated from the patient bundle and patient authentication
    flow.
  - Added bootstrap, route-isolation, and production bundle source-graph tests.
- **2026-08-07 — Encounter-free workspace and stricter session handling**
  - Allowed the dashboard to run without `regSno` or an encounter for case
    browsing, the doctor assistant, and the rules center.
  - Kept patient invitation visible but disabled outside an encounter, added a
    current-encounter status indicator, and required bootstrap capability, CSRF,
    and matching encounter context before inviting a patient.
  - Classified redirects, 401/403 responses, non-JSON content, and malformed JSON
    as expired UCC sessions instead of accepting login-page HTML as bootstrap data.
  - Standardized structured EMR summaries into the same two-line display used by
    the development frontend.

### Patient app

#### v2.2.0 (2026-09-09)

- 在既有 HttpOnly session gate 加入 QR 相機掃描與貼上完整邀請網址；優先使用瀏覽器
  `BarcodeDetector`，不支援時延遲載入 ZXing，並在任何相機失敗路徑保留貼碼方式。
- 先驗證既有 cookie session，再交換單次 opaque code 並重新取得 session；避免成功交換後
  因暫時性驗證錯誤重送已消耗 code。畫面只顯示伺服器回傳的可信任 Patient／Encounter，
  並驗證完整 active session schema；不從 code 解碼病人資料，也不接受瀏覽器覆寫
  invitation FHIR context。
- 對齊新版 SMART/FHIR reader、Synthea default identifier、國語／台語逐請求語言、Avatar
  預載與背景生成，以及文字和結構化題目的語音活動偵測、可確認辨識結果與失敗重問。
- 疼痛圖與 headache／chest／abdomen 問卷選項雙向同步；精細部位不明時不推測左右側，
  並維持單一選項群組與送出動作。
- Node 22 的 14 個 frontend-v2 測試檔及 Patient production build 通過。npm audit 另回報
  18 個來自 `fhirclient`／`isomorphic-webcrypto` optional React Native／Expo 相依鏈的上游
  moderate／high advisories；瀏覽器 production bundle 未載入該 mobile toolchain，仍待
  上游提供不破壞相容性的更新。

#### v2.1.0 (2026-08-11)

- 在問診主畫面新增 Patient 專用的常駐 Avatar 舞台：本地服務生成 MP4 時顯示醫師、
  當次朗讀字幕與生成／播放狀態，原有聊天訊息與作答流程維持可見可用。
- 本地 MP4 使用有聲自動播放並保留原生 controls；瀏覽器拒絕播放時，舞台顯示明確的
  「播放醫師語音」按鈕與提示，讓病人用一次點擊恢復聲音。
- 設定 drawer 改為靜態醫師預覽，避免與主舞台同時播放同一段影片造成重複音訊；
  provider、D-ID 記憶體內憑證與本地預設行為不變。
- 共享 Avatar 模組目前只由 Patient app 引用，因此 Doctor app 版本與執行路徑未變更。

#### v2.0.1 (2026-08-09)

- Made direct-FHIR URL query overrides fail closed unless an explicit development
  flag and exact-origin allowlist are both configured; production ignores them.
- Replaced broad routing-keyword symptom detection with a narrow presentation-term
  matcher and ASCII token boundaries so unrelated diagnoses remain in FHIR history.
- Verified the patient production bundle and shared FHIR regression tests with
  Node 22.

#### v2.0.0 (2026-08-07)

- **2026-08-06 — Isolated invitation-based patient application**
  - Introduced the separately built patient app at `/`, without doctor routes or
    doctor API clients in its bundle.
  - Read the one-time invitation token from the URL fragment only after explicit
    confirmation, exchanged it for an HttpOnly session cookie, and then removed
    the fragment so patient identity is not retained in the URL.
  - Added invitation-token, route-isolation, and production bundle source-graph
    tests.
- **2026-08-07 — Correctable questionnaire flow and local media providers**
  - Added option deselection, mutually exclusive “other” text, and a back action
    that removes the last visible answer and trace before re-answering.
  - Improved left/right labels on the enlarged body pain map and standardized
    legacy structured summaries into the two-line EMR display.
  - Made local Breeze-ASR-26 transcription and CosyVoice3 + MuseTalk Avatar the
    default path, while retaining the pinned, locally bundled D-ID browser
    provider as an optional choice.

### Shared package (not an independently versioned service)

`packages/shared/` is a source library consumed by both apps, not a separately
deployed service and therefore has no service version in this document. The
2026-08-06 split moved shared consultation, FHIR, terminology, structured-record,
body-map, rule-governance, and clinical-evidence code into this package. The
2026-08-07 questionnaire correction, body-map, EMR rendering, and patient Avatar
changes were implemented through the relevant shared modules while doctor and
patient authorization, routing, and bootstrap boundaries remained app-specific.
The 2026-09-09 parity update added clinician-reviewed FHIR Composition submission,
SMART/FHIR context helpers, invitation parsing, questionnaire voice mapping, and
precise/coarse pain-location synchronization. These shared capabilities remain
guarded by each app's independent authorization and session boundary.

## Commands

```bash
npm install
npm run dev:doctor
npm run dev:patient
npm run build
npm test
```

- Doctor app: `/ai-consult/`, hash routes `/doctor` and `/doctor/rules`, API
  base `/ai-api`.
- Patient app: `/`, no doctor routes, API base `/api`.

The doctor app obtains a short-lived UCC access token from
`/AiConsult/Bootstrap`; the token stays in memory. The patient app exchanges a
token from the URL fragment only after explicit confirmation and then relies on
an HttpOnly session cookie. Never place patient identity data in either URL.

See each app's `.env.example` for deploy-time overrides.

Production builds ignore `?fhir=` and `?directFhir=` URL overrides. The shared
FHIR client only accepts them in an explicit development build with
`VITE_ENABLE_FHIR_QUERY_OVERRIDE=true` and an exact-origin
`VITE_FHIR_QUERY_OVERRIDE_ORIGINS` allowlist; deployed patient identity data
must use the configured same-origin proxy or SMART client.

## Patient avatar providers

The patient app defaults to the local CosyVoice3 + MuseTalk service and retains
the optional D-ID Agent SDK flow. Configure the build with:

```dotenv
VITE_AVATAR_PROVIDER=local # local or did
VITE_DID_CLIENT_KEY=
VITE_DID_AGENT_ID=
```

The pinned `@d-id/client-sdk` npm dependency is emitted as a local lazy-loaded
JavaScript chunk. The browser does not fetch executable SDK code from a runtime
CDN.

D-ID credentials can instead be entered in the Avatar drawer and remain only
in page memory. Every `VITE_*` value is compiled into public browser JavaScript;
never place a server secret there. If preconfiguration is required, use only a
D-ID browser/embed key restricted to the deployed origin.
