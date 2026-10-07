# Methods (draft for JMS Brief Report)

> Drafting notes (delete before submission): items in **[brackets]** are unresolved and
> need the authors' decision; each is grounded in the repository state at commit
> `6eb242a` (branch `simple-questionnaire-rag-avatar`). Numbers are not reported here.
>
> Framing: the contribution is the **framework**: its stages, the data contract at
> each stage boundary, and the safety invariants that hold whatever is plugged in.
> Each module described below is the *reference implementation* of a stage, chosen to
> make the pipeline work end to end; it is not the object of study. Module-level
> choices (e.g. a fixed questionnaire versus a conversational interview) are
> deliberately left to follow-up studies.

## 2. Methods

### 2.1 Framework overview

We propose a modular framework for AI-assisted pre-consultation that integrates with
a hospital electronic health record (EHR) through HL7 FHIR R4. The framework divides
pre-consultation into six stages (Fig. 1), each defined by what it receives and what
it must return (Table 1). Any implementation that satisfies a stage's contract can
replace the reference module, so each stage can be developed and evaluated on its own
while the rest of the pipeline stays fixed.

**Table 1. Stages, contracts and reference implementations**

| Stage | Input → output contract | Reference implementation | Example substitutes (further study) |
|---|---|---|---|
| S1 Authorization & history retrieval | registration → authorized session + FHIR R4 history (TW Core) | one-time QR invitation; EHR prefill or SMART on FHIR | other EHR launch flows; patient portal login |
| S2 Patient interview | chief complaint + FHIR history → structured answers (fixed answer schema) | complaint-specific fixed questionnaire, with optional avatar | LLM-driven conversational interview (AMIE-style); adaptive questionnaires |
| S3 Red-flag alerting | free text / answers → finding codes → rule decision (continue / urgent / hand off) | deterministic rules + LLM normalization to whitelisted codes | calibrated local classifier; clinician-curated rule sets |
| S4 Knowledge retrieval | query from answers → ranked evidence passages | dense retrieval over a medical literature corpus | knowledge graph (e.g. PrimeKG/MedKGI); guideline corpora |
| S5 Record generation | answers + evidence → schema-validated record (history, ranked DDx, not-to-miss, work-up) | Gemini, 12 single-task schema-constrained calls | local or other LLMs; graph-based or rule-based rankers |
| S6 Review & write-back | record → physician-confirmed FHIR `Composition` | doctor-facing application embedded in the EHR | other EHR documentation targets |

The framework fixes three invariants that every substitute must preserve:
(i) **red-flag alerting** runs on the interview's output and can stop the interview,
and models only produce labels for auditable rules, never the urgency decision;
(ii) **fail closed**: a stage failure is surfaced or handed to staff, never replaced
by a confident default; and (iii) **no write-back without review**: generated
content stays labelled as unconfirmed until a physician confirms it. The framework is
a research prototype; its output does not constitute a diagnosis.

**[State honestly: the stage boundaries are enforced as data contracts (FHIR
resources, answer and finding-code schemas, JSON response schemas validated by the
backend), not as a formal plugin API. Only S4/S5 substitutes have been exercised
(see 2.8); substitution at S2 is supported by the contract but not yet demonstrated.]**

### 2.2 Reference implementation

The modules below are described only to the depth needed to reproduce the pipeline.

**S1: Authorization and history retrieval.** After registration, the hospital system
requests a one-time invitation using a service-signed RS256 JWT. The QR code carries
only an opaque random token (no patient data), which is exchanged once for a
time-limited session cookie with CSRF protection and institution/encounter isolation.
Prior history (demographics, conditions, procedures, medications, allergies) is
obtained as FHIR R4 resources (TW Core 1.0.0) and used to skip questions already
answered in the EHR. **[Decide and state which path the studied deployment used:
EHR-provided invitation prefill (production path) or SMART on FHIR reads (PKCE S256)
in the sandbox.]** SMART access tokens are never forwarded to the backend or the LLM.

**S2: Patient interview.** The reference interview is a fixed questionnaire selected
from the chief complaint by local keyword rules: common sections (chief complaint,
demographics, history, medications, allergies), then a complaint-specific module.
Modules for chest pain, headache and abdominal pain are enabled. A locally hosted avatar
(Breeze-ASR-26 speech recognition, CosyVoice 3 synthesis, MuseTalk 1.5 lip-sync; all
on-premises) can read questions aloud and accept voice answers, which the patient
confirms before submission. The interview runs without the avatar if needed.
A fixed questionnaire was chosen as the reference because it makes collected
information identical across patients, which simplifies evaluating downstream
stages; whether a conversational interview collects more complete information is a
question for a follow-up study. **[Confirm the source and clinical review status of
the three modules; 49 further candidate modules are provisional and disabled.]**

**S3: Red-flag alerting.** At the chief-complaint step, deterministic raw-text rules
(negation-aware) run first; if none fires, an LLM maps the free text to whitelisted
finding codes, each requiring verbatim evidence, and versioned structured rules
evaluate those codes. A match ends the interview, flags the record as urgent and
stores the triggering rule and evidence. Extraction failure hands the patient to
staff. Rule publication requires a named reviewer and an audit snapshot. The rules
are provisional, not clinically approved, limited to the three complaint routes, and
their recall has not been measured.

**S4: Knowledge retrieval.** The reference corpus is Medscape articles (Emergency
Medicine, Infectious Diseases, Laboratory Medicine), chunked and embedded with
`paraphrase-multilingual-MiniLM-L12-v2` in a local vector store. Results for the
diagnosis/examination, laboratory and imaging tasks are retrieved from separate
partitions and fused by reciprocal rank fusion. **[Open: Medscape terms of use; no
licence statement in the repository. If it cannot be cleared, swap in another corpus;
this is itself an S4 substitution.]**

**S5: Record generation.** Gemini generates the record in 12 single-task requests,
each constrained by a JSON response schema and re-validated by the backend; any
failure aborts generation and keeps the answers for retry. Output: structured history,
up to five ranked differential diagnoses, five not-to-miss diagnoses, and suggested
examination, laboratory and imaging work-up. Patient answers and retrieved text are
treated as untrusted data in prompts. No treatment or disposition recommendation is
produced.

> **Note:** the differential was extended from three to five items in backend
> v0.16.0; earlier ER-Reason runs used three and must be re-run before reporting top-5.

**S6: Review and write-back.** The physician edits and confirms each history section
in a doctor-facing application embedded in the EHR. Only then is a `Composition`
(TW Core, LOINC 11503-0, status `preliminary`) posted to the FHIR server, keyed for
idempotency, with patient/encounter references verified and the author derived from
the signed practitioner identity. Write-back requires a dedicated scope and is off
by default. **[State limitation: only synthetic data on a test server; no
`Condition`, `Provenance` or signature resources are written.]**

### 2.3 Deployment setting

Services run as Docker containers on a single GPU host behind an Nginx gateway; the
physician interface is embedded in the EHR through a reverse proxy. **[Name site(s),
dates, number of users; none is recorded in the repository and no hospital
acceptance test is documented.]** The reference S5 sends questionnaire content to an
external LLM provider; real-patient use requires institutional consent, a vendor
agreement and privacy review. **[Ethics/IRB statement needed.]**

### 2.4 Evaluation: demonstrating stage-level substitution

The evaluation demonstrates the framework property: the same S2 output can be held
fixed while S4/S5 are swapped and compared under one protocol. It does not claim
clinical accuracy for any module.

**Dataset.** ER-Reason v1.0.0 (PhysioNet, credentialed access). *Not MIMIC-IV;
correct the outline unless a different dataset is intended.* Because the dataset has
no structured symptom answers, an LLM-simulated patient answered the questionnaire
from only the pre-examination portion of the ED provider note; diagnosis fields were
never shown. Encounters were included when the chief complaint routed to one of the
three modules and the ED diagnosis mapped to one of 33 disease profiles; earliest
eligible encounter per patient (n = 92). Cases where the gold diagnosis appeared in
the simulator input were analysed as a sensitivity subset.

**Reference standard.** ED primary diagnosis mapped to a disease profile by an LLM
draft reviewed by a second model; **clinician review has not been performed.**

**Substitution arms (S4/S5).** Gemini with retrieval, Gemini without retrieval,
rule-based vote (AMIE unit_vote) and knowledge-graph posterior (MedKGI), all on
identical interview transcripts.

**Metrics.** Top-1/3/5 accuracy by exact profile match (failures kept in the
denominator, Wilson 95% CIs, exact McNemar for paired arms), and not-to-miss
coverage among cases whose gold diagnosis is not-to-miss. **[Define the intended
multi-reference "top-5 DDx coverage" and "not-to-miss coverage" or reword; one gold
label per case.]** Temperature 0.1 where supported; **[no seeds, single run per arm;
add repeats]**.

**[Confirm the PhysioNet DUA permits sending note excerpts to Gemini; many
credentialed-access DUAs prohibit external LLM APIs unless no-retention terms are
met.]**
