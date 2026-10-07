# Red-flag detection with a calibrated structured classifier (design draft)

Status: research design for a separate full paper; not implemented. Search date
2026-10-02; the literature scan below is shallow (a few web searches, abstracts only)
and must be replaced by a systematic search before any novelty claim is made.

## 1. Problem and current system

In the default questionnaire pipeline, red flags are detected by 8 deterministic
raw-text rules at the chief-complaint step (backend v0.15.0). A more general path
(LLM free-text -> whitelisted finding codes -> 23 structured rules) exists only in the
legacy AMIE engine. Gaps: colloquial and Taiwanese-Mandarin expressions, negation,
multi-symptom complaints, and no measured recall for either path.

## 2. Proposed method

A locally hosted "System One"-style model: one forward pass answers all typed
questions in parallel and returns calibrated confidences. The downstream rules stay
deterministic and auditable; the model only supplies labels.

- **Input**: current patient utterance, prior confirmed labels from earlier turns,
  complaint route, and FHIR risk flags (anticoagulants, malignancy, pregnancy, ...).
- **Output heads** (one per finding code, ~86 initially): three states, `present`,
  `negated`, `not_mentioned`, each with a probability. Extra heads: onset, severity,
  new-or-worsening.
- **Backbone**: a small multilingual or Chinese encoder, hosted in-hospital (no
  data egress). LLM teacher labels synthetic colloquial text; clinician-adjudicated
  data fine-tunes and evaluates.
- **Loss**: asymmetric, higher weight on missing a `present` red-flag finding,
  weighted by clinical severity tier (to be set by clinicians).
- **Calibration and guarantee**: split-conformal / conformal risk control on a held-out
  clinician-labelled calibration set, per finding code, to bound the miss rate of
  `present` red-flag findings at level alpha. Inputs outside the guaranteed region
  abstain, which routes to human handoff (fail closed).
- **Decision layer**: unchanged versioned rules (`safety_rules.json`) consume the
  labels. Any abstention on a red-flag head, or model failure, hands off to staff.

## 3. Related work found (abstract-level; to verify)

| Theme | What exists | Implication |
| --- | --- | --- |
| LLM extraction + deterministic rule engine | TRACE, maternal/newborn triage (WhatsApp, India): LLM extracts canonical symptoms, a rule engine decides; recall 0.565 -> 0.810 reported ([arXiv 2609.09356](https://arxiv.org/pdf/2609.09356)) | The architecture itself is **not novel**. No calibration or abstention reported in the abstract. |
| LLM red-flag under-triage | Japanese vignette audit of gpt-4o-mini: 100% hard under-triage of urgent red-flag cases under near-deterministic decoding ([PMC13109825](https://pmc.ncbi.nlm.nih.gov/articles/PMC13109825/)) | Supports not letting a generative model decide urgency. |
| Add-only safety layer over rule-based red flags | Informal proposal in an open-source cancer-bot repo ([issue 197](https://github.com/gautamgauri/suchi-cancer-bot/issues/197)) | Idea is in circulation; not a publication. |
| Conformal triage | Imaging AI deployment ([medRxiv 2024](https://www.medrxiv.org/content/10.1101/2024.02.09.24302543v1)); ICU simulation ([medRxiv 2026](https://www.medrxiv.org/content/10.64898/2026.05.29.26354474v2.full)); prevalence-shift audit ([arXiv 2605.20956](https://arxiv.org/pdf/2605.20956)) | Conformal methods are established for risk triage over tabular/imaging inputs. |
| Conformal risk control for medical LLMs | Medical summarization safety layer ([arXiv 2606.08969](https://arxiv.org/pdf/2606.08969)); abstention in medical MCQA ([arXiv 2601.12471](https://arxiv.org/abs/2601.12471)); CRC limits for structured generation ([arXiv 2606.29054](https://arxiv.org/pdf/2606.29054)) | Guarantee machinery exists; not shown here for symptom-label extraction feeding rules. |
| Chinese symptom normalization / negation | Mostly traditional Chinese medicine records and FSA negation ([JBI 2021](https://dl.acm.org/doi/10.1016/j.jbi.2021.103718)) | Little found for Traditional Chinese colloquial patient text in Western-medicine red flags. |
| System One models | Jev, TypeSafe AI, hosted API, early access ([DataCamp](https://www.datacamp.com/blog/system-one-models-jev), [TypeSafe](https://typesafe.ai/blog/introducing-system-one-models-and-jev)) | Vendor claims; no medical evaluation found. |

## 4. Honest novelty assessment

- Not novel: LLM-extract-then-rules (TRACE), conformal prediction in medicine,
  abstention and handoff.
- Plausible contribution, if a systematic search confirms the gap:
  (1) a calibrated three-state (present / negated / not mentioned) multi-label
  extractor for red-flag findings with a finite-sample bound on missed `present`
  findings; (2) a locally hosted model with no data egress; (3) a clinician-adjudicated
  Traditional Chinese colloquial benchmark with negation and prompt-injection
  stress sets; (4) end-to-end evidence that the guarantee survives into the
  rule decision (rule-level recall, not only label-level).
- Caveat: the conformal guarantee requires exchangeability between calibration and
  deployment text. Distribution shift (new dialects, new hospitals) breaks it; the paper
  must test this explicitly (held-out site/phrasing split) rather than assume it.

## 5. Evaluation plan

- **Dataset**: synthetic colloquial utterances with gold finding states, adjudicated
  by >= 2 clinicians (agreement reported); strata for negation, multi-symptom,
  Taiwanese code-mixing, typos/ASR errors, injection attempts. Keep calibration, test
  and out-of-distribution phrasing splits strictly separate.
- **Metrics**: per-finding recall of `present` (with Wilson CIs), rule-level red-flag
  recall, recall at a fixed abstention rate, calibration error, handoff rate,
  false-alarm rate, latency, and cost.
- **Baselines**: current raw-text rules; current Gemini free-text extractor; Jev API
  (only if the authors obtain access and a data-boundary review permits synthetic
  inputs); the same classifier without conformal control.
- **External check**: ER-Reason pre-examination text as a distribution-shift probe;
  it has no red-flag labels, so use only after defining a labelling protocol, and
  confirm the PhysioNet DUA allows the planned processing.

## 6. Risks and open decisions

- Clinical review and annotation are the critical path (months, IRB or equivalent).
- Rare findings have few positives, so per-finding bounds will be loose; consider
  grouping findings by severity tier for the guarantee.
- High-risk clinical change: any use in the product needs clinical approval; the paper
  reports offline results only.
- Decisions for the authors: target language scope (Traditional Chinese only or
  including Taiwanese), whether to seek Jev access as a baseline, annotator
  availability, and the severity tiers and target alpha per tier.
