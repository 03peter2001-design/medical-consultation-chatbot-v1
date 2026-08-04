# SMART on FHIR integrated application

This directory contains the launch pages and container configuration for the
full Vue consultation application:

- `launch.html`: provider EHR launch entry point
- `launch-patient.html`: standalone patient launch entry point
- `start.html`: local synthetic-patient launcher
- `nginx.conf`: serves the Vue build and proxies `/api` to FastAPI
- `../smart-deployment/smart-launcher-gateway.conf`: normalizes local SMART
  Launcher CORS by preserving the requesting localhost/127.0.0.1 port

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

`backend/.env` must exist before the stack starts. After importing the
synthetic FHIR bundles, open `http://127.0.0.1:5174/start.html` and select a
patient. The page creates an R4 Provider EHR Launch through
`http://127.0.0.1:8090`; successful authorization opens the real patient
consultation UI.

To configure the Launcher manually, open `http://127.0.0.1:8090` and use
`http://127.0.0.1:5174/launch.html` as the launch URL.

This is a development sandbox. It is not configured for production use or
real patient data. Production deployment still requires client registration,
TLS, trusted redirect URIs, user authorization, least-privilege scopes, audit
logging, backend authentication, and an approved clinician-confirmed FHIR
write-back workflow.

The API image installs `backend/requirements-runtime.txt` plus the reviewed
CPU-only RAG dependencies, and mounts the host `backend/chroma_db` and cached
embedding model read-only. Run `./scripts/bootstrap.sh --with-rag` before the
first SMART startup. `start-smart.sh` verifies the index, model cache, and
backend `/api/v1/health` `rag_enabled` response before reporting the stack ready. RAG
supports clinician research features and background reporting; the
deterministic patient interview does not use RAG for Safety or disease votes.

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
