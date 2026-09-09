# SMART on FHIR 本機整合應用

## 服務版本

目前文件基線為 **SMART sandbox/app v1.1.2**（截至 2026-08-28）。這是依
`devlog/` 回溯整理的文件版本，用來描述當時已整合的本機 SMART 開發能力；
repository 目前沒有與此版本對應的 Git tag，也不代表正式臨床部署版本。

### v1.1.2 (2026-08-28)

- 修正本機 SMART Launcher gateway 的 CORS preflight：允許前端防止病歷快取時使用的
  `Cache-Control`，以及瀏覽器可能伴隨的 `Pragma` request header。OAuth token exchange
  成功後，Patient 與 `$everything` request 不再被瀏覽器攔截成 `Failed to fetch`。
- FHIR root proxy 接受 HAPI Bundle pagination link 的精確 `/fhir` compatibility alias，
  避免 SMART public base 再附加 HAPI base 後形成 `/v/r4/fhir/fhir?...` 並回傳 404。
- SMART Backend 的受信任 issuer 會跟隨 `SMART_LAUNCHER_PORT` 設為瀏覽器實際使用的
  loopback public issuer，不再誤用只能在 Compose 網路內解析的 `fhir-root-proxy` 名稱。
- CORS origin 仍只允許帶明確 port 的 `http://127.0.0.1`／`http://localhost`，不放寬成
  wildcard；回歸測試、Nginx config check、實際 preflight 與合成病人 SMART launch 驗證
  記錄於 2026-08-28 devlog。

### v1.1.1（截至 2026-08-25）

- 修正 sandbox 內建 Vue app 的 SMART patient cache：快取現在以 OAuth callback
  `state` 區隔；從 Launcher 重新選擇病人產生新 state 時，會重新讀取 token 中的
  Patient ID、Patient resource 與 `$everything`，不再沿用上一個 launch 的姓名。
- 合成回歸測試確認連續兩個 launch state 會取得不同 Patient ID 與姓名；frontend
  17 組 Node tests、production build 與 OpenAPI type check 通過。因本機 HAPI／SMART
  Compose services 當下未啟動，實際 Launcher OAuth round trip 仍待啟動 sandbox 後驗證。

### v1.1.0（截至 2026-08-25）

- 合成資料沙盒明確啟用 Backend FHIR Composition writer，使用內部
  `http://hapi:8080/fhir` 寫入，並保存由伺服器設定的 sandbox issuer 作為病例來源；
  修正 Compose 內部 HAPI service port 為容器實際監聽的 8080。
- SMART 瀏覽器 token 仍不傳給 Backend；沙盒只保存 Patient／Encounter ID，醫師完成
  七段摘要確認後由 Backend 的獨立寫入設定建立 `preliminary` Composition。重試使用穩定
  consultation identifier 避免重複建立。
- `FHIR_PATIENT_CONTEXT_INPUT_ENABLED`、loopback auth bypass 與本機 clinician fallback
  是此合成沙盒的明示開發例外，不得沿用至正式部署。正式環境仍須受信任的 patient
  context、Backend Practitioner 身分與核准的最小寫入 scope。

### v1.0.0（截至 2026-08-05）

- **2026-07-29 — 建立 SMART on FHIR 開發沙盒**
  - 將本機 SMART Launcher、FHIR root proxy、FastAPI 與 Vue production build
    組成完整 Compose stack，並重用 HAPI FHIR R4 Server。
  - Provider EHR Launch 與 standalone patient launch 完成 OAuth 後，會回到實際
    病患問診；前端恢復 SMART client，讀取 launch-context Patient 與
    `Patient/{id}/$everything`，映射基本資料、病史、手術、用藥與過敏後開始問診。
  - OAuth callback 會處理 pending launch、清除 authorization code，並保留
    Patient／Encounter context；FHIR access token 僅用於瀏覽器呼叫 FHIR Server，
    不送往問診 API、RAG 或外部模型。
  - Vue 與 FastAPI 改為同源 `/api` reverse proxy，加入 Launcher CORS gateway、
    `no-store` discovery response、安全 headers、synthetic patient 啟動頁、port
    override 與持久化 consultation volume。
  - App image 固定並本機提供 `fhirclient` 2.6.3；runtime 以唯讀、offline 方式
    掛載 RAG／模型 cache，環境限定使用合成資料。
- **2026-08-04 — API 契約與操作文件同步**
  - SMART Compose、啟動腳本及文件統一改用版本化 `/api/v1/health` 健康檢查。
  - 補齊啟動前置條件、OAuth／FHIR 預填資料流、同源 proxy、唯讀 scopes、模型
    cache、SQLite volume 與正式 FHIR 回寫治理邊界。
- **2026-08-05 — 容器網路與測試資料啟動流程修正**
  - backend 與 FHIR reverse proxy 改用 Compose service `hapi:8080`，不再依賴
    host gateway。
  - `start-smart.sh` 啟動前會冪等確認並匯入兩筆合成病人 Bundle；啟動 Compose
    時不再自動移除其他服務容器。

This directory contains the launch pages and container configuration for the
full Vue consultation application:

- `launch.html`: provider EHR launch entry point
- `launch-patient.html`: standalone patient launch entry point
- `start.html`: local synthetic-patient launcher
- `nginx.conf`: serves the Vue build and proxies `/api` to FastAPI
- `../smart-deployment/smart-launcher-gateway.conf`: normalizes local SMART
  Launcher CORS by preserving the requesting localhost/127.0.0.1 port

Proxy 設定的責任請見
[`../smart-deployment/README.md`](../smart-deployment/README.md)。

The OAuth redirect returns to the Vue application. The frontend restores the
authorized `fhirclient`, reads the launch-context Patient and
`Patient/{id}/$everything`, maps the clinical resources into the existing
questionnaire prefill, and starts the consultation. The access token is not
sent to the consultation backend.

The local stack reuses the existing HAPI FHIR R4 server at
`http://127.0.0.1:8081/fhir`（可由 `FHIR_PORT` 覆寫）. Start the FastAPI backend, SMART Launcher,
internal FHIR path proxy, and Vue application from the repository root:

```bash
./scripts/start-smart.sh
```

啟動前必須先：

1. 依 [術語文件](../backend/terminology/README.md) 啟動 HAPI FHIR
2. 匯入 `backend/fhir_samples/` 的合成 FHIR bundles
3. 建立並填妥 `backend/.env`
4. 第一次使用 RAG 時執行 `./scripts/bootstrap.sh --with-rag`

接著開啟 `http://127.0.0.1:5174/start.html` 選擇合成病人。此頁會透過
`http://127.0.0.1:8090` 建立 R4 Provider EHR Launch；授權成功後進入真正的
Vue 病患問診介面。

```text
EHR Launch → OAuth 授權 → Patient launch context → FHIR $everything
→ 病歷預填 → AI 預問診 → 問診編號／醫師端
```

Vue 與 FastAPI 由同一 App origin 的 `/api` reverse proxy 串接。FHIR access
token 只由瀏覽器中的 SMART client 用於 FHIR Server，不會送入 `/chat`、RAG
或外部模型。

To configure the Launcher manually, open `http://127.0.0.1:8090` and use
`http://127.0.0.1:5174/launch.html` as the launch URL.

This is a development sandbox. It is not configured for production use or
real patient data. Production deployment still requires client registration,
TLS, trusted redirect URIs, user authorization, least-privilege scopes, audit
logging, backend authentication, and an approved clinician-confirmed FHIR
write-back workflow.

瀏覽器 scopes 只包含病人資料讀取，系統不會把瀏覽器 token 交給 Backend。此沙盒會在
醫師逐段確認及送出前總覽後，由 Backend 以開發環境設定寫入 `preliminary`
Composition；不代表電子簽章或正式臨床核准。正式回寫仍需院方核准的 server-side
credential、可信 Practitioner 身分、版本衝突、Provenance、AuditEvent 及失敗復原
流程。本機 SMART Launcher 不是正式身分系統。

The API image installs `backend/requirements-runtime.txt` plus the reviewed
CPU-only RAG dependencies, and mounts the host `backend/chroma_db` and cached
embedding model read-only. Run `./scripts/bootstrap.sh --with-rag` before the
first SMART startup. `start-smart.sh` verifies the index, model cache, and
backend `/api/v1/health` `rag_enabled` response before reporting the stack ready. RAG
supports clinician research features and background reporting; the
deterministic patient interview does not use RAG for Safety or disease votes.

PyTorch 固定由官方 CPU-only wheel index 安裝。Hugging Face model cache 預設位於
`.rag-cache/huggingface/hub`；需要重用其他 cache 時：

```bash
RAG_HF_HUB_CACHE=/其他路徑 ./scripts/start-smart.sh
```

SMART runtime 以 offline、唯讀方式載入 model cache，並關閉 Hugging Face 與
Chroma telemetry。問診 SQLite 保存於 Docker volume `consultation-data`，一般
停止不會刪除。

The app image pins `fhirclient` 2.6.3 and serves it locally from
`/vendor/fhir-client.js`; loading the app does not depend on a JavaScript CDN.

Override the SMART-facing ports when needed:

```bash
SMART_LAUNCHER_PORT=8091 SMART_APP_PORT=5175 \
  ./scripts/start-smart.sh
```

Stop the local stack without deleting its PostgreSQL volume:

```bash
docker compose -f compose.smart.yml down
```
