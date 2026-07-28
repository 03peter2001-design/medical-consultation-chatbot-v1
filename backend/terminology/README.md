# Local FHIR terminology reference

The checked-in archive is the official `tw.gov.mohw.twcore#1.0.0`
FHIR R4 package published by Taiwan's Ministry of Health and Welfare.

- Registry source: `https://packages.fhir.org/tw.gov.mohw.twcore/1.0.0`
- Canonical: `https://twcore.mohw.gov.tw/ig/twcore`
- Downloaded: 2026-07-28
- SHA-256:
  `a9ea37f16ea163b2c584ce7d423a5095587a1c027d0d4e4a5cdb0e7445e4932d`

The extracted JSON files are unmodified resources from that package and are
the subset used by the application to identify the official SNOMED CT and
LOINC system URIs and applicable TW Core profiles.

This repository does **not** create a free-text-to-code lookup table.
Incoming codes are retained only when they already exist in a FHIR `Coding`.
Full SNOMED CT terminology lookup requires a licensed release or terminology
server; TW Core references SNOMED CT but does not redistribute the complete
SNOMED CT concept release.
