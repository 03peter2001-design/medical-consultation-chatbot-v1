# Frontend V2

This workspace produces two deliberately isolated Vue applications from the
same clinical component library.

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
