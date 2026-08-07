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
```

FastAPI has no published host port. Patient traffic and UCC traffic both pass
through Nginx. The UCC listener is bound to the Ubuntu private address and also
uses an Nginx IP allowlist; apply the same allowlist in `ufw` or the cloud
firewall. The two Nginx listeners may use one certificate only if its SAN covers
both the public patient name and the private UCC API DNS name.

The public patient listener returns 404 for `/api/v1/doctor/*` and for the UCC
invitation-creation endpoint. FastAPI JWT/scope enforcement remains the final
authorization boundary; the Nginx blocks are defense in depth.

The backend alone joins a separate outbound-only Docker bridge so it can reach
the configured LLM/FHIR providers. No host port is published on that network.
Restrict outbound DNS/IPs at the host firewall when provider endpoints are fixed.

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

The gateway logs method and path only: query strings, Referer headers, request
bodies, invitation tokens, and clinical content are deliberately omitted.
Uvicorn access logging is disabled; security events remain in the application
audit table. Central log collectors must apply the same PII/token redaction.

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
