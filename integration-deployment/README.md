# UCC doctor + external patient deployment

This directory contains a deployment blueprint only. Nothing here overwrites
`C:\Deploy\eHIS`, starts IIS, or starts Ubuntu services until an administrator
explicitly runs the scripts.

## Service version

目前版本為 **integration deployment bundle v1.6.0（2026-09-11）**。
這是依 `devlog/` 回溯整理的部署文件版本，用來標示安全整合藍圖、雙前端與
GPU／Avatar 部署能力的共同基線；repository 目前沒有與此版本對應的 Git tag，
也不表示任何院所環境已完成正式上線驗收。

### v1.6.0 (2026-09-11)

- B01 掛號成功後會以資料庫掛號流水號 `regSno` 呼叫獨立的
  `AiConsult/RegistrationInvitations`，並直接在掛號介面以 eHIS 既有的本機
  Syncfusion QR renderer 顯示患者預問診 QR Code；邀請失敗不會回滾已完成的掛號，
  且可在原畫面重試。
- 掛號邀請端點保留 antiforgery、同院所與稽核邊界，只允許具有 B01 選單權限且
  `registered_user_id` 與登入帳號相同的建立者，並僅接受當日未報到、候診或看診中的
  掛號；原醫師／代診邀請端點及其 `0/1` 狀態限制不變。
- 新增可重複執行、先備份且遇到未知 eHIS source anchor 會拒絕部分安裝的整合安裝器，
  以及只修改 `AiConsult:BackendBaseUrl` 的安全設定工具，避免伺服器端邀請誤送至
  patient SPA 的 443 listener。
- 驗證涵蓋 `regSno`／antiforgery／no-store request contract、HTTPS patient URL、
  403／404／502 非破壞性錯誤狀態、B01 授權 source contract 與 eHIS .NET build。

- Backend 的 Compose 環境範例新增 Gemini 任務分流：固定問卷七個病史擷取任務與
  RAG query translation 使用 `gemini-3.5-flash-lite`，五個 RAG／臨床決策任務使用
  `gemini-3.6-flash`。
- `backend/.env` 與 `integration-deployment/.env` 仍是彼此獨立的本機設定來源；部署
  bundle 只透過本目錄 `env_file: .env` 注入容器，不會讀取或同步 `backend/.env`。
  更新模型設定後需重新建立或重啟 backend container 才會清除 process-level client cache。
- 未改變 Compose 網路、祕密掛載、RAG corpus、臨床規則或 API 契約；既有
  `GEMINI_MODEL` 仍可作為未設定專用模型時的相容回退。

### v1.5.3 (2026-09-09)

- 明確設定 UCC JWT clock-skew 容忍預設 30 秒，Backend 只接受 0–300 秒，避免 eHIS 與
  Ubuntu 主機的正常小幅時差造成剛簽發 token 暫時 401；不放寬簽章、issuer、audience、
  scope 或機構隔離。
- Nginx 三個 API proxy 入口會移除 upstream cache metadata，再固定回傳 `no-store`；IIS
  doctor 靜態設定亦禁止沿用舊 SPA shell，避免暫時性 401 或病例回應被快取。
- Doctor 部署腳本從 Vite entry hash 更新 eHIS `AiConsult/Index.cshtml` 的 iframe
  `assetVersion`，讓一般重新整理也能取得新 bundle；腳本仍不 publish 或 restart IIS。
- 靜態部署驗證涵蓋 clock-skew、Nginx／IIS no-cache 與 iframe cache-buster invariants。

### v1.5.2 (2026-08-17)

- 補充更新前的 SQLite online backup 與既有 Backend／Avatar image 標籤快照流程，
  讓完整 Compose rebuild 前保留可明確選取的程式與資料復原點。
- 記錄完整 rebuild、health／logs 驗證、以 `--no-build` 回退 image，以及只有資料
  不相容時才執行確認式 SQLite restore 的操作順序。
- 明確警告不得在一般更新或回退流程使用 `docker compose down -v`，避免刪除病例、
  模型、Avatar cache 與監視設定的 named volumes。

### v1.5.1 (2026-08-13)

- Gateway healthcheck 改走實際的 HTTPS `/api/v1/health` 反代路徑；若 Nginx 無法連到
  Docker 內部的 `backend:8000`，gateway 不再誤顯示 healthy。
- Ubuntu 部署前置檢查現在要求 `.env`、UCC JWT 公鑰與 TLS 檔案皆為非空的一般檔案，
  避免 Docker 因遺漏 bind-mount 來源而建立同名目錄並讓檢查誤判通過。
- Backend 仍只 `expose` 容器內 8000，不新增任何 host port；UCC 持續經 gateway 8443
  存取。驗證包含完整 Compose rebuild、backend 容器內 health 與 gateway upstream health。

### v1.5.0 (2026-08-11)

- 新增 `AVATAR_ANIMATION_ENABLED` 部署開關，預設 `true`，保留既有 MuseTalk
  嘴型動畫行為與相容性；Compose 對 backend 與 Avatar service 顯式提供同一預設。
- 設為 `false` 時，Avatar service 跳過 MuseTalk，以基準醫師靜態圖搭配本機
  CosyVoice 語音輸出；字幕／朗讀文字仍由前端顯示，不改變問診內容或後端 API。
- 正常 frontend → backend 流程由 backend 預設或單次 request override 決定是否動畫；
  Avatar service 的環境值只供直接 caller 或未帶 override 時 fallback。單次切換不需
  重建 Avatar image/container。
- Compose 與靜態部署驗證會檢查此設定仍有明確且向後相容的預設值。

### v1.4.0 (2026-08-10)

- 新增固定於 `amir20/dozzle:v10.6.14` 的輕量容器監視 UI，可在網頁查看本 Compose
  project 的 container status、health、CPU／memory 與即時 logs。
- UI 只發布於 host loopback `127.0.0.1:18080`；遠端管理者必須使用 SSH tunnel。
  Dozzle 不連接 patient、UCC 或 backend networks，也不由 clinical gateway 對外提供。
- Dozzle 不直接掛載 Docker socket；固定版 Docker API proxy 是唯一 socket consumer，
  `POST=0` 並只開放 containers、events、info、ping、version 等監視所需 API sections。
- Actions、shell、MCP 與 analytics 明確停用；API proxy 不發布 host port且只在 internal
  network 與 Dozzle 相連。監視 API 仍可能包含敏感 container metadata，因此 UI 不得
  改綁 LAN 或 public IP。
- 新增 Dozzle 與 API proxy healthchecks、持久化 UI settings volume，以及 resolved
  Compose security invariants，鎖定 loopback port、唯讀 API、停用能力與 networks。

### v1.3.1 (2026-08-10)

- 修正 backend 將 Chroma working index 掛成唯讀，導致
  `PersistentClient` 啟動時因 SQLite bookkeeping 無法寫入而停用 RAG。
- RAG bind mount 現在保留 host 路徑作為持久化來源，但允許 Chroma 必要的內部寫入；
  PowerShell static validator 會拒絕再次加入 `:ro` 的設定。
- 這是部署掛載修正，不變更 RAG corpus、collection 內容、embedding model、醫療規則
  或病患端問診行為。病患端 Safety 與疾病投票仍不使用 RAG。
- 驗證包含 Compose config、backend 重新建立、health 的完整 v2 collections，以及實際
  本機 embedding／Chroma 檢索。

### v1.3.0 (2026-08-10)

- 16 GB RTX 5060 Ti 預設改為 Breeze ASR 與本機 Avatar 模型 warm-up 後常駐，
  不再於每次辨識／影片後卸載；容量較小或並行負載較高的 GPU 可用 release
  flags 回退原有低顯存模式。
- 配合 backend `/v1/avatar/warmup`，前端啟用 Avatar 時才一次載入所有語音與嘴型
  模型；第一次較慢，後續 warm-up 與合成直接重用。
- 實測第一次 warm-up 47.35 秒、第二次 0.005 秒；國語／閩南語連續合成後所有
  模型仍 loaded，常駐約使用 11.5 GB 顯存並保留約 4.3 GB。

### v1.2.0 (2026-08-10)

- 新增只綁定 host `127.0.0.1:18000` 的 Nginx development API，讓開發版
  `frontend/` 固定與 Docker backend 溝通；FastAPI container port 仍不直接發布。
- 開發機可明確設定 `ALLOW_LOCAL_AUTH_BYPASS=true` 與 localhost CORS allowlist；
  `.env.example` 及正式部署預設仍為 `false`，非本機來源繼續要求 patient session 或
  UCC Bearer token。
- Public patient 與 UCC proxy 現在覆寫而非附加用戶傳入的 `X-Forwarded-For`，避免
  外部請求偽裝 loopback；只有 host-loopback development listener 注入
  `127.0.0.1`。
- Gateway 明確加入獨立 edge bridge 以承接 host-published ports；backend 持續只在
  private／egress networks，FastAPI port 不對 host 發布。
- Patient／UCC host ports 可分別以 `PATIENT_HTTPS_PORT`／`UCC_API_PORT` 覆寫，正式
  預設仍為 443／8443；本機已有服務占用時不必破壞既有 listener。
- Backend 修改後可用 `docker compose up -d --build backend` 重建，開發版 Vite
  frontend 保持熱更新；Nginx 會透過 Docker DNS 重新解析重建後的 backend IP，
  Docker volume 成為此流程的病例資料來源。
- 驗證包含完整 Compose build、Nginx syntax、實際 host port bindings、localhost
  CORS、開發白名單、Avatar CUDA status，以及 public TLS 偽造 forwarded-IP 仍回 401。

### v1.1.0 (2026-08-10)

- Avatar service 額外發布於 host loopback `127.0.0.1:8090`，讓直接執行的
  `frontend/` 與 FastAPI backend 可測試既有 GPU Avatar，不必把 backend 打包為
  Docker image。
- 8090 不綁定 LAN 或公網介面；正式瀏覽器仍只透過 gateway 與 backend 的
  `/v1/avatar/*` 路由存取，不直接接觸模型服務。
- 驗證包含 Compose config、Avatar CUDA／checkpoint health、Docker backend 私有
  網路連線、host loopback health，以及從本機 backend 取得有效 MP4 的端到端合成。

### v1.0.0（截至 2026-08-07）

- **2026-08-06 — 安全邊界與雙前端部署基線**
  - 後端整合 RS256 JWT、scope、一次性病患邀請、Secure／HttpOnly session、
    institution／encounter isolation、安全稽核與明確 CORS allowlist；正式環境可
    停用未版本化 API aliases。
  - 建立 `frontend-v2` doctor／patient 分離部署：醫師端位於 `/ai-consult/`，
    由 UCC bootstrap 取得短效記憶體 token；病患端以 fragment invitation token
    交換 HttpOnly session，且不包含醫師 router 或 API client。
  - 新增 Ubuntu Docker Compose／Nginx 唯一入口、私有 FastAPI port、UCC 與病患
    listener／路由隔離、IIS `/ai-api` reverse proxy、doctor CSP 與 PowerShell
    build／安裝腳本。
  - 新增 Ubuntu deploy、SQLite online backup／確認式 restore 與靜態設定驗證；
    文件涵蓋 TLS、憑證、firewall、單 worker、WAL、金鑰權限與驗收程序。
- **2026-08-07 — GPU、ASR、Avatar 與部署前驗證**
  - 部署藍圖納入 Breeze-ASR-26、私有 CosyVoice3 + MuseTalk 1.5 Avatar service，
    以及可切換的 D-ID browser provider；Avatar service 不發布 host port。
  - backend／Avatar image 與 Compose 加入 CUDA 12.8、NVIDIA GPU reservation、
    Hugging Face／模型／影片 volumes，以及各階段模型卸載與 VRAM 釋放設定，供
    單張 16 GB GPU 的循序錄音→辨識→影片流程使用。
  - Nginx 加入 Avatar 長 timeout、固定醫師圖片路徑與 provider-specific CSP；
    local mode 維持 self-only，D-ID mode 僅增加必要 HTTPS／WSS endpoints。
  - Ubuntu deployment script 僅讀取三個 browser build 設定，不 source server
    secrets 或輸出值；部署前驗證新增 CUDA、ASR／Avatar invariants、敏感資料與
    ignore 檢查。
  - loopback auth bypass 仍預設關閉，且只接受直接 TCP peer 為 loopback；正式
    UCC principal 持續強制 tenant isolation。

## Architecture

```text
UCC browser -> IIS /ai-consult/ (doctor static build)
            -> IIS /ai-api/* -> Ubuntu LAN:8443/v1/* -> Nginx -> FastAPI

Patient browser -> https://patient.example/ (patient static build)
                -> /api/v1/* -> Nginx -> FastAPI

Development frontend -> http://127.0.0.1:18000/v1/* -> Nginx -> FastAPI

Operator browser -> http://127.0.0.1:18080 -> Dozzle
                                  -> internal read-only API proxy -> Docker socket

FastAPI -> one Docker-internal port, one worker, SQLite WAL named volume
FastAPI -> private avatar service -> local CosyVoice3 -> local MuseTalk 1.5
```

FastAPI has no published host port. Patient, UCC, and local development traffic all
pass through Nginx. The development listener is published on host loopback only;
it is not reachable from the LAN. The UCC listener is bound to the Ubuntu private address and also
uses an Nginx IP allowlist; apply the same allowlist in `ufw` or the cloud
firewall. The two Nginx listeners may use one certificate only if its SAN covers
both the public patient name and the private UCC API DNS name.

The public patient listener returns 404 for `/api/v1/doctor/*` and for the UCC
invitation-creation endpoint. FastAPI JWT/scope enforcement remains the final
authorization boundary; the Nginx blocks are defense in depth.

Nginx joins a dedicated edge bridge for host-published ports and the private API
bridge for upstream access. The backend and avatar service join private networks. The
backend uses it for the configured LLM/FHIR providers; the avatar service uses
it to download model weights during setup. FastAPI is not published directly;
Avatar and the development Nginx API are available only on host loopback. Avatar
inference is local after the weights are cached in the
`avatar-models` Docker volume. Restrict outbound DNS/IPs at the host firewall
when provider endpoints are fixed.

## 1. Ubuntu preparation and deployment

Requirements: Docker Engine with Compose v2, Node.js 18+, DNS, and a valid TLS
certificate. Clone the repository to a restricted service directory, then:

```sh
cd integration-deployment
cp .env.example .env
chmod 600 .env
# Edit .env; do not leave example.invalid, replace-me, or 0.0.0.0 for UCC_API_BIND_IP.
install -m 600 /secure/source/ucc-jwt-public.pem secrets/ucc-jwt-public.pem
install -m 600 /secure/source/fullchain.pem secrets/tls-fullchain.pem
install -m 600 /secure/source/private-key.pem secrets/tls-private-key.pem
chmod +x scripts/*.sh
./scripts/deploy-ubuntu.sh
```

Open TCP 443 to intended patients. Open TCP 8443 only from the UCC IIS address:

```sh
sudo ufw allow 443/tcp
sudo ufw allow from 10.20.30.10 to 10.20.30.40 port 8443 proto tcp
sudo ufw deny 8443/tcp
```

Replace the example addresses with actual fixed addresses. In a formal deployment,
keep `ALLOW_LOCAL_AUTH_BYPASS=false`. Port 18000 may appear in `docker compose ps`,
but its host binding must be exactly `127.0.0.1`, never `0.0.0.0` or a LAN address.
Validate:

```sh
curl --fail https://patient.example/healthz
curl --fail https://ai-api.internal.example:8443/v1/health   # from IIS host only
docker compose ps
```

### Development frontend with the containerized backend

For the development `frontend/`, keep Vite on the host and run every backend service
through Compose. In the local, uncommitted `integration-deployment/.env`, use:

```dotenv
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
DEVELOPMENT_API_PORT=18000
ALLOW_LOCAL_AUTH_BYPASS=true
# 若主機 443 已被其他服務使用，可在本機改用：
PATIENT_HTTPS_PORT=10443
```

Start or refresh the complete backend pipeline, then start Vite:

```sh
cd integration-deployment
docker compose up -d --build

cd ../frontend
npm run dev
```

The existing frontend default resolves its API to the page hostname on port 18000,
so `http://localhost:5173` talks to `http://localhost:18000`, which is the loopback
Nginx listener backed by Docker FastAPI. After a backend source change, rebuild only
that service; Docker will recreate it while preserving named volumes:

```sh
cd integration-deployment
docker compose up -d --build backend
```

Frontend source changes still use Vite hot reload. `backend/.env` does not configure
the Docker backend; `integration-deployment/.env` is authoritative. The Docker
`consultation-data` volume is also separate from `backend/data/consultations.db`;
moving old cases requires an explicit backup/import and is never automatic.

### Local container status and live logs

The Compose stack includes [Dozzle](https://dozzle.dev/) for lightweight container
status, health, resource metrics, and live-log viewing. Start it with the rest of the
stack or independently:

```sh
cd integration-deployment
docker compose up -d monitor
docker compose ps monitor docker-api-proxy
```

On the Docker host, open `http://127.0.0.1:18080`. To view it from an administrator
workstation, keep the server port on loopback and create an SSH tunnel:

```sh
ssh -N -L 18080:127.0.0.1:18080 deploy-user@ubuntu-host
```

Then open `http://127.0.0.1:18080` on the workstation. If that local port is occupied,
change `CONTAINER_MONITOR_PORT` in the uncommitted deployment `.env` and use the same
local port in the tunnel.

Dozzle uses a Compose-project display filter and does not persist a separate copy of
container logs; it streams what the Docker daemon retains. The filter is a UI
convenience, not an authorization boundary. The named `monitor-data` volume stores UI
preferences.

Dozzle does not mount `docker.sock` directly. A pinned
[Docker Socket Proxy](https://github.com/Tecnativa/docker-socket-proxy) exposes only
the read-only Docker API sections required for container status and logs over an
internal network; it has no host port. Those APIs can still reveal sensitive
container metadata, and logs may contain operational or clinical details. Do not
expose this service through the patient/UCC gateway or bind it to a LAN/public
interface. Keep actions, shell, and MCP disabled. See the upstream
[Dozzle security guidance](https://dozzle.dev/guide/authentication) before adding any
remote access method other than SSH tunneling.

### Breeze ASR GPU

The backend image uses the CUDA 12.8 PyTorch wheel and Compose reserves one
NVIDIA GPU. On the Ubuntu host, install NVIDIA Container Toolkit before the
first deployment, then configure Docker and restart the daemon. Restarting
Docker can interrupt running containers, so schedule this step accordingly:

```sh
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu22.04 nvidia-smi
```

Set `ASR_PROVIDER=breeze` and `BREEZE_ASR_DEVICE=cuda` in `.env`. After the
Avatar warm-up, `GET /v1/health` should report
`speech_transcription.loaded: true` when
`BREEZE_ASR_RELEASE_GPU_AFTER_TRANSCRIBE=false`; the CUDA pipeline stays ready
for following recordings. The mounted
`HF_MODEL_CACHE_PATH` is writable because Breeze-ASR-26 downloads roughly 6 GB
of model files on first use. The 16 GB RTX 5060 Ti profile is verified for
resident models; other GPUs must be measured and may need the release option.

The gateway logs method and path only: query strings, Referer headers, request
bodies, invitation tokens, and clinical content are deliberately omitted.
Uvicorn access logging is disabled; security events remain in the application
audit table. Central log collectors must apply the same PII/token redaction.

### Local CosyVoice3 + MuseTalk Avatar

Set `AVATAR_PROVIDER=local` to use `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` for
speech and MuseTalk 1.5 for lip sync, based on `pic/dr training pc.png`.
Pre-download the checkpoints before accepting patient traffic:

```sh
docker compose build avatar
docker compose run --rm avatar python3.10 -m app.download_models
docker compose up -d avatar
docker compose ps avatar
docker compose exec avatar python3.10 -c \
  "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8090/health')))"
```

The health output must show `status: ok`, `device: cuda:0`, and
`models_downloaded: true`. Enabling Avatar calls `/v1/avatar/warmup`; with
`AVATAR_RELEASE_GPU_AFTER_RENDER=false`, health then keeps `speech_loaded` and
`animation_loaded` true across renders. Generated MP4 files are capped by count
and stored in `avatar-cache`; do not treat that volume as a clinical record.

Set `AVATAR_ANIMATION_ENABLED=false` when lip animation is not required. For the
normal frontend → backend path, this is the backend default; a render request can
override it without rebuilding the Avatar image or container. The same Compose
value is also passed to the Avatar service as the fallback for direct callers or
requests that omit an override. Static mode skips MuseTalk inference and returns
a video made from the static doctor image plus local CosyVoice speech. The patient
frontend continues to display the spoken text as subtitles; this setting changes
only animation work, not the text, speech provider, authentication boundary, or
consultation behavior. The default is `true` for backward compatibility.

Resident models reduce single-user sequential flow latency, but do not serialize
simultaneous ASR and Avatar requests from different users. On a multi-user
installation, measure peak memory, lower `MUSETALK_BATCH_SIZE`, enable both
release flags, enforce admission control, or dedicate separate GPUs.

The Avatar container also binds its API to host loopback only, so the development
`frontend/` and a backend started directly from `backend/` can use the same GPU
service without containerizing FastAPI. Keep these values in the local, uncommitted
`backend/.env`:

```dotenv
AVATAR_ENABLED=true
AVATAR_SERVICE_URL=http://127.0.0.1:8090
AVATAR_TIMEOUT_SECONDS=600
```

Start only the GPU service when the rest of the development stack runs on the host:

```sh
cd integration-deployment
docker compose up -d avatar
curl --fail http://127.0.0.1:8090/health
```

The Compose mapping is deliberately fixed to `127.0.0.1`; do not change it to
`0.0.0.0`, because browsers must continue to reach Avatar through the authenticated
backend API rather than the unauthenticated model endpoint.

The bundled CosyVoice sample is only a bootstrap voice. Before clinical use,
mount a short consented reference recording as described in
[`../avatar-service/README.md`](../avatar-service/README.md). Obtain explicit
permission for both the source portrait and voice, and label the experience as
AI-generated.

### D-ID Avatar provider

Set `AVATAR_PROVIDER=did` and provide `DID_CLIENT_KEY` plus `DID_AGENT_ID` in
`integration-deployment/.env` to retain the D-ID browser client. The Ubuntu
deployment script reads only these three settings and injects them into the
patient Vite build as `VITE_*` values; it never prints their values or sources
the server credential file. Re-run the deployment script whenever the provider
or D-ID settings change because they are compiled into the static patient
bundle.

All Vite environment values are public to anyone who can load or inspect the
patient JavaScript. `DID_CLIENT_KEY` must therefore be a credential explicitly
intended by D-ID for browser/client distribution. Do not place a reusable D-ID
API secret here; supporting a server secret requires a backend proxy instead.
The gateway serves a prebuilt bind-mounted `frontend-v2` dist, so these values
are intentionally not passed as Docker Compose build arguments.

The patient Content Security Policy is provider-specific. Local mode keeps both
`connect-src` and `script-src` restricted to `'self'`. The deployment script
adds only `https://*.d-id.com` and `wss://*.d-id.com` to `connect-src` for D-ID;
the SDK is bundled locally, so no third-party script origin is allowed. A manual
`docker compose up` defaults to the strict local policy. Use the deployment
script for a D-ID release so the validated provider and CSP cannot drift apart.

## 2. UCC doctor frontend

On the development/build Windows host, build and copy to an eHIS *project*:

```powershell
.\integration-deployment\scripts\deploy-doctor.ps1 `
  -EhisProjectRoot 'D:\ehis\eHIS'
```

The script builds with `VITE_BACKEND_BASE_URL=/ai-api`, updates the eHIS iframe
`assetVersion` from the generated Vite entry hash, backs up an existing
`wwwroot\ai-consult` and the changed `AiConsult/Index.cshtml`, then installs the
build plus the static CSP and no-cache policy. It also invokes the idempotent B01
registration-invitation installer, which backs up and patches the required eHIS
controller, encounter service, model, view, and registration success hook before
copying the local QR browser asset. Unknown source anchors fail closed before any
source file is written. Rebuild and publish eHIS after these updates; the script
itself does not publish or restart eHIS. The iframe URL remains:

```text
/ai-consult/index.html?regSno=<current-registration>#/doctor
```

Install IIS Application Request Routing and URL Rewrite, enable ARR proxying,
then merge `iis/ai-api-rewrite.rules.xml` before the ASP.NET Core catch-all rule.
Replace the internal hostname and require a certificate trusted by Windows.
Authorization headers must be preserved. Test `/ai-api/v1/health` from IIS,
then test an authenticated doctor endpoint; never disable TLS validation.

Configure the deployed eHIS environment without placing the private key in a
JSON file. The audience and issuer must exactly match Ubuntu `.env`:

```json
{
  "AiConsult": {
    "BackendBaseUrl": "https://ai-api.internal.example:8443/",
    "JwtIssuer": "ucc-ehis",
    "JwtAudience": "medical-consultation-api",
    "JwtTtlMinutes": 5,
    "CertificateThumbprint": "THUMBPRINT_WITHOUT_SPACES",
    "CertificateStoreName": "My",
    "CertificateStoreLocation": "LocalMachine"
  }
}
```

For an existing deployed eHIS configuration, update only the private backend URL
with the guarded helper (it creates a timestamped backup and never prints other
configuration values):

```powershell
.\integration-deployment\scripts\set-ehis-ai-backend-url.ps1 `
  -ConfigPath 'C:\Deploy\eHIS\appsettings.Local.json' `
  -BackendBaseUrl 'https://ai-api.internal.example:8443/'
```

The B01 QR flow uses a separate authorization path from the doctor dashboard.
Only the signed-in B01 user who created the same-day registration may issue its
invitation, including `NotCheckIn` state 5. The existing doctor invitation still
requires the assigned/substitute doctor and current state 0 or 1. Neither path
places patient prefill data in the DOM or logs; the displayed QR contains the
one-time patient invitation URL and must not be forwarded.

After publishing eHIS to a separate staging directory and completing the normal
change-window checks, an administrator may deploy only the B01 integration files
with a backup-first, hash-verified app-pool switch:

```powershell
dotnet publish D:\ehis\eHIS\eHIS.csproj -c Release --no-restore `
  -o "$env:TEMP\ehis-registration-qr"

.\integration-deployment\scripts\deploy-local-ehis-registration.ps1 `
  -StagingRoot "$env:TEMP\ehis-registration-qr" `
  -DeployRoot 'C:\Deploy\eHIS' `
  -AppPoolName 'eHIS-Pool'
```

The script validates both roots and all three staged files before stopping IIS,
backs up existing targets, rolls back copied files on failure, and restarts the
application pool in `finally`. This interrupts active eHIS requests; run it only
during an explicitly approved maintenance window and do not treat it as a substitute
for the organization's release procedure.

The IIS application-pool identity needs read permission on that certificate's
private key. Export only its SubjectPublicKeyInfo as `ucc-jwt-public.pem` for
Ubuntu. Confirm the exported public key validates a token before enabling the
invitation flow. `DevelopmentPrivateKeyPem` is for local testing only and must
not be present in deployed configuration.

Keep `UCC_JWT_CLOCK_SKEW_SECONDS=30` in Ubuntu `.env` unless infrastructure has a
stricter measured requirement. Accepted values are 0–300 seconds; this tolerance
is only for JWT time claims and is not a substitute for NTP synchronization.

If an eHIS site-level CSP already exists, merge rather than duplicate policies.
It must allow same-origin `frame-src 'self'` and the doctor iframe response must
retain `frame-ancestors 'self'`.

## 3. Updating

Before each update, create separate recovery points for persistent consultation
data and the currently running application images. Image tags protect the previous
program version from being replaced by the next `:local` build; they do not back up
SQLite or bind-mounted configuration.

```sh
cd integration-deployment
./scripts/backup-sqlite.sh

# Replace this example with a unique UTC date/time for the maintenance window.
SNAPSHOT_TAG=20260817T120000Z
docker image tag medical-consultation-backend:local \
  medical-consultation-backend:backup-$SNAPSHOT_TAG
docker image tag medical-consultation-avatar:local \
  medical-consultation-avatar:backup-$SNAPSHOT_TAG

docker image ls medical-consultation-backend
docker image ls medical-consultation-avatar
```

Keep the Git revision used for the snapshot in the maintenance record. Then update
the source and rebuild the complete Compose application. Docker may reuse unchanged
layers; use `docker compose build --no-cache` only when a cache-independent rebuild
is specifically required.

```sh
git pull --ff-only
docker compose config --quiet
docker compose up -d --build --remove-orphans
docker compose ps
docker compose logs --tail=100 backend
curl --fail http://127.0.0.1:18000/v1/health
```

For the full production workflow, including the patient frontend build and deployment
preflight checks, continue to use `./scripts/deploy-ubuntu.sh` instead of the direct
Compose command above.

If the new containers fail acceptance, point the Compose image names back to the
snapshot and recreate without building from the current source tree:

```sh
SNAPSHOT_TAG=20260817T120000Z
docker image tag medical-consultation-backend:backup-$SNAPSHOT_TAG \
  medical-consultation-backend:local
docker image tag medical-consultation-avatar:backup-$SNAPSHOT_TAG \
  medical-consultation-avatar:local

docker compose up -d --no-build --force-recreate
docker compose ps
docker compose logs --tail=100 backend
curl --fail http://127.0.0.1:18000/v1/health
```

An image rollback normally keeps the current SQLite data. Restore the matching
SQLite backup only if the failed release changed data in a way the previous backend
cannot safely read. Use the confirmed restore procedure in the next section during
an approved maintenance window.

For an off-host or cleanup-resistant image snapshot, export the tagged images to
protected storage. The Avatar image may be large; omit it when only Backend changed.

```sh
docker image save \
  -o backups/docker-images-$SNAPSHOT_TAG.tar \
  medical-consultation-backend:backup-$SNAPSHOT_TAG \
  medical-consultation-avatar:backup-$SNAPSHOT_TAG

# Recover exported tags when the local Docker image cache no longer has them.
docker image load -i backups/docker-images-$SNAPSHOT_TAG.tar
```

Never use `docker compose down -v` for an update or rollback. The `-v` option removes
named volumes, including consultation data, model/cache data, and monitor settings.

On Windows, run `deploy-doctor.ps1` against the development eHIS project, build
and test eHIS, then use the organization's normal publish/change window. Do not
copy directly over `C:\Deploy\eHIS` while IIS is serving requests.

## 4. Backup and restore

`backup-sqlite.sh` uses SQLite's online backup API, which is consistent with WAL
and does not copy a live `.db` file blindly. Send encrypted copies off-host daily
and apply retention according to clinical governance policy.

Restore requires an explicit confirmation flag, creates a fresh pre-restore
backup, stops the single backend, restores, and restarts it:

```sh
./scripts/restore-sqlite.sh consultations-YYYYMMDDTHHMMSSZ.sqlite3 --confirm-restore
curl --fail https://patient.example/healthz
```

Run restore only in an approved maintenance window. Validate consultation and
invitation counts through authorized application workflows after recovery.

## 5. Security and acceptance checklist

- Keep the UCC signing private key only in Windows Certificate Store; Ubuntu has
  the public key only. Rotate by an approved overlapping-key procedure.
- `.env`, TLS material, database backups, and model credentials must be readable
  only by the service administrator and encrypted at rest.
- Keep `ENABLE_UNVERSIONED_ALIASES=false`, CORS empty, cookies Secure/HttpOnly,
  and one Uvicorn worker while SQLite is used.
- TLS, CSP, HSTS, request-size limit (12 MiB), AI timeout (180 seconds), and
  UCC source allowlisting are enforced by Nginx.
- Use only test or de-identified data for this acceptance deployment. There is
  no write-back to the production medical record.
- Run `powershell -File scripts/validate-config.ps1` after editing deployment
  files and `docker compose config --quiet` before each release.
