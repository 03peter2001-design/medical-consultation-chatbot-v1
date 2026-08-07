# UCC doctor + external patient deployment

This directory contains a deployment blueprint only. Nothing here overwrites
`C:\Deploy\eHIS`, starts IIS, or starts Ubuntu services until an administrator
explicitly runs the scripts.

## Architecture

```text
UCC browser -> IIS /ai-consult/ (doctor static build)
            -> IIS /ai-api/* -> Ubuntu LAN:8443/v1/* -> Nginx -> FastAPI

Patient browser -> https://patient.example/ (patient static build)
                -> /api/v1/* -> Nginx -> FastAPI

FastAPI -> one Docker-internal port, one worker, SQLite WAL named volume
FastAPI -> private avatar service -> local CosyVoice3 -> local MuseTalk 1.5
```

FastAPI has no published host port. Patient traffic and UCC traffic both pass
through Nginx. The UCC listener is bound to the Ubuntu private address and also
uses an Nginx IP allowlist; apply the same allowlist in `ufw` or the cloud
firewall. The two Nginx listeners may use one certificate only if its SAN covers
both the public patient name and the private UCC API DNS name.

The public patient listener returns 404 for `/api/v1/doctor/*` and for the UCC
invitation-creation endpoint. FastAPI JWT/scope enforcement remains the final
authorization boundary; the Nginx blocks are defense in depth.

The backend and avatar service join a separate, unpublished Docker bridge. The
backend uses it for the configured LLM/FHIR providers; the avatar service uses
it to download model weights during setup. Neither service publishes a host
port. Avatar inference is local after the weights are cached in the
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

Replace the example addresses with actual fixed addresses. Confirm that port
8000 is not published by `docker compose ps`. Validate:

```sh
curl --fail https://patient.example/healthz
curl --fail https://ai-api.internal.example:8443/v1/health   # from IIS host only
docker compose ps
```

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
first transcription, `GET /v1/health` should report
`speech_transcription.loaded` as `false` again when
`BREEZE_ASR_RELEASE_GPU_AFTER_TRANSCRIBE=true`; this is expected because the
CUDA pipeline is unloaded before the following chat/avatar request. During
inference it temporarily reports `device: cuda:0`. The mounted
`HF_MODEL_CACHE_PATH` is writable because Breeze-ASR-26 downloads roughly 6 GB
of model files on first use. Disabling the release option reduces subsequent
ASR latency but is unsafe when Avatar shares a 16 GB GPU.

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
`models_downloaded: true`. This deployment enables
`AVATAR_RELEASE_GPU_AFTER_RENDER=true`: after CosyVoice has written the WAV it
is unloaded before MuseTalk starts, and all remaining Avatar models are
unloaded after the MP4 completes. This returns VRAM to the lazy-loaded Breeze
ASR, but every uncached sentence pays model reload latency. A cached sentence
serves its existing MP4 without loading either model. While an uncached render
is active, health may temporarily show `speech_loaded` or `animation_loaded` as
`true`; both return to `false` afterward. Generated MP4 files are capped by
count and stored in `avatar-cache`; do not treat that volume as a clinical
record.

The paired Breeze and Avatar release settings prevent the normal sequential
flow (recording → transcription → response video) from leaving either model
resident when the other starts. They do not serialize truly simultaneous ASR
and Avatar requests from different users; on a multi-user installation, lower
`MUSETALK_BATCH_SIZE` and enforce admission control or dedicate separate GPUs
after measuring concurrent peak memory.

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

The script builds with `VITE_BACKEND_BASE_URL=/ai-api`, backs up an existing
`wwwroot\ai-consult`, then installs the build plus the static CSP. It does not
publish or restart eHIS. The iframe URL remains:

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

The IIS application-pool identity needs read permission on that certificate's
private key. Export only its SubjectPublicKeyInfo as `ucc-jwt-public.pem` for
Ubuntu. Confirm the exported public key validates a token before enabling the
invitation flow. `DevelopmentPrivateKeyPem` is for local testing only and must
not be present in deployed configuration.

If an eHIS site-level CSP already exists, merge rather than duplicate policies.
It must allow same-origin `frame-src 'self'` and the doctor iframe response must
retain `frame-ancestors 'self'`.

## 3. Updating

Before each update, back up SQLite and keep the previous container image and
doctor static backup:

```sh
cd integration-deployment
./scripts/backup-sqlite.sh
git pull --ff-only
./scripts/deploy-ubuntu.sh
docker compose ps
```

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
