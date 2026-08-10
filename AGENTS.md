# AGENTS.md

This file defines the repository-wide working agreement for agents operating in this
project. More specific instructions may be added in a nested `AGENTS.md`; the closest
applicable file takes precedence. Keep component-specific details near the component
and do not duplicate these repository-wide rules.

## 1. Project Context

This repository contains a medical pre-consultation system with several related
surfaces:

- `backend/`: FastAPI APIs, AMIE interview logic, safety and disease rules, RAG,
  persistence, questionnaires, FHIR integration, and tests.
- `frontend/`: the development version of the Vue 3 patient and doctor application;
  this is the default frontend target for ordinary development work.
- `frontend-v2/`: the real deployment version, with split doctor and patient
  applications plus shared Vue code; treat it as a separately controlled production
  release line.
- `avatar-service/`: local speech and avatar generation service.
- `integration-deployment/`, `smart-app/`, and `smart-deployment/`: deployment,
  reverse proxy, SMART on FHIR, and institutional integration assets.
- `docs/`: API contracts, research material, and project planning.
- `devlog/`: dated development records.

Read the root README and the nearest component README before changing an unfamiliar
area. Preserve the current architecture unless the task explicitly calls for a
migration or redesign.

## 2. Operating Model

- Keep the main thread responsible for requirements, decisions, implementation
  integration, verification, and final acceptance.
- For any non-trivial task containing two or more independently verifiable,
  non-overlapping work units, use sub-agents by default. If the main thread does not
  delegate such a task, briefly state why delegation would not be safe or useful.
- Simple, indivisible, tightly coupled, sequentially dependent, or overlapping work
  is exempt from the default delegation requirement.
- Do not delegate trivial, indivisible, or tightly coupled work solely to create more
  threads.
- Never allow concurrent write-capable agents to edit the same files or overlapping
  modules. Assign explicit file or module ownership when parallel writes are used.
- A subtask must not silently expand its scope. Return architecture, compatibility,
  security, or product decisions to the main thread.
- The main thread must review and verify all integrated results; a sub-agent report is
  evidence, not automatic acceptance.

## 3. Before Making Changes

- Inspect applicable instructions, repository structure, relevant documentation,
  current Git status, and the files needed for the task.
- Assume existing modified and untracked files belong to the user or another active
  workstream. Preserve them and avoid unrelated cleanup or formatting.
- If required work overlaps unrelated modifications and cannot be separated safely,
  stop and ask the user how to proceed.
- For non-trivial work, state a short plan with explicit completion criteria before
  implementation.
- Resolve ambiguities that could materially change clinical behavior, security,
  privacy, architecture, data, API contracts, deployment, or compatibility.
- Prefer the smallest coherent change that satisfies the requirement. Do not perform
  opportunistic refactors outside the requested scope.

## 4. Git, Commits, and Development Records

- Do not commit, amend, squash, rebase, push, or open a pull request unless the user
  explicitly requests it.
- When a commit is requested, review the diff and verification results first. Stage
  and commit only files belonging to the requested change.
- Never absorb, discard, or rewrite unrelated user changes.
- Use an imperative, focused commit subject that describes the delivered outcome.
- Do not describe failing or partially verified work as complete.
- Important delivered features, architecture changes, deployment changes, clinical
  behavior changes, and multi-phase efforts should update the existing
  `devlog/YYYY-MM-DD.md` record.
- Small fixes, investigations, reviews, and documentation-only corrections do not
  require a devlog entry unless the user asks for one.
- Do not create a separate root `DEVLOG.md`. Do not paste raw terminal logs into the
  devlog; summarize results, decisions, and remaining limitations.

## 5. Service Versioning

- Every delivered update must increment the documented SemVer of each service it
  changes. An update includes behavior, code, configuration, dependencies, build or
  deployment behavior, tests, and service-specific documentation. Pure
  investigation or review with no repository change does not increment a version.
- Treat one coherent delivered batch as one version increment per affected service,
  using the highest applicable SemVer level:
  - **MAJOR** for an approved breaking change to a public API, required configuration,
    authentication boundary, persisted data contract, deployment contract, or other
    consumer-facing compatibility boundary.
  - **MINOR** for a backward-compatible feature or material behavior/capability
    addition.
  - **PATCH** for a backward-compatible bug fix, refactor, test-only change,
    dependency maintenance, or documentation-only correction.
- The canonical service release record is the version section in the service's
  nearest README. On every version increment:
  1. add a new version entry above older entries using the heading format
     `vMAJOR.MINOR.PATCH (YYYY-MM-DD)`;
  2. describe the delivered changes in enough detail to identify behavior,
     compatibility, security/clinical implications, migrations, and verification;
  3. preserve older version entries instead of rewriting their history; and
  4. update the current-version row, date, summary, and link in the root `README.md`.
- Documentation version records are the required version system for this repository.
  Do not add or modify runtime version endpoints, package metadata, image tags, or
  build-time version injection merely to mirror the README unless the user explicitly
  requests runtime/release automation.
- Map changed paths to independently versioned services as follows:
  - `backend/` changes increment the Backend API version, except a change confined to
    external terminology artifacts or their documentation, which updates the
    terminology component matrix instead. Backend terminology behavior changes still
    increment Backend API.
  - `frontend/` changes increment the development Vue frontend version.
  - `frontend-v2/apps/doctor/` changes increment Doctor frontend; changes under
    `frontend-v2/apps/patient/` increment Patient frontend.
  - `frontend-v2/packages/shared/` changes increment every doctor/patient app whose
    delivered behavior or bundle is affected. Do not assume both when the change is
    provably app-specific.
  - `avatar-service/` changes increment Local Avatar service.
  - `smart-app/`, `smart-deployment/`, `compose.smart.yml`, and SMART-specific startup
    behavior increment SMART on FHIR sandbox app. `smart-deployment/` follows the
    SMART app version and is not an independent service.
  - `integration-deployment/` changes increment Integration deployment bundle.
- For repository-wide files or cross-service generated artifacts, increment only the
  services whose delivered behavior, contract, build, test coverage, or documentation
  is materially changed. A root governance/documentation change that affects no
  service does not force all service versions to increment.
- A version-record edit required by the same version increment does not recursively
  trigger another increment. Do not increment versions for unrelated pre-existing
  user changes, generated output alone, or a devlog entry that only records an already
  versioned delivery.
- Keep service SemVer separate from API prefixes such as `/v1`, SQLite
  `user_version`, RAG index generations, Safety/ClinicalFact/disease-profile
  revisions, questionnaire schemas, model versions, FHIR implementation guides, and
  terminology releases. Update those provenance or compatibility versions as their
  own rules require; a service bump never implies clinical approval.
- Before final handoff, compare all task-owned changed paths with the mapping above
  and verify that every affected service README and the root version table agree. A
  missing required version increment means the task is not complete.

## 6. Frontend and Generated-File Coordination

- `frontend/` is the development version. Unless the user says otherwise, implement
  frontend feature work, experiments, UI changes, and behavior changes there only.
- `frontend-v2/` is the real deployment version and is not an automatic mirror of
  `frontend/`. Do not copy, port, synchronize, merge, regenerate, or otherwise apply
  changes from `frontend/` to `frontend-v2/` unless the user explicitly requests that
  the deployment version be updated.
- A request that mentions only "frontend" means `frontend/`, not both versions. A
  request must explicitly mention `frontend-v2`, the deployment version, production
  deployment, or equivalent wording before files under `frontend-v2/` may be changed.
- When a backend, API, schema, or shared data change could affect `frontend-v2/`,
  preserve backward compatibility with the deployed version where practical. Report
  the potential deployment impact, but do not modify `frontend-v2/` without explicit
  user direction.
- Existing duplicated behavior between the two versions is not, by itself,
  authorization to synchronize them. Do not treat drift as a defect unless the user
  asks for parity or deployment promotion.
- Keep app-specific routing, bootstrap, authentication, and UI behavior in the
  appropriate `frontend-v2/apps/patient/` or `frontend-v2/apps/doctor/` application.
- When the user explicitly requests a `frontend-v2/` update, verify that version
  independently and avoid blind copying because imports, application context,
  authentication, and security boundaries may differ.
- Treat exported questionnaire route files as derived artifacts. The current
  `backend/scripts/export_questionnaire_frontend.py` exporter writes to both frontend
  versions, so running it is a cross-version update and requires explicit user
  approval to update `frontend-v2/`. Do not hand-edit a generated copy or run the
  cross-version exporter merely to keep both versions synchronized.
- When the OpenAPI contract changes, update `docs/openapi.json` and regenerate or
  check committed frontend API types as documented in `docs/README.md` and the
  frontend README.

## 7. Clinical Safety, Privacy, and Data Boundaries

- Treat changes to triage, emergency escalation, red-flag symptoms, medications,
  diagnosis or treatment suggestions, interview stopping conditions, clinical
  summaries, questionnaires, and safety rules as high-risk clinical changes.
- High-risk clinical content must have explicit provenance and must remain subject to
  qualified human or clinical review. Model output alone must not publish or approve
  clinical rules.
- Clearly distinguish confirmed source data, patient-reported information, model
  inference, provisional content, simulation, and clinician-reviewed content.
- Preserve safe behavior when information is missing, contradictory, malformed, or
  unavailable. Do not replace an explicit failure or escalation with a confident
  clinical guess.
- Maintain institution, tenant, patient, encounter, and user-role isolation across
  API, database, FHIR, UCC, SMART, cache, and audit paths.
- Never use real patient, personal, institutional, or production data in tests,
  fixtures, examples, prompts, screenshots, or devlogs.
- Never log or commit protected health information, personal data, credentials,
  access tokens, private keys, populated `.env` files, clinical payloads, or raw model
  prompts containing sensitive data.
- Do not send clinical or personal data to a new external model, analytics provider,
  avatar provider, or other third party without explicit user approval and a review
  of the data boundary.
- Security controls must fail closed. Development bypasses must be explicit, disabled
  by default, and restricted so they cannot weaken production behavior.

## 8. Architecture and Implementation Quality

- Separate domain and clinical rules from HTTP transport, UI, persistence,
  configuration, model providers, and external integrations.
- Keep dependencies directed and explicit. Avoid circular dependencies, hidden global
  state, and generic dumping grounds such as unbounded `utils`, `helpers`, or
  `common` modules.
- Prefer clear composition and small stable interfaces over large inheritance
  hierarchies or speculative frameworks.
- Keep business and safety rules testable without a live network, GUI, production
  database, or third-party service whenever practical.
- Follow existing language, naming, formatting, typing, and module conventions.
- Validate inputs at system boundaries and handle failures deliberately. Do not
  silently swallow exceptions or return ambiguous success values.
- Keep configuration outside business logic. Do not introduce unexplained magic
  constants or environment-dependent behavior without documentation.
- Comment intent, invariants, provenance, and non-obvious tradeoffs rather than
  restating straightforward code.
- Remove newly introduced dead code. Preserve compatibility shims only when their
  purpose and removal conditions are documented.

## 9. File and Function Size

- File size is a review signal, not an automatic failure and not a requirement to
  refactor unrelated legacy code.
- For new files or substantial expansions, reconsider cohesion around 300 lines and
  strongly justify growth beyond 500 lines.
- Existing large modules may be changed without unrelated decomposition. If the task
  adds another responsibility or materially increases complexity, prefer extracting
  a named, testable unit when that can be done safely within scope.
- Treat functions around 50 lines as a refactoring signal when extraction improves
  cohesion, clarity, or testing. Avoid artificial splitting and excessive
  indirection.
- Generated code, derived data, schemas, fixtures, migrations, and source corpora are
  exempt when splitting or hand-editing would reduce correctness or provenance.

## 10. Dependencies, APIs, and Data Compatibility

- Reuse existing dependencies when they adequately solve the problem.
- Ask before adding a production dependency that materially affects security,
  privacy, licensing, bundle size, deployment, GPU requirements, or maintenance.
- Pin or constrain versions according to the conventions of the affected component.
- Preserve public APIs, OpenAPI schemas, FHIR mappings, file formats, environment
  variables, database schemas, CLI behavior, and persisted clinical data unless a
  breaking change is explicitly approved.
- Document the impact and migration path for approved breaking changes.
- Database migrations must protect existing data and be reversible when practical.
- Changes to prompts, RAG corpora, questionnaire sources, disease profiles, or safety
  rules must retain source/version provenance and avoid overwriting prior reviewed or
  experimental outputs.

## 11. Tests and Verification

- Every behavior change must include or update tests at the lowest effective level.
- Add a deterministic regression test for a bug fix whenever the defect can be
  reproduced reliably.
- Cover normal behavior, relevant boundary cases, expected failures, authorization
  failures, and safe clinical fallbacks for the changed behavior.
- Run the narrowest relevant checks during development. Run broader checks when a
  change crosses components, changes a shared contract, or affects high-risk clinical
  or security behavior.
- Do not weaken, delete, or skip tests merely to make a change pass.
- Do not claim a check passed unless it was actually run successfully. If a check
  cannot run, report the exact command, reason, and remaining verification gap.

Common verification commands are:

```bash
# Backend (run from backend/)
venv/bin/ruff check .
venv/bin/ruff format --check .
venv/bin/pyright --project pyproject.toml
venv/bin/lint-imports --config .importlinter
venv/bin/python -m unittest discover -s tests

# Existing frontend (run from frontend/)
npm test
npm run build
npm run api:check

# Split frontend (run from frontend-v2/)
npm test
npm run build

# Avatar service (run from avatar-service/ with its environment available)
python -m unittest discover -s tests

# Repository hooks (run from repository root)
pre-commit run --all-files
```

Use the interpreter and environment already configured for the component. Do not
install dependencies, download models, start external services, or access production
systems unless the task requires it and the user has authorized the consequential
action. Follow the nearest README for deployment, FHIR, GPU, and end-to-end checks.

## 12. Research, RAG, and ML Work

- Record random seeds, dataset or cohort versions, splits, preprocessing,
  configuration, model/provider version, prompt version, retrieval configuration,
  and evaluation definitions needed for reproducibility.
- Separate source data, configuration, derived data, indexes, checkpoints, reports,
  and figures into clearly defined locations.
- Do not commit large datasets, model weights, generated media, vector indexes, or
  confidential material unless repository policy and the user explicitly require it.
- Use immutable run identifiers or versioned result directories; do not overwrite
  prior experimental results.
- Record failed or inconclusive experiments when they affect later decisions.
- Prevent train/test leakage, patient-level leakage, answer leakage, and evaluation
  against the same material used to construct a questionnaire or retrieval corpus.
- Report measured results separately from assumptions and interpretations.

## 13. Documentation

- Update the nearest relevant README when setup, execution, configuration, directory
  responsibility, public interfaces, clinical review workflow, or deployment behavior
  changes.
- Do not add README files to trivial leaf folders, generated output, caches, vendored
  code, or self-explanatory fixtures.
- Parent documentation should provide navigation and shared concepts; child
  documentation should own local details without copying the parent.
- Keep examples synthetic and free of secrets or sensitive clinical information.

## 14. Code Review Rules

Review in this order:

1. Functional and clinical correctness, including regressions and unsafe confidence.
2. Security, privacy, authorization, tenant isolation, and destructive side effects.
3. Data integrity, concurrency, auditability, and error handling.
4. API, schema, configuration, FHIR, deployment, and backward compatibility.
5. Test coverage and verification gaps.
6. Architecture, cohesion, and maintainability.

For each actionable finding, provide severity, exact file and line, a concrete failure
scenario and impact, why existing guards or tests do not prevent it, and the smallest
safe correction. Do not report formatting preferences already enforced by tooling. If
no actionable issue is found, say so and list remaining inspection or test gaps.

## 15. Definition of Done

Completion depends on the task type:

- Investigation or review: provide an evidence-based conclusion, identify inspected
  scope and verification gaps, and do not modify files unless asked.
- Small implementation: satisfy the requested behavior, add or update relevant tests,
  run focused verification, update every affected service version record, and review
  the diff for unrelated changes or secrets.
- Cross-component, clinical, security, architecture, API, or deployment change: also
  run appropriate broader checks, update affected documentation and the dated devlog,
  and disclose migration or operational impact.
- Commit, push, or PR work: perform it only when explicitly requested and report the
  resulting identifiers.

Every final handoff must summarize the outcome, files changed, checks actually run,
known limitations, and any decision or next step that still requires the user.
