# SMART on FHIR 本機整合應用

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
`http://127.0.0.1:8080/fhir`. Start the FastAPI backend, SMART Launcher,
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

目前 scopes 只包含病人資料讀取，系統不會自動把 AI 內容寫回 FHIR。正式回寫
需要醫師確認、版本衝突、Provenance、AuditEvent 及失敗復原流程。本機 SMART
Launcher 不是正式身分系統。

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
