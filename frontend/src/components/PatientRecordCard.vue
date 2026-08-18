<script setup>
import { computed } from 'vue'

import { getPainMapPreset } from '../data/bodyPainRegions.js'
import { buildClinicalRecord } from '../services/clinicalRecord.js'
import {
  formatEmrSummary,
  splitStructuredNote,
} from '../services/structuredNote.js'
import BodyPainMap from './BodyPainMap.vue'
import ClinicalEvidence from './ClinicalEvidence.vue'
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
const painMapPreset = computed(() => getPainMapPreset(props.record.type))
const painLocationIds = computed(() =>
  (props.record.pain_locations || [])
    .map((location) =>
      typeof location === 'string' ? location : location.id,
    )
    .filter(Boolean),
)
</script>

<template>
  <article class="clinical-dashboard">
    <header class="patient-identity">
      <div>
        <div class="identity-title">
          <h2>{{ clinical.identity.name }}</h2>
          <span>#{{ clinical.identity.queueNumber }}</span>
          <strong :class="{ urgent: clinical.identity.urgent }">
            {{ clinical.identity.triage }}
          </strong>
        </div>
        <dl class="identity-meta">
          <div>
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
          <div>
            <dt>主訴分類</dt>
            <dd>{{ clinical.identity.type }}</dd>
          </div>
          <div class="complaint">
            <dt>主訴</dt>
            <dd>{{ clinical.complaint }}</dd>
          </div>
        </dl>

        <section
          v-if="emrSummary"
          class="emr-summary"
          aria-labelledby="emr-summary-title"
        >
          <div class="emr-summary-heading">
            <span class="emr-mark" aria-hidden="true">EMR</span>
            <div>
              <small>結構化病歷重點</small>
              <h3 id="emr-summary-title">病歷摘要 EMR</h3>
            </div>
            <strong>快速掌握病況</strong>
          </div>
          <p>{{ emrSummary }}</p>
        </section>
      </div>
    </header>

    <StructuredReport
      v-if="record.structured_note"
      class="patient-summary-report"
      :text="record.structured_note"
      :sources="record.structured_sources || []"
      hide-emr
    />

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

    <ClinicalEvidence :clinical="clinical" />

    <div class="narrative-grid">
      <details class="narrative-panel">
        <summary>
          <span>
            <small>原始文字</small>
            <strong>問卷摘要</strong>
          </span>
          <em>展開完整摘要</em>
        </summary>
        <p>{{ record.summary || '未提供問卷摘要' }}</p>
      </details>
      <details class="narrative-panel">
        <summary>
          <span>
            <small>Gemini 整理 · 固定疾病表</small>
            <strong>醫師速覽摘要</strong>
          </span>
          <em>展開約 300 字摘要</em>
        </summary>
        <p>{{ record.report || '尚未產生醫師速覽摘要' }}</p>
      </details>
    </div>
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
}

.patient-identity {
  padding: 20px 22px 17px;
  border-bottom: 1px solid #dbe4ec;
}

.patient-summary-report {
  margin: 16px 18px 0;
}

.identity-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
}

.identity-title h2 {
  font-size: clamp(23px, 2.2vw, 30px);
  line-height: 1.2;
  letter-spacing: 0.01em;
}

.identity-title > span {
  color: #61758a;
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
}

.identity-title > strong {
  padding: 5px 10px;
  border: 1px solid #9fcfc4;
  border-radius: 6px;
  background: #eef9f6;
  color: #087f6d;
  font-size: 13px;
}

.identity-title > strong.urgent {
  border-color: #ef9ca5;
  background: #fff3f4;
  color: #b83243;
}

.identity-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 26px;
  margin-top: 14px;
}

.identity-meta > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.identity-meta .complaint {
  display: grid;
  min-width: 0;
  flex: 1 0 100%;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  margin-top: 3px;
  padding: 12px 14px;
  border: 1px solid #c4d9e7;
  border-left: 4px solid #2568b2;
  border-radius: 8px;
  background: linear-gradient(90deg, #eef6fb 0%, #f8fbfd 100%);
}

.identity-meta .complaint dt {
  color: #2568b2;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.identity-meta .complaint dd {
  color: #16334a;
  font-size: clamp(17px, 1.6vw, 20px);
  font-weight: 700;
  line-height: 1.5;
}

.identity-meta dt {
  flex: 0 0 auto;
  color: #6b7f92;
  font-size: 12px;
  font-weight: 600;
}

.identity-meta dd {
  color: #2c4357;
  font-size: 15px;
}

.emr-summary {
  margin-top: 12px;
  overflow: hidden;
  border: 1px solid #8fc8bf;
  border-left: 5px solid #087f6d;
  border-radius: 9px;
  background: linear-gradient(120deg, #effaf7 0%, #f8fcfb 58%, #edf7fb 100%);
  box-shadow: 0 5px 16px rgb(23 72 88 / 9%);
}

.emr-summary-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px 10px;
  border-bottom: 1px solid #cce3df;
}

.emr-mark {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  place-items: center;
  border-radius: 8px;
  background: #087f6d;
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.emr-summary-heading div {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 1px;
}

.emr-summary-heading small {
  color: #53766f;
  font-size: 11px;
  letter-spacing: 0.05em;
}

.emr-summary-heading h3 {
  color: #15584f;
  font-size: 17px;
  line-height: 1.3;
}

.emr-summary-heading > strong {
  flex: 0 0 auto;
  padding: 4px 8px;
  border: 1px solid #add5ce;
  border-radius: 999px;
  background: rgb(255 255 255 / 75%);
  color: #087f6d;
  font-size: 11px;
}

.emr-summary > p {
  padding: 13px 15px 15px;
  color: #203f3b;
  font-size: 15px;
  font-weight: 550;
  line-height: 1.75;
  white-space: pre-wrap;
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
  margin: 16px 18px 0;
  padding: 13px 15px;
  border: 1px solid #eb8793;
  border-radius: 8px;
  background: #fff6f7;
  color: #ab2d3d;
}

.alert-mark {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  place-items: center;
  border-radius: 50%;
  background: #c6404f;
  color: #fff;
  font-size: 17px;
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
  font-size: 17px;
}

.red-flag-banner small {
  width: 100%;
  color: #98505a;
  font-size: 13px;
}

.snapshot-grid {
  display: grid;
  grid-template-columns: 1fr 1fr minmax(280px, 1.1fr);
  margin: 16px 18px 0;
  border: 1px solid #d6e0e9;
  border-radius: 8px;
}

.snapshot-section {
  min-width: 0;
  padding: 17px;
}

.snapshot-section + .snapshot-section {
  border-left: 1px solid #d6e0e9;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 13px;
}

.section-heading span {
  color: #6b7f92;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.section-heading h3 {
  margin-top: 1px;
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
  gap: 8px;
  margin-bottom: 15px;
}

.finding-list span {
  padding: 6px 9px;
  border: 1px solid #ef9ca5;
  border-radius: 6px;
  background: #fff7f8;
  color: #b83243;
  font-size: 13px;
  font-weight: 600;
}

.fact-list {
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

.history-list {
  display: grid;
  gap: 10px;
}

.history-row {
  display: grid;
  grid-template-columns: 9px 76px minmax(0, 1fr);
  gap: 8px;
  align-items: baseline;
}

.history-status {
  width: 8px;
  height: 8px;
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
  border-color: #d6e0e9;
}

.pain-section :deep(.compact .figure-stage) {
  height: 190px;
}

.pain-section :deep(.side-label) {
  display: none;
}

.pain-empty {
  display: flex;
  min-height: 205px;
  align-items: center;
  justify-content: center;
  gap: 20px;
  color: #6b7f92;
}

.pain-empty svg {
  width: 54px;
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
  font-size: 13px;
}

.narrative-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin: 14px 18px 18px;
}

.narrative-panel {
  border: 1px solid #d6e0e9;
  border-radius: 8px;
  background: #fff;
}

.narrative-panel summary {
  display: flex;
  min-height: 68px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 15px;
  cursor: pointer;
  list-style: none;
}

.narrative-panel summary::-webkit-details-marker {
  display: none;
}

.narrative-panel summary span {
  display: grid;
  gap: 2px;
}

.narrative-panel summary small {
  color: #6b7f92;
  font-size: 11px;
  letter-spacing: 0.06em;
}

.narrative-panel summary strong {
  font-size: 16px;
}

.narrative-panel summary em {
  color: #2568b2;
  font-size: 12px;
  font-style: normal;
  font-weight: 600;
}

.narrative-panel > p {
  padding: 0 15px 15px;
  border-top: 1px solid #e2e9ef;
  color: #40576b;
  line-height: 1.75;
  padding-top: 14px;
  white-space: pre-wrap;
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
  }

  .patient-identity {
    padding: 17px 15px;
  }

  .identity-meta {
    display: grid;
    gap: 7px;
  }

  .identity-meta > div {
    display: grid;
    gap: 1px;
  }

  .identity-meta .complaint {
    grid-template-columns: 1fr;
    gap: 4px;
    margin-top: 5px;
    padding: 11px 12px;
  }

  .emr-summary-heading {
    align-items: flex-start;
    padding: 11px 12px 9px;
  }

  .emr-summary-heading > strong {
    display: none;
  }

  .emr-summary > p {
    padding: 12px;
    font-size: 14px;
    line-height: 1.7;
  }

  .red-flag-banner,
  .patient-summary-report,
  .snapshot-grid,
  .narrative-grid {
    margin-right: 12px;
    margin-left: 12px;
  }

  .snapshot-grid,
  .narrative-grid {
    grid-template-columns: 1fr;
  }

  .snapshot-section + .snapshot-section {
    border-top: 1px solid #d6e0e9;
    border-left: 0;
  }

  .pain-section {
    grid-column: auto;
  }

}
</style>
