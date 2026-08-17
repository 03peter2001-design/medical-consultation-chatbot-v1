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
