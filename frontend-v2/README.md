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
