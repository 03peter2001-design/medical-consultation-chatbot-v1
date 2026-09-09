<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'

import {
  areAllSummaryRowsConfirmed,
  buildFhirCompositionRequest,
  canSubmitFhirComposition,
  confirmEditableSummaryRow,
  createEditableSummaryRows,
  updateEditableSummaryRow,
} from '../services/physicianSummary.js'
import { api } from '../services/doctorBackend.js'
import FhirSubmissionDialog from './FhirSubmissionDialog.vue'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  report: { type: String, default: '' },
  record: { type: Object, required: true },
  canWriteFhir: { type: Boolean, default: false },
})

const summarySection = ref(null)
const editableRows = ref([])
const previewError = ref('')
const dialogOpen = ref(false)
const submitting = ref(false)
const submissionResult = ref(props.record.fhir_submission || null)
const confirmedCount = computed(
  () => editableRows.value.filter((row) => row.confirmed).length,
)
const allRowsConfirmed = computed(
  () => areAllSummaryRowsConfirmed(editableRows.value),
)
const hasFhirContext = computed(
  () => Boolean(props.record.fhir_context?.patient_id),
)
const alreadySubmitted = computed(() => Boolean(submissionResult.value))
const canOpenSubmission = computed(
  () => canSubmitFhirComposition({
    rows: editableRows.value,
    hasFhirContext: hasFhirContext.value,
    hasPermission: props.canWriteFhir,
    alreadySubmitted: alreadySubmitted.value,
    submitting: submitting.value,
  }),
)

function resizeTextarea(textarea) {
  if (!textarea) return
  textarea.style.height = 'auto'
  textarea.style.height = `${textarea.scrollHeight}px`
}

function resizeSummaryInputs() {
  nextTick(() => {
    summarySection.value
      ?.querySelectorAll('.summary-editor')
      .forEach(resizeTextarea)
  })
}

function handleSummaryInput(row, event) {
  updateEditableSummaryRow(row, event.target.value)
  resizeTextarea(event.target)
}

function confirmRow(row) {
  confirmEditableSummaryRow(row)
}

function openFhirSubmissionDialog() {
  previewError.value = ''
  if (!allRowsConfirmed.value) {
    previewError.value = '請先確認所有醫師摘要欄位，再送出資料。'
    return
  }
  if (!props.canWriteFhir) {
    previewError.value = '目前醫師工作階段沒有 FHIR 寫入權限。'
    return
  }
  if (!hasFhirContext.value) {
    previewError.value = '此病例沒有 FHIR Patient 綁定，無法送出。'
    return
  }
  if (alreadySubmitted.value) return
  dialogOpen.value = true
}

async function submitFhirComposition() {
  if (!canOpenSubmission.value) {
    if (!props.canWriteFhir) {
      previewError.value = '目前醫師工作階段沒有 FHIR 寫入權限。'
    } else if (!hasFhirContext.value) {
      previewError.value = '此病例沒有 FHIR Patient 綁定，無法送出。'
    } else if (!alreadySubmitted.value && !allRowsConfirmed.value) {
      previewError.value = '請先確認所有醫師摘要欄位，再送出資料。'
    }
    return
  }
  previewError.value = ''
  submitting.value = true
  try {
    const payload = buildFhirCompositionRequest(
      editableRows.value,
      props.record.updated_at,
    )
    submissionResult.value = await api.createFhirComposition(
      props.record.consultation_id,
      payload,
    )
    dialogOpen.value = false
  } catch (error) {
    previewError.value = error.message || 'FHIR 寫入失敗，請稍後再試。'
  } finally {
    submitting.value = false
  }
}

watch(
  () => props.rows,
  (rows) => {
    editableRows.value = createEditableSummaryRows(rows)
    submissionResult.value = props.record.fhir_submission || null
    dialogOpen.value = false
    previewError.value = ''
    resizeSummaryInputs()
  },
  { deep: true, immediate: true },
)

onMounted(() => {
  resizeSummaryInputs()
  window.addEventListener('resize', resizeSummaryInputs)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeSummaryInputs)
})
</script>

<template>
  <section ref="summarySection" aria-labelledby="physician-summary-title">
    <header>
      <div>
        <span>CLINICIAN NOTE</span>
        <h3 id="physician-summary-title">醫師摘要</h3>
      </div>
      <strong :class="{ confirmed: allRowsConfirmed }">
        <template v-if="allRowsConfirmed">All columns are reviewed</template>
        <template v-else>
          Draft · {{ confirmedCount }}/{{ editableRows.length }} Confirmed
        </template>
      </strong>
    </header>
    <dl class="physician-summary-rows">
      <div v-for="(row, index) in editableRows" :key="row.key">
        <dt>
          <b>{{ row.key }}</b>
          <span>{{ row.label }}</span>
        </dt>
        <dd>
          <label class="visually-hidden" :for="`summary-${index}`">
            編輯{{ row.label || row.key }}
          </label>
          <textarea
            :id="`summary-${index}`"
            class="summary-editor"
            :value="row.value"
            rows="1"
            :disabled="alreadySubmitted"
            @input="handleSummaryInput(row, $event)"
          />
          <small v-if="row.value !== row.originalValue" class="edit-hint">
            已由醫師修改；尚未寫入後端或 FHIR
          </small>
        </dd>
        <div class="row-review">
          <span v-if="row.confirmed" class="row-confirmed">✓ Confirmed</span>
          <button
            v-else
            type="button"
            class="confirm-button"
            :disabled="!row.value.trim()"
            :aria-label="`確認${row.label || row.key}`"
            @click="confirmRow(row)"
          >
            確認
          </button>
        </div>
      </div>
    </dl>
    <details class="ai-overview">
      <summary>
        <span>
          <small>AI-generated medical records</small>
          <strong>AI 合成病歷</strong>
        </span>
        <em>展開</em>
      </summary>
      <div class="ai-overview-content">
        <dl>
          <div v-for="row in editableRows" :key="row.key">
            <dt>{{ row.key }}</dt>
            <dd>{{ row.value }}</dd>
          </div>
        </dl>
        <div class="fhir-action">
          <div>
            <strong>FHIR 病歷送出</strong>
            <small id="fhir-preview-description">
              <template v-if="alreadySubmitted">
                已儲存為 Composition/{{ submissionResult.resource_id }}
              </template>
              <template v-else-if="!canWriteFhir">
                目前醫師工作階段沒有 FHIR 寫入權限
              </template>
              <template v-else-if="!hasFhirContext">
                此病例沒有 FHIR Patient 綁定
              </template>
              <template v-else-if="allRowsConfirmed">
                點擊後先核對病人與病歷內容，再確認送出
              </template>
              <template v-else>
                請先確認全部 {{ editableRows.length }} 個摘要欄位
              </template>
            </small>
          </div>
          <button
            type="button"
            aria-describedby="fhir-preview-description"
            :disabled="!canOpenSubmission"
            @click="openFhirSubmissionDialog"
          >
            {{ alreadySubmitted ? '已儲存至 FHIR' : '送出並儲存至 FHIR' }}
          </button>
        </div>
        <p
          v-if="previewError"
          class="preview-error"
          role="alert"
        >
          {{ previewError }}
        </p>
      </div>
    </details>
    <FhirSubmissionDialog
      v-if="dialogOpen"
      :record="record"
      :rows="editableRows"
      :submitting="submitting"
      :error="previewError"
      @close="dialogOpen = false"
      @submit="submitFhirComposition"
    />
  </section>
</template>

<style scoped>
section {
  overflow: hidden;
  border: 1px solid #cbd7e1;
  border-radius: 7px;
  background: #fff;
}

section > header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 16px;
  border-bottom: 1px solid #dbe4ec;
}

section > header span,
section > header > strong {
  color: #6b7f92;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
}

section > header h3 {
  color: #17324d;
  font-size: 18px;
}

section > header > strong {
  color: #b83243;
  font-family: 'Noto Sans TC', system-ui, sans-serif;
  letter-spacing: 0;
}

section > header > strong.confirmed {
  color: #087f6d;
}

.physician-summary-rows > div {
  display: grid;
  min-width: 0;
  grid-template-columns: 112px minmax(0, 1fr) auto;
  align-items: start;
  gap: 12px;
  padding: 11px 16px;
  border-bottom: 1px solid #e2e9ef;
}

.physician-summary-rows dt {
  display: grid;
  align-content: start;
  gap: 8px;
}

.physician-summary-rows dt b {
  color: #2568b2;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.physician-summary-rows dt span,
.physician-summary-rows small {
  color: #6b7f92;
  font-size: 11px;
}

.physician-summary-rows dd {
  display: grid;
  min-width: 0;
  gap: 5px;
  color: #2b4256;
  font-size: 14px;
  line-height: 1.65;
}

.summary-editor {
  box-sizing: border-box;
  width: 100%;
  min-height: 44px;
  resize: vertical;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: #2b4256;
  font: inherit;
  line-height: 1.65;
  overflow-y: hidden;
  overflow-wrap: anywhere;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    box-shadow 0.18s ease;
}

.summary-editor:hover {
  border-color: #cbd7e1;
  background: #f8fafc;
}

.summary-editor:focus {
  border-color: #4b88c6;
  outline: 0;
  background: #fff;
  box-shadow: 0 0 0 3px rgb(37 104 178 / 12%);
}

.edit-hint {
  color: #9c6220 !important;
  font-size: 10px !important;
}

.row-review {
  display: flex;
  min-width: 96px;
  justify-content: flex-end;
}

.confirm-button,
.fhir-action button {
  border: 1px solid #2568b2;
  border-radius: 5px;
  background: #2568b2;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.confirm-button {
  min-width: 72px;
  min-height: 34px;
  padding: 6px 12px;
}

.confirm-button:hover {
  border-color: #1e5795;
  background: #1e5795;
}

.confirm-button:disabled {
  border-color: #cbd7e1;
  background: #e8eef3;
  color: #718598;
  cursor: not-allowed;
}

.row-confirmed {
  padding: 7px 0;
  color: #087f6d;
  font-size: 11px;
  font-weight: 750;
  white-space: nowrap;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

.ai-overview summary {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 16px;
  cursor: pointer;
  list-style: none;
}

.ai-overview summary::-webkit-details-marker {
  display: none;
}

.ai-overview summary span {
  display: grid;
  gap: 1px;
}

.ai-overview summary small {
  color: #6b7f92;
  font-size: 10px;
  letter-spacing: 0.05em;
}

.ai-overview summary strong {
  color: #2b4256;
  font-size: 14px;
}

.ai-overview summary em {
  color: #2568b2;
  font-size: 12px;
  font-style: normal;
  font-weight: 650;
}

.ai-overview[open] summary {
  border-bottom: 1px solid #e2e9ef;
}

.ai-overview[open] summary em {
  font-size: 0;
}

.ai-overview[open] summary em::after {
  content: '收合';
  font-size: 12px;
}

.ai-overview-content {
  padding: 13px 16px;
  color: #40576b;
}

.ai-overview-content dl {
  display: grid;
  gap: 14px;
}

.ai-overview-content dl > div {
  display: grid;
  gap: 3px;
}

.ai-overview-content dt {
  color: #2568b2;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 750;
}

.ai-overview-content dd {
  color: #40576b;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.fhir-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid #e2e9ef;
}

.fhir-action > div {
  display: grid;
  gap: 2px;
}

.fhir-action strong {
  color: #2b4256;
  font-size: 13px;
}

.fhir-action small {
  color: #6b7f92;
  font-size: 11px;
}

.fhir-action button {
  min-height: 38px;
  padding: 8px 14px;
}
.fhir-action button:hover {
  border-color: #1e5795;
  background: #1e5795;
}

.fhir-action button:disabled,
.fhir-action button:disabled:hover {
  border-color: #9eb0bf;
  background: #f4f7f9;
  color: #607487;
  cursor: not-allowed;
}

.preview-error {
  margin-top: 8px;
  color: #b83243;
  font-size: 12px;
}

@media (max-width: 700px) {
  section > header {
    display: grid;
    align-items: start;
  }

  .physician-summary-rows > div {
    grid-template-columns: 80px minmax(0, 1fr);
    padding: 11px 12px;
  }

  .row-review {
    grid-column: 2;
    justify-content: flex-start;
  }

  .ai-overview summary {
    padding: 11px 12px;
  }

  .ai-overview-content {
    padding: 13px 12px;
  }

  .fhir-action {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
