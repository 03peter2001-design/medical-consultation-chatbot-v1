<script setup>
import { computed } from 'vue'

import { getPainMapPreset } from '../data/bodyPainRegions.js'
import { buildClinicalRecord } from '../services/clinicalRecord.js'
import {
  formatEmrSummary,
  parseEmrFields,
  splitStructuredNote,
} from '../services/structuredNote.js'
import BodyPainMap from './BodyPainMap.vue'
import ClinicalEvidence from './ClinicalEvidence.vue'
import PhysicianSummary from './PhysicianSummary.vue'
import SourceTags from './SourceTags.vue'
import StructuredReport from './StructuredReport.vue'
import TerminologyCode from './TerminologyCode.vue'

const props = defineProps({
  record: { type: Object, required: true },
})

const clinical = computed(() => buildClinicalRecord(props.record))
const emrSummary = computed(
  () =>
    formatEmrSummary(
      props.record,
      splitStructuredNote(props.record.structured_note).emrSummary,
    ),
)
const emrPreview = computed(
  () => emrSummary.value.split(/\r?\n/).find(Boolean) || '',
)
const painMapPreset = computed(() => getPainMapPreset(props.record.type))
const painLocationIds = computed(() =>
  (props.record.pain_locations || [])
    .map((location) =>
      typeof location === 'string' ? location : location.id,
    )
    .filter(Boolean),
)
const patientData = computed(
  () => props.record.patient_data || props.record.data || {},
)
const complaintDuration = computed(
  () =>
    patientData.value.onset ||
    [patientData.value.onset_num, patientData.value.onset_unit]
      .filter(Boolean)
      .join(' '),
)
const parsedEmrFields = computed(() =>
  parseEmrFields(props.record.structured_note),
)
const physicianSummaryRows = computed(() => {
  const parsed = parsedEmrFields.value
  const parsedSource = 'Gemini 彙整 · 待醫師確認'
  const history = clinical.value.historyFacts
  const historyValue = history
    .filter(
      (fact) =>
        !['past_meds', 'current_meds', 'allergy'].includes(fact.key),
    )
    .map((fact) => `${fact.label}：${fact.value}`)
    .join('；')
  const medicationValue = [
    patientData.value.past_meds
      ? `過去用藥：${patientData.value.past_meds}`
      : '',
    patientData.value.current_meds
      ? `目前用藥：${patientData.value.current_meds}`
      : '',
  ]
    .filter(Boolean)
    .join('；')
  const onsetValue = complaintDuration.value
    ? `發作／持續時間：${complaintDuration.value}`
    : '現病史細節未提供'

  return [
    {
      key: 'Chief Complaint',
      label: '主訴',
      value: parsed.cc || clinical.value.complaint,
      source: parsed.cc ? parsedSource : '病人自述',
    },
    {
      key: 'Present Illness',
      label: '現病史',
      value: parsed.pi || onsetValue,
      source: parsed.pi ? parsedSource : '結構化資料',
    },
    {
      key: 'Past History',
      label: '過去病史',
      value: parsed.ph || historyValue || '尚無結構化過去病史',
      source: parsed.ph ? parsedSource : '結構化資料',
    },
    {
      key: 'Drug History',
      label: '用藥史',
      value: parsed.meds || medicationValue || '用藥史未提供',
      source: parsed.meds ? parsedSource : '結構化資料',
    },
    {
      key: 'Allergy History',
      label: '過敏史',
      value: parsed.allergy || patientData.value.allergy || '過敏史未提供',
      source: parsed.allergy ? parsedSource : '結構化資料',
    },
    {
      key: 'Personal History',
      label: '個人史',
      value:
        parsed.personal ||
        patientData.value.personal_history ||
        '個人史未提供',
      source: parsed.personal ? parsedSource : '結構化資料',
    },
    {
      key: 'Family History',
      label: '家族病史',
      value:
        parsed.family || patientData.value.family_history || '家族病史未提供',
      source: parsed.family ? parsedSource : '結構化資料',
    },
  ]
})
</script>

<template>
  <article class="clinical-dashboard">
    <header class="patient-identity">
      <span class="identity-eyebrow" aria-hidden="true" />
      <div class="identity-content">
        <div class="identity-title">
          <h2>{{ clinical.identity.name }}</h2>
          <span class="birth-date">
            出生日期 {{ clinical.identity.birthDate }}
          </span>
          <span>#{{ clinical.identity.queueNumber }}</span>
          <strong :class="{ urgent: clinical.identity.urgent }">
            {{ clinical.identity.triage }}
          </strong>
        </div>
        <dl class="identity-meta">
          <div class="identity-highlight identity-demographics">
            <dt>基本資料</dt>
            <dd>
              {{ clinical.identity.gender }} /
              {{ clinical.identity.age }} /
              {{ clinical.identity.bloodType }}
              <span
                v-if="clinical.identity.bloodTypeCodings.length"
                class="inline-codings"
              >
                <TerminologyCode
                  v-for="coding in clinical.identity.bloodTypeCodings"
                  :key="`${coding.system}-${coding.code}`"
                  :coding="coding"
                />
              </span>
            </dd>
          </div>
          <div class="identity-highlight identity-category">
            <dt>主訴分類</dt>
            <dd>{{ clinical.identity.type }}</dd>
          </div>
          <div class="complaint">
            <dt>摘要</dt>
            <dd>
              {{ clinical.identity.age }}{{ clinical.identity.gender }} ，主訴為「{{ clinical.complaint }}」
              <template v-if="complaintDuration">
                ，持續時間{{ complaintDuration?.slice(0, -1) }}
              </template>
            </dd>
          </div>
        </dl>
      </div>
    </header>

    <section
      v-if="clinical.redFlags.length"
      class="red-flag-banner"
      role="alert"
    >
      <span class="alert-mark" aria-hidden="true">!</span>
      <div>
        <span>臨床警訊</span>
        <strong>
          {{ clinical.redFlags.map((flag) => flag.label).join('、') }}
        </strong>
        <small
          v-if="clinical.redFlags.some((flag) => flag.evidence)"
        >
          證據：
          {{
            clinical.redFlags
              .map((flag) => flag.evidence)
              .filter(Boolean)
              .join('、')
          }}
        </small>
      </div>
    </section>

    <div class="snapshot-grid">
      <section class="snapshot-section">
        <div class="section-heading">
          <div>
            <span>本次問診</span>
            <h3>關鍵症狀</h3>
          </div>
          <strong>{{ clinical.findings.length }}</strong>
        </div>

        <div v-if="clinical.findings.length" class="finding-list">
          <span
            v-for="finding in clinical.findings"
            :key="`${finding.code}-${finding.evidence}`"
          >
            {{ finding.evidence || finding.label }}
          </span>
        </div>
        <p v-else class="section-empty">尚無結構化關鍵症狀</p>

        <dl v-if="clinical.symptomFacts.length" class="fact-list">
          <div
            v-for="fact in clinical.symptomFacts"
            :key="fact.key"
            class="fact-row"
          >
            <dt>{{ fact.label }}</dt>
            <dd>
              <span>{{ fact.value }}</span>
              <span v-if="fact.codings.length" class="fact-codings">
                <TerminologyCode
                  v-for="coding in fact.codings"
                  :key="`${coding.system}-${coding.code}-${coding.field}`"
                  :coding="coding"
                />
              </span>
            </dd>
          </div>
        </dl>
      </section>

      <section class="snapshot-section">
        <div class="section-heading">
          <div>
            <span>病史資料</span>
            <h3>重要背景</h3>
          </div>
        </div>

        <dl v-if="clinical.historyFacts.length" class="history-list">
          <div
            v-for="fact in clinical.historyFacts"
            :key="fact.key"
            class="history-row"
          >
            <span
              class="history-status"
              :class="fact.tone"
              aria-hidden="true"
            />
            <dt>{{ fact.label }}</dt>
            <dd>
              <span>{{ fact.value }}</span>
              <span v-if="fact.codings.length" class="fact-codings">
                <TerminologyCode
                  v-for="coding in fact.codings"
                  :key="`${coding.system}-${coding.code}-${coding.field}`"
                  :coding="coding"
                />
              </span>
            </dd>
          </div>
        </dl>
        <p v-else class="section-empty">尚無結構化病史資料</p>
      </section>

      <section class="snapshot-section pain-section">
        <div class="section-heading">
          <div>
            <span>病人自述</span>
            <h3>疼痛或不適位置</h3>
          </div>
          <strong>{{ painLocationIds.length }}</strong>
        </div>

        <BodyPainMap
          v-if="painLocationIds.length"
          :model-value="painLocationIds"
          :preset="painMapPreset"
          readonly
          compact
        />
        <div v-else class="pain-empty">
          <svg viewBox="0 0 64 84" aria-hidden="true">
            <circle cx="32" cy="14" r="10" />
            <path d="M23 27h18l7 20-8 3 3 30H32l-3-27-3 27H15l3-30-8-3 7-20z" />
          </svg>
          <div>
            <strong>未標記部位</strong>
            <span>本次問診沒有圖像化疼痛位置</span>
          </div>
        </div>
      </section>
    </div>

    <StructuredReport
      v-if="record.structured_note"
      class="patient-summary-report"
      :text="record.structured_note"
      hide-emr
    />
    <details v-if="emrSummary" class="emr-summary">
      <summary class="emr-summary-trigger">
        <span class="emr-mark" aria-hidden="true">RAG</span>
        <span class="emr-summary-label">
          <span class="emr-summary-title-row">
            <strong id="emr-summary-title">RAG 病歷／文獻摘要</strong>
            <small>Gemini 生成 · 待醫師確認</small>
          </span>
          <span class="emr-summary-preview">{{ emrPreview }}</span>
        </span>
        <span class="emr-summary-action">
          <span v-if="record.structured_sources?.length">
            {{ record.structured_sources.length }} 項來源
          </span>
          <span v-else>查看完整摘要</span>
          <svg
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="1.8"
            aria-hidden="true"
          >
            <path d="m6 8 4 4 4-4" />
          </svg>
        </span>
      </summary>
      <section
        class="emr-summary-content"
        aria-labelledby="emr-summary-title"
      >
        <p>{{ emrSummary }}</p>
        <SourceTags :sources="record.structured_sources || []" />
      </section>
    </details>

    <PhysicianSummary
      class="physician-summary"
      :rows="physicianSummaryRows"
      :report="record.report"
    />

    <details class="clinical-evidence-disclosure">
      <summary>
        <span>
          <small>固定規則、疾病票數與問診軌跡</small>
          <strong>臨床依據與稽核資料</strong>
        </span>
        <em>展開完整依據</em>
      </summary>
      <ClinicalEvidence :clinical="clinical" />
    </details>
  </article>
</template>

<style scoped>
.clinical-dashboard {
  width: 100%;
  flex: 0 0 auto;
  overflow: hidden;
  border: 1px solid #cfdbe6;
  border-radius: 10px;
  background: #fff;
  color: #1b3145;
  font-size: 15px;
  box-shadow: 0 8px 24px rgb(32 65 91 / 7%);
}

.patient-identity {
  display: grid;
  grid-template-columns: 4px minmax(0, 1fr);
  gap: 12px;
  padding: 20px 22px 18px;
  border-bottom: 1px solid #dbe4ec;
}

.identity-eyebrow {
  overflow: hidden;
  width: 4px;
  border-radius: 4px;
  background: #2568b2;
  color: transparent;
}

.identity-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 7px 14px;
}

.identity-title h2 {
  color: #17324d;
  font-size: clamp(24px, 2.2vw, 31px);
  line-height: 1.2;
  letter-spacing: 0.01em;
}

.identity-title > span {
  color: #61758a;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.identity-title .birth-date {
  font-family: 'Noto Sans TC', system-ui, sans-serif;
  font-size: 14px;
}

.identity-title > strong {
  margin-left: auto;
  padding: 4px 9px;
  border: 1px solid #9fcfc4;
  border-radius: 6px;
  background: #eef9f6;
  color: #087f6d;
  font-size: 12px;
}

.identity-title > strong.urgent {
  border-color: #ef9ca5;
  background: #fff3f4;
  color: #b83243;
}

.identity-meta {
  display: grid;
  grid-template-columns: minmax(260px, auto) minmax(220px, 1fr);
  gap: 10px;
  margin-top: 14px;
}

.identity-meta > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.identity-meta > .identity-highlight {
  display: grid;
  min-width: 0;
  min-height: 58px;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  padding: 10px 13px;
  border: 1px solid #c7d9e9;
  border-left: 4px solid #2568b2;
  border-radius: 8px;
  background: #f5f9fd;
}

.identity-meta .identity-highlight dt {
  padding: 3px 7px;
  border-radius: 4px;
  background: #dcebf8;
  color: #1e5f98;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.identity-meta .identity-highlight dd {
  overflow-wrap: anywhere;
  color: #17324d;
  font-size: clamp(16px, 1.4vw, 19px);
  font-weight: 750;
  line-height: 1.45;
}

.identity-meta > .identity-category {
  border-color: #a9d3ca;
  border-left-color: #0b8c78;
  background: #eef9f6;
}

.identity-meta .identity-category dt {
  background: #d9f0eb;
  color: #087563;
}

.identity-meta .identity-category dd {
  color: #086f60;
}

.identity-meta dt {
  flex: 0 0 auto;
  color: #6b7f92;
  font-size: 12px;
  font-weight: 650;
}

.identity-meta dd {
  color: #2c4357;
  font-size: 14px;
}

.identity-meta .complaint {
  display: grid;
  min-width: 0;
  grid-column: 1 / -1;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: baseline;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid #d8e1e9;
}

.identity-meta .complaint dt {
  padding-left: 10px;
  border-left: 3px solid #2568b2;
  color: #2568b2;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.identity-meta .complaint dd {
  color: #16334a;
  font-size: clamp(16px, 1.6vw, 20px);
  font-weight: 700;
  line-height: 1.5;
}

.inline-codings,
.fact-codings {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-left: 6px;
  vertical-align: middle;
}

.red-flag-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 14px 18px 0;
  padding: 12px 14px;
  border: 1px solid #eb8793;
  border-left: 4px solid #c6404f;
  border-radius: 7px;
  background: #fff6f7;
  color: #ab2d3d;
}

.alert-mark {
  display: grid;
  width: 27px;
  height: 27px;
  flex: 0 0 27px;
  place-items: center;
  border-radius: 50%;
  background: #c6404f;
  color: #fff;
  font-size: 16px;
  font-weight: 800;
}

.red-flag-banner div {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
}

.red-flag-banner span:not(.alert-mark) {
  font-size: 12px;
  font-weight: 700;
}

.red-flag-banner strong {
  font-size: 16px;
}

.red-flag-banner small {
  width: 100%;
  color: #98505a;
  font-size: 13px;
}

.snapshot-grid {
  display: grid;
  grid-template-columns: 1fr 1fr minmax(270px, 1.05fr);
  margin: 14px 18px 0;
  border: 1px solid #cbd7e1;
  border-radius: 7px;
}

.snapshot-section {
  min-width: 0;
  padding: 15px 17px;
}

.snapshot-section + .snapshot-section {
  border-left: 1px solid #cbd7e1;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-heading span {
  color: #6b7f92;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.section-heading h3 {
  margin-top: 1px;
  color: #17324d;
  font-size: 17px;
}

.section-heading > strong {
  color: #2568b2;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.finding-list {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-bottom: 14px;
}

.finding-list span {
  padding: 5px 8px;
  border: 1px solid #ef9ca5;
  border-radius: 5px;
  background: #fff7f8;
  color: #b83243;
  font-size: 12px;
  font-weight: 650;
}

.fact-list,
.history-list {
  display: grid;
  gap: 8px;
}

.fact-row {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid #e5ebf1;
}

.history-row {
  display: grid;
  grid-template-columns: 8px 76px minmax(0, 1fr);
  gap: 8px;
  align-items: baseline;
}

.fact-row dt,
.history-row dt {
  color: #6b7f92;
  font-size: 12px;
}

.fact-row dd,
.history-row dd {
  min-width: 0;
  color: #2b4256;
  line-height: 1.5;
}

.history-row dd {
  display: grid;
  gap: 5px;
}

.fact-codings {
  margin-left: 0;
}

.history-status {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #2568b2;
}

.history-status.clear {
  background: #0a927e;
}

.section-empty {
  color: #6b7f92;
  font-size: 13px;
  line-height: 1.6;
}

.pain-section :deep(.body-map) {
  width: 100%;
  border: 0;
  background: transparent;
}

.pain-section :deep(.compact .figure-stage) {
  height: 150px;
}

.pain-section :deep(.side-label) {
  display: none;
}

.pain-empty {
  display: flex;
  min-height: 150px;
  align-items: center;
  justify-content: center;
  gap: 18px;
  color: #6b7f92;
}

.pain-empty svg {
  width: 46px;
  fill: #edf3f8;
  stroke: #8aa4ba;
  stroke-linejoin: round;
  stroke-width: 1.5;
}

.pain-empty div {
  display: grid;
  gap: 3px;
}

.pain-empty strong {
  color: #2c4357;
}

.pain-empty span {
  max-width: 180px;
  font-size: 12px;
}

.patient-summary-report,
.emr-summary,
.physician-summary,
.clinical-evidence-disclosure {
  margin: 14px 18px 0;
}

.emr-summary {
  overflow: hidden;
  border: 1px solid #58aa9c;
  border-left: 5px solid #087f6d;
  border-radius: 7px;
  background: #fff;
  box-shadow: 0 4px 14px rgb(23 86 75 / 7%);
}

.emr-summary-trigger {
  display: grid;
  min-height: 76px;
  grid-template-columns: 38px minmax(0, 1fr) auto;
  align-items: center;
  gap: 11px;
  padding: 12px 14px;
  background: #f3fbf9;
  cursor: pointer;
  list-style: none;
  transition: background 0.18s ease;
}

.emr-summary-trigger::-webkit-details-marker {
  display: none;
}

.emr-summary-trigger:hover {
  background: #ecf8f5;
}

.emr-summary-trigger:focus-visible {
  outline: 2px solid #087f6d;
  outline-offset: -3px;
}

.emr-summary[open] .emr-summary-trigger {
  border-bottom: 1px solid #cbe7e1;
}

.emr-mark {
  display: grid;
  width: 38px;
  height: 30px;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 6px;
  background: #087f6d;
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.06em;
}

.emr-summary-label {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.emr-summary-title-row {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 3px 10px;
}

.emr-summary-title-row > strong {
  color: #087f6d;
  font-size: 17px;
  line-height: 1.3;
}

.emr-summary-title-row > small {
  color: #53766f;
  font-size: 11px;
}

.emr-summary-preview {
  overflow: hidden;
  color: #405f59;
  font-size: 13px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.emr-summary-action {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #087f6d;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.emr-summary-action svg {
  width: 18px;
  height: 18px;
  transition: transform 0.18s ease;
}

.emr-summary[open] .emr-summary-action svg {
  transform: rotate(180deg);
}

.emr-summary-content > p {
  padding: 14px 16px 10px 63px;
  color: #203f3b;
  font-size: 14px;
  font-weight: 550;
  line-height: 1.7;
  white-space: pre-wrap;
}

.emr-summary-content :deep(.source-list) {
  padding: 0 16px 15px 63px;
}

.clinical-evidence-disclosure > summary {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 16px;
  cursor: pointer;
  list-style: none;
}

.clinical-evidence-disclosure > summary::-webkit-details-marker {
  display: none;
}

.clinical-evidence-disclosure > summary span {
  display: grid;
  gap: 1px;
}

.clinical-evidence-disclosure > summary small {
  color: #6b7f92;
  font-size: 10px;
  letter-spacing: 0.05em;
}

.clinical-evidence-disclosure > summary strong {
  color: #2b4256;
  font-size: 14px;
}

.clinical-evidence-disclosure > summary em {
  color: #2568b2;
  font-size: 12px;
  font-style: normal;
  font-weight: 650;
}

.clinical-evidence-disclosure {
  margin-bottom: 18px;
  border: 1px solid #d6e0e9;
  border-radius: 7px;
  background: #f8fafc;
}

.clinical-evidence-disclosure > summary {
  min-height: 64px;
}

.clinical-evidence-disclosure[open] > summary {
  border-bottom: 1px solid #d6e0e9;
}

.clinical-evidence-disclosure :deep(.evidence-layout) {
  margin: 14px;
}

@media (max-width: 1040px) {
  .snapshot-grid {
    grid-template-columns: 1fr 1fr;
  }

  .pain-section {
    grid-column: 1 / -1;
    border-top: 1px solid #d6e0e9;
    border-left: 0 !important;
  }

  .pain-section :deep(.body-map) {
    max-width: 360px;
  }
}

@media (max-width: 700px) {
  .clinical-dashboard {
    border-right: 0;
    border-left: 0;
    border-radius: 0;
    box-shadow: none;
  }

  .patient-identity {
    gap: 9px;
    padding: 16px 14px;
  }

  .identity-title {
    align-items: center;
  }

  .identity-title h2 {
    flex: 1 0 100%;
  }

  .identity-title > strong {
    margin-left: 0;
  }

  .identity-meta {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .identity-meta > div {
    display: grid;
    gap: 1px;
  }

  .identity-meta > .identity-highlight {
    min-height: 54px;
    grid-template-columns: minmax(80px, auto) minmax(0, 1fr);
    gap: 9px;
    padding: 9px 11px;
  }

  .identity-meta .complaint {
    grid-column: 1;
    grid-template-columns: 1fr;
    gap: 4px;
    padding-top: 10px;
  }

  .red-flag-banner,
  .patient-summary-report,
  .snapshot-grid,
  .emr-summary,
  .physician-summary,
  .clinical-evidence-disclosure {
    margin-right: 12px;
    margin-left: 12px;
  }

  .snapshot-grid {
    grid-template-columns: 1fr;
  }

  .snapshot-section + .snapshot-section {
    border-top: 1px solid #d6e0e9;
    border-left: 0;
  }

  .pain-section {
    grid-column: auto;
  }

  .emr-summary-trigger {
    grid-template-columns: 38px minmax(0, 1fr);
    align-items: start;
    padding: 12px;
  }

  .emr-summary-action {
    grid-column: 2;
    justify-self: start;
  }

  .emr-summary-preview {
    white-space: normal;
  }

  .emr-summary-content > p,
  .emr-summary-content :deep(.source-list) {
    padding-right: 12px;
    padding-left: 12px;
  }

  .clinical-evidence-disclosure > summary {
    padding: 11px 12px;
  }

  .clinical-evidence-disclosure :deep(.evidence-layout) {
    margin: 10px;
  }
}
</style>
