# Local SMART on FHIR demo

This directory contains the two-page browser launch flow used by the local
SMART Launcher:

- `launch.html`: provider EHR launch entry point
- `launch-patient.html`: standalone patient launch entry point
- `index.html`: OAuth redirect page and authenticated FHIR reader

The SMART stack reuses the existing HAPI FHIR R4 server at
`http://127.0.0.1:8080/fhir`. Start the SMART Launcher, internal FHIR path
proxy, and demo app from the repository root:

```bash
./scripts/start-smart.sh
```

After importing the synthetic FHIR bundles, open
`http://127.0.0.1:5174/start.html` and select a patient. The page creates an R4
Provider EHR Launch through `http://127.0.0.1:8090`.

To configure the Launcher manually, open `http://127.0.0.1:8090` and use
`http://127.0.0.1:5174/launch.html` as the launch URL.

This is a development sandbox. It is not configured for production use or
real patient data.

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
