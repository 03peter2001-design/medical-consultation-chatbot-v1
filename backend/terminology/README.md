# Vendored TW Core FHIR packages

This directory contains the complete FHIR NPM package dependency closure used
to install `tw.gov.mohw.twcore#1.0.0` into HAPI FHIR R4. A fresh clone does not
need a separate HAPI Starter checkout or a live FHIR package registry during
package installation.

## Reproducibility

`packages.lock.json` is the source of truth. It records installation order,
package name, exact version, manifest license value, relative archive path and
SHA-256 for every archive. `python -m scripts.install_twcore` checks every
manifest and hash before contacting HAPI.

The package set contains:

| Package | Version | Why it is included |
| --- | --- | --- |
| `hl7.fhir.r4.core` | 4.0.1 | FHIR R4 base definitions |
| `hl7.fhir.r4.examples` | 4.0.1 | SDC dependency |
| `hl7.fhir.uv.extensions.r4` | 5.2.0 | TW Core and terminology extensions |
| `hl7.terminology.r4` | 5.0.0 | IPS-pinned terminology dependency |
| `fhir.dicom` | 2022.4.20221006 | IPS transitive dependency |
| `hl7.fhir.uv.ips` | 1.1.0 | TW Core direct dependency |
| `hl7.fhir.uv.sdc` | 3.0.0 | TW Core direct dependency |
| `hl7.terminology.r4` | 7.0.0 | TW Core direct terminology dependency |
| `tw.gov.mohw.twcore` | 1.0.0 | Taiwan Core Implementation Guide |

Both terminology versions are intentional: IPS 1.1.0 pins 5.0.0 while TW Core
1.0.0 pins 7.0.0. HAPI stores FHIR packages by package name and version.

The TW Core archive was downloaded from
`https://packages.fhir.org/tw.gov.mohw.twcore/1.0.0`; the dependency archives
under `packages/` use the equivalent registry URL formed from each locked name
and version. The archive manifests label the HL7 and TW Core packages
`CC0-1.0`; the DICOM package manifest labels itself `free`.

## Install

The root Compose workflow starts HAPI, waits for it to become healthy and
installs the complete locked set:

```bash
docker compose -f compose.fhir.yml --profile setup up -d
docker compose -f compose.fhir.yml logs twcore-installer
```

The `setup` profile prevents an ordinary later `docker compose up -d` from
reinstalling the same large package set. The installer also writes the lock
SHA-256 to `Basic/twcore-package-set` in HAPI. A later installer run skips the
upload when that database marker still matches `packages.lock.json`; use
`--force` to reinstall intentionally.

For an already-running HAPI server:

```bash
cd backend
python -m scripts.install_twcore
```

Set `FHIR_BASE_URL` or pass `--server` when HAPI is not available at
`http://127.0.0.1:8080/fhir`. To verify local files without contacting HAPI:

```bash
cd backend
python -m scripts.install_twcore --verify-only
```

The extracted `twcore-1.0.0/` files are an unmodified application-facing subset
used to identify official system URIs and relevant profiles. The complete
archive is the file installed into HAPI.

## Scope

These archives reproduce the TW Core profiles, extensions, ValueSets,
CodeSystems and package dependencies. They do **not** contain the full LOINC or
SNOMED CT releases. TW Core references those external systems but does not
redistribute their complete terminology content. Full SNOMED CT validation
still requires a licensed release or terminology service, and full LOINC
validation requires a separately obtained LOINC release.
