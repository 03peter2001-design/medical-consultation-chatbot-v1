<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  record: { type: Object, required: true },
  rows: { type: Array, required: true },
  submitting: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['close', 'submit'])
const dialogCard = ref(null)
const patient = computed(
  () => props.record.patient_data || props.record.data || {},
)
const context = computed(() => props.record.fhir_context || {})
const patientName = computed(
  () => patient.value.name || props.record.patient_name || '未提供',
)

function requestClose() {
  if (!props.submitting) emit('close')
}

function handleKeydown(event) {
  if (event.key === 'Escape') requestClose()
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
  nextTick(() => dialogCard.value?.focus())
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div class="dialog-backdrop" @click.self="requestClose">
      <section
        ref="dialogCard"
        class="dialog-card"
        tabindex="-1"
        role="dialog"
        aria-modal="true"
        aria-labelledby="fhir-dialog-title"
        aria-describedby="fhir-dialog-description"
      >
        <header>
          <div>
            <small>FHIR COMPOSITION</small>
            <h2 id="fhir-dialog-title">確認送出病歷</h2>
          </div>
          <button
            type="button"
            class="close-button"
            :disabled="submitting"
            aria-label="關閉確認視窗"
            @click="requestClose"
          >
            ×
          </button>
        </header>

        <div class="dialog-content">
          <p id="fhir-dialog-description" class="review-notice">
            請核對病人、就診與七段醫師摘要。送出後將建立
            <code>Composition</code>；目前狀態為
            <code>preliminary</code>，不等同電子簽章。
          </p>

          <section class="patient-review" aria-labelledby="patient-review-title">
            <h3 id="patient-review-title">病人與就診資料</h3>
            <dl>
              <div>
                <dt>姓名</dt>
                <dd>{{ patientName }}</dd>
              </div>
              <div>
                <dt>出生日期</dt>
                <dd>{{ patient.birth_date || '未提供' }}</dd>
              </div>
              <div>
                <dt>性別</dt>
                <dd>{{ patient.gender || '未提供' }}</dd>
              </div>
              <div>
                <dt>問診編號</dt>
                <dd>{{ record.consultation_id }}</dd>
              </div>
              <div>
                <dt>FHIR Patient</dt>
                <dd><code>Patient/{{ context.patient_id }}</code></dd>
              </div>
              <div>
                <dt>FHIR Encounter</dt>
                <dd>
                  <code v-if="context.encounter_id">
                    Encounter/{{ context.encounter_id }}
                  </code>
                  <span v-else>未提供</span>
                </dd>
              </div>
            </dl>
          </section>

          <section class="summary-review" aria-labelledby="summary-review-title">
            <h3 id="summary-review-title">即將寫入的醫師摘要</h3>
            <dl>
              <div v-for="row in rows" :key="row.key">
                <dt>{{ row.key }}<span v-if="row.label"> · {{ row.label }}</span></dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>
          </section>

          <p v-if="error" class="submit-error" role="alert">{{ error }}</p>
        </div>

        <footer>
          <button
            type="button"
            class="secondary-button"
            :disabled="submitting"
            @click="requestClose"
          >
            返回修改
          </button>
          <button
            type="button"
            class="submit-button"
            :disabled="submitting"
            @click="emit('submit')"
          >
            {{ submitting ? '送出中…' : '確認無誤，送出至 FHIR' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop {
  position: fixed;
  z-index: 1000;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(14 34 51 / 58%);
}

.dialog-card {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  width: min(900px, 100%);
  max-height: min(860px, calc(100vh - 48px));
  overflow: hidden;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 24px 70px rgb(7 31 50 / 28%);
}

.dialog-card:focus {
  outline: none;
}

.dialog-card > header,
.dialog-card > footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
}

.dialog-card > header {
  border-bottom: 1px solid #dbe4ec;
}

.dialog-card > header small {
  color: #6b7f92;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
}

.dialog-card h2 {
  margin: 2px 0 0;
  color: #17324d;
  font-size: 21px;
}

.close-button {
  width: 36px;
  height: 36px;
  border: 0;
  background: transparent;
  color: #526b80;
  font-size: 28px;
  cursor: pointer;
}

.dialog-content {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 18px 20px;
  touch-action: pan-y;
  -webkit-overflow-scrolling: touch;
}

.review-notice {
  margin: 0 0 18px;
  padding: 12px 14px;
  border-left: 4px solid #d89a31;
  background: #fff9ed;
  color: #59461f;
  line-height: 1.6;
}

.dialog-content h3 {
  margin: 0 0 10px;
  color: #17324d;
  font-size: 15px;
}

.patient-review dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid #dbe4ec;
  border-radius: 7px;
  background: #dbe4ec;
}

.patient-review dl > div {
  min-width: 0;
  padding: 10px 12px;
  background: #fff;
}

.patient-review dt,
.summary-review dt {
  color: #657b8e;
  font-size: 11px;
  font-weight: 700;
}

.patient-review dd {
  margin-top: 3px;
  overflow-wrap: anywhere;
  color: #263f55;
  font-size: 13px;
}

.summary-review {
  margin-top: 20px;
}

.summary-review dl {
  display: grid;
  gap: 10px;
}

.summary-review dl > div {
  padding: 11px 13px;
  border: 1px solid #dbe4ec;
  border-radius: 7px;
}

.summary-review dt {
  color: #2568b2;
}

.summary-review dt span {
  color: #718598;
  font-weight: 500;
}

.summary-review dd {
  margin-top: 5px;
  color: #2b4256;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.submit-error {
  margin: 14px 0 0;
  color: #b83243;
  font-size: 13px;
}

.dialog-card > footer {
  justify-content: flex-end;
  border-top: 1px solid #dbe4ec;
  background: #f8fafc;
}

.dialog-card > footer button {
  min-height: 40px;
  padding: 8px 15px;
  border-radius: 6px;
  font-weight: 700;
  cursor: pointer;
}

.secondary-button {
  border: 1px solid #9eb0bf;
  background: #fff;
  color: #40576b;
}

.submit-button {
  border: 1px solid #087f6d;
  background: #087f6d;
  color: #fff;
}

.dialog-card button:disabled {
  cursor: wait;
  opacity: 0.65;
}

@media (max-width: 620px) {
  .dialog-backdrop {
    align-items: end;
    padding: 0;
  }

  .dialog-card {
    max-height: 94vh;
    max-height: 94dvh;
    border-radius: 12px 12px 0 0;
  }

  .patient-review dl {
    grid-template-columns: 1fr;
  }

  .dialog-card > footer {
    align-items: stretch;
    flex-direction: column-reverse;
  }
}
</style>
