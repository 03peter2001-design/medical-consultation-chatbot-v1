<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import { RouterLink } from 'vue-router'

import AppHeader from '../components/AppHeader.vue'
import ChatMessage from '../components/ChatMessage.vue'
import ConsultationBrowser from '../components/ConsultationBrowser.vue'
import PatientRecordCard from '../components/PatientRecordCard.vue'
import StructuredReport from '../components/StructuredReport.vue'
import TypingIndicator from '../components/TypingIndicator.vue'
import { api, backendUrl, connectionError } from '../services/backend.js'

const sessionId = `dr_${Date.now()}`
const casePageSize = 30
const suggestions = [
  '胸痛合併冒冷汗要優先排除什麼？',
  'Thunderclap headache 的鑑別診斷？',
  'D-dimer 在肺栓塞的檢驗意義',
  '顳動脈炎（GCA）的診斷標準',
]

const chatbox = ref(null)
const textInput = ref(null)
const queueInput = ref('')
const input = ref('')
const items = ref([])
const loadedPatient = ref(null)
const structuredMode = ref(false)
const isSending = ref(false)
const isLoadingPatient = ref(false)
const typing = ref(false)
const healthState = ref('checking')
const connectionText = ref('檢查後端連線中...')
const preservePatientTop = ref(false)
const caseSearch = ref('')
const caseRecords = ref([])
const caseTotal = ref(0)
const isLoadingCases = ref(false)
const caseListError = ref('')
const deletingQueueNumber = ref('')
const mobileWorkspaceTab = ref('cases')
let caseSearchTimer = null
let caseRequestVersion = 0

const canChat = computed(
  () => healthState.value === 'online' && !isSending.value,
)
const placeholder = computed(() =>
  structuredMode.value
    ? '貼上新的口語補充主訴，例如：剛剛家屬補充說阿伯這兩天有黑便...'
    : '輸入臨床問題，Enter 送出、Shift+Enter 換行...',
)
const modeHint = computed(() =>
  structuredMode.value
    ? '下一則訊息會針對這段補充資訊，再產生一次新的六段式分析'
    : '',
)
const patientType = computed(() => typeLabel(loadedPatient.value?.type))
const hasMoreCases = computed(
  () => caseRecords.value.length < caseTotal.value,
)

watch(
  typing,
  async () => {
    await nextTick()
    if (preservePatientTop.value) {
      if (chatbox.value) chatbox.value.scrollTop = 0
      return
    }
    if (chatbox.value) {
      chatbox.value.scrollTop = chatbox.value.scrollHeight
    }
  },
)

watch(caseSearch, () => {
  window.clearTimeout(caseSearchTimer)
  caseSearchTimer = window.setTimeout(() => {
    void fetchConsultations({ reset: true })
  }, 250)
})

function nextId() {
  return `${Date.now()}_${items.value.length}`
}

function pushMessage(role, text, sources = []) {
  items.value.push({
    id: nextId(),
    kind: 'message',
    role,
    text,
    sources,
  })
}

function pushStructured(text, sources = []) {
  items.value.push({
    id: nextId(),
    kind: 'structured',
    text,
    sources,
  })
}

function focusInput() {
  nextTick(() => textInput.value?.focus())
}

function typeLabel(type) {
  return (
    {
      chest: '胸痛',
      headache: '頭痛',
      abdomen: '腹痛',
      other: '其他',
    }[type] || type || '未分類'
  )
}

function summaryUnavailableMessage(record) {
  if (record.workflow_status === 'summary_pending') {
    return '病例編號已建立，AI 摘要正在背景產生，請稍後重新載入。'
  }
  if (record.workflow_status === 'summary_failed') {
    const detail = record.summary_error ? `（${record.summary_error}）` : ''
    return `AI 摘要產生失敗，可稍後重試。${detail}`
  }
  if (record.workflow_status === 'summary_partial') {
    return '一般 AI 摘要已完成，但六段式 RAG 分析未完整產生，可使用手動再次分析。'
  }
  if (record.rag_enabled === false) {
    return '病例送出時 RAG 向量庫尚未啟用，因此沒有預先產生結構化分析。'
  }
  return '這筆病例尚無預先產生的結構化分析，可使用下方「手動再次分析」功能。'
}

async function fetchConsultations({ reset = true } = {}) {
  if (!reset && isLoadingCases.value) return
  const requestVersion = ++caseRequestVersion
  isLoadingCases.value = true
  caseListError.value = ''
  const offset = reset ? 0 : caseRecords.value.length

  try {
    const result = await api.listConsultations({
      search: caseSearch.value,
      limit: casePageSize,
      offset,
    })
    if (requestVersion !== caseRequestVersion) return
    caseRecords.value = reset
      ? result.items
      : [...caseRecords.value, ...result.items]
    caseTotal.value = result.total
  } catch (error) {
    if (requestVersion !== caseRequestVersion) return
    caseListError.value = error.message
    if (reset) {
      caseRecords.value = []
      caseTotal.value = 0
    }
  } finally {
    if (requestVersion === caseRequestVersion) {
      isLoadingCases.value = false
    }
  }
}

function refreshConsultations() {
  void fetchConsultations({ reset: true })
}

async function checkHealth() {
  healthState.value = 'checking'
  connectionText.value = '檢查後端連線中...'
  try {
    const health = await api.health()
    if (health.rag_enabled) {
      healthState.value = 'online'
      connectionText.value = '已連線 · RAG 已啟用'
      focusInput()
    } else {
      healthState.value = 'warning'
      connectionText.value = '已連線，但 RAG 尚未啟用'
    }
  } catch {
    healthState.value = 'offline'
    connectionText.value = `無法連接後端：${backendUrl}`
  }
}

async function loadPatient(queueNumberOverride = '') {
  const queueNumber =
    typeof queueNumberOverride === 'string' && queueNumberOverride
      ? queueNumberOverride.trim()
      : queueInput.value.trim()
  if (!queueNumber || isLoadingPatient.value) return

  textInput.value?.blur()
  isLoadingPatient.value = true
  preservePatientTop.value = true
  try {
    const record = await api.loadPatient(queueNumber, sessionId)
    loadedPatient.value = record
    mobileWorkspaceTab.value = 'record'
    queueInput.value = ''
    items.value = [
      {
        id: nextId(),
        kind: 'patient',
        record,
      },
    ]

    if (record.structured_note) {
      pushStructured(record.structured_note, record.structured_sources)
    } else {
      items.value.push({
        id: nextId(),
        kind: 'unavailable',
        text: summaryUnavailableMessage(record),
      })
    }

    void fetchConsultations({ reset: true })
    await nextTick()
    if (chatbox.value) chatbox.value.scrollTop = 0
  } catch (error) {
    window.alert(`⚠️ ${error.message}\n後端：${backendUrl}`)
  } finally {
    isLoadingPatient.value = false
    await nextTick()
    await new Promise((resolve) => {
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(resolve)
      })
    })
    if (chatbox.value) chatbox.value.scrollTop = 0
    preservePatientTop.value = false
  }
}

async function deleteConsultation(record) {
  if (deletingQueueNumber.value) return
  const confirmed = window.confirm(
    `確定要永久刪除 ${record.patient_name}（病例 #${record.queue_number}）嗎？\n\n此操作無法復原。`,
  )
  if (!confirmed) return

  deletingQueueNumber.value = record.queue_number
  try {
    await api.deleteConsultation(record.queue_number)
    caseRecords.value = caseRecords.value.filter(
      (item) => item.queue_number !== record.queue_number,
    )
    caseTotal.value = Math.max(0, caseTotal.value - 1)
    if (loadedPatient.value?.queue_number === record.queue_number) {
      loadedPatient.value = null
      items.value = []
      input.value = ''
    }
  } catch (error) {
    window.alert(`⚠️ 刪除病例失敗：${error.message}`)
  } finally {
    deletingQueueNumber.value = ''
  }
}

async function unloadPatient() {
  try {
    await api.unloadPatient(sessionId)
  } catch {
    // The local UI can still be reset if the backend session already expired.
  }
  loadedPatient.value = null
  items.value = []
  mobileWorkspaceTab.value = 'cases'
}

async function clearChat() {
  try {
    await api.clearDoctorSession(sessionId)
  } catch {
    // Clearing the visible conversation remains safe when the backend is offline.
  }
  loadedPatient.value = null
  items.value = []
  input.value = ''
  mobileWorkspaceTab.value = 'cases'
}

function chooseSuggestion(suggestion) {
  input.value = suggestion
  void sendMessage()
}

function autoGrow() {
  if (!textInput.value) return
  textInput.value.style.height = 'auto'
  textInput.value.style.height = `${Math.min(
    textInput.value.scrollHeight,
    120,
  )}px`
}

function handleKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void sendMessage()
  }
}

async function sendMessage() {
  const message = input.value.trim()
  if (!message || !canChat.value) return

  pushMessage('user', message)
  input.value = ''
  nextTick(autoGrow)
  isSending.value = true
  typing.value = true

  try {
    const mode = structuredMode.value ? 'structured_note' : 'chat'
    const data = await api.doctorChat(message, sessionId, mode)
    if (data.mode === 'structured_note') {
      pushStructured(data.reply, data.sources)
    } else {
      pushMessage('ai', data.reply, data.sources)
    }
  } catch (error) {
    pushMessage('ai', `⚠️ ${connectionError(error)}`)
  } finally {
    typing.value = false
    isSending.value = false
    focusInput()
  }
}

onMounted(() => {
  void checkHealth()
  void fetchConsultations({ reset: true })
})

onBeforeUnmount(() => {
  window.clearTimeout(caseSearchTimer)
})
</script>

<template>
  <div class="app-shell doctor-app">
    <AppHeader
      icon=""
      title="醫師端病例與文獻助手"
      subtitle="病例資料庫 / Medscape EM / ID / Lab Medicine"
      :status="connectionText"
      :status-tone="healthState === 'online' ? 'online' : 'idle'"
    >
      <template #icon>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="1.8"
        >
          <path d="M8 4.5h8a2 2 0 0 1 2 2v13H6v-13a2 2 0 0 1 2-2Z" />
          <path d="M9 3h6v3H9zM12 9v6M9 12h6" />
        </svg>
      </template>
      <RouterLink class="nav-link" to="/">← 病患問診端</RouterLink>
      <RouterLink class="nav-link" to="/doctor/rules">規則中心</RouterLink>
      <button class="utility-button clear-button" @click="clearChat">
        清除對話
      </button>
    </AppHeader>

    <section class="patient-bar" aria-label="病人查詢">
      <input
        v-model="queueInput"
        type="text"
        maxlength="16"
        placeholder="輸入問診編號（urgent 3碼／routine 5碼）..."
        :disabled="isLoadingPatient"
        @keydown.enter.prevent="loadPatient()"
      />
      <button
        class="load-patient-button"
        :disabled="isLoadingPatient || !queueInput.trim()"
        @click="loadPatient()"
      >
        {{ isLoadingPatient ? '分析中…' : '載入病人' }}
      </button>
      <div v-if="loadedPatient" class="patient-tag">
        <span>
          👤 病人 {{ loadedPatient.queue_number }}（{{ patientType }}）
        </span>
        <button aria-label="取消載入病人" @click="unloadPatient">✕</button>
      </div>
    </section>

    <nav class="mobile-workspace-tabs" aria-label="醫師端工作區">
      <button
        :class="{ active: mobileWorkspaceTab === 'cases' }"
        :aria-current="mobileWorkspaceTab === 'cases' ? 'page' : undefined"
        @click="mobileWorkspaceTab = 'cases'"
      >
        病例
      </button>
      <button
        :class="{ active: mobileWorkspaceTab === 'record' }"
        :aria-current="mobileWorkspaceTab === 'record' ? 'page' : undefined"
        @click="mobileWorkspaceTab = 'record'"
      >
        分析
      </button>
    </nav>

    <div
      class="doctor-workspace"
      :class="`mobile-${mobileWorkspaceTab}`"
    >
      <ConsultationBrowser
        v-model:search="caseSearch"
        :records="caseRecords"
        :total="caseTotal"
        :loading="isLoadingCases"
        :error="caseListError"
        :deleting-queue-number="deletingQueueNumber"
        :loaded-queue-number="loadedPatient?.queue_number"
        :patient-loading="isLoadingPatient"
        :has-more="hasMoreCases"
        @refresh="refreshConsultations"
        @select="loadPatient"
        @delete="deleteConsultation"
        @load-more="fetchConsultations({ reset: false })"
      />

      <main class="doctor-main">
      <div ref="chatbox" class="messages doctor-messages" aria-live="polite">
        <section v-if="!items.length" class="empty-state">
          <div class="empty-icon">🩻</div>
          <p>
            病人送出問診時，AI 已預先產生六段式結構化病歷分析；
            輸入問診編號即可直接載入
            （EMR病歷 / 初步鑑別診斷 / 防漏診鑑別 / 理學檢查 /
            檢驗建議 / 影像學決策）。<br /><br />
            也可以直接向 AI 提問任何臨床或文獻相關問題，
            回答將根據 Medscape 急診醫學 / 感染科 /
            檢驗醫學文獻庫產生，並附上引用來源。
          </p>
          <div class="suggestions">
            <button
              v-for="suggestion in suggestions"
              :key="suggestion"
              :disabled="!canChat"
              @click="chooseSuggestion(suggestion)"
            >
              {{ suggestion }}
            </button>
          </div>
        </section>

        <template v-for="item in items" :key="item.id">
          <ChatMessage
            v-if="item.kind === 'message'"
            :role="item.role"
            :text="item.text"
            :sources="item.sources"
            ai-label="AI 文獻助手"
            user-label="醫師"
          />
          <PatientRecordCard
            v-else-if="item.kind === 'patient'"
            :record="item.record"
          />
          <StructuredReport
            v-else-if="item.kind === 'structured'"
            :text="item.text"
            :sources="item.sources"
          />
          <div v-else-if="item.kind === 'unavailable'" class="unavailable">
            ⚠️ {{ item.text }}
          </div>
        </template>
        <TypingIndicator v-if="typing" label="AI 文獻助手" />
      </div>

      <div class="mode-bar">
        <button
          class="mode-button"
          :class="{ active: structuredMode }"
          @click="structuredMode = !structuredMode"
        >
          <span class="mode-dot" />
          🩺 手動再次分析：{{ structuredMode ? '開啟' : '關閉' }}
        </button>
        <span>{{ modeHint }}</span>
      </div>

      <div class="doctor-input-bar">
        <textarea
          ref="textInput"
          v-model="input"
          rows="1"
          :placeholder="placeholder"
          :disabled="!canChat"
          @input="autoGrow"
          @keydown="handleKeydown"
        />
        <button
          class="doctor-send"
          :disabled="!canChat || !input.trim()"
          aria-label="送出訊息"
          @click="sendMessage"
        >
          ➤
        </button>
      </div>
      <div class="footnote">
        AI 回答僅供臨床參考，不能取代醫師的專業判斷。
      </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.doctor-app {
  --brand-accent: var(--blue);
  --message-accent: var(--blue);
}

.clear-button:hover {
  border-color: var(--danger);
  color: var(--danger);
}

.mobile-workspace-tabs {
  display: none;
}

.patient-bar {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  min-height: 62px;
  padding: 10px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-1);
}

.patient-bar > input {
  width: 310px;
  min-height: 42px;
  padding: 9px 13px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
}

.patient-bar > input:focus {
  border-color: var(--blue);
}

.load-patient-button {
  min-height: 42px;
  padding: 9px 17px;
  border-radius: 6px;
  background: var(--blue);
  color: white;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.load-patient-button:disabled,
.patient-bar > input:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.patient-tag {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 42px;
  padding: 8px 13px;
  border: 1px solid rgb(10 146 126 / 35%);
  border-radius: 6px;
  background: var(--green-soft);
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.patient-tag button {
  background: transparent;
  color: var(--green);
  cursor: pointer;
}

.doctor-workspace {
  display: grid;
  min-height: 0;
  flex: 1;
  grid-template-columns: minmax(300px, 340px) minmax(0, 1fr);
  overflow: hidden;
}

.doctor-main {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg);
}

.doctor-messages {
  width: 100%;
  max-width: 1180px;
  flex: 1;
  gap: 16px;
  margin: 0 auto;
  overflow-anchor: none;
  padding: 24px 28px;
}

.empty-state {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--muted);
  text-align: center;
}

.empty-icon {
  font-size: 40px;
  opacity: 0.3;
}

.empty-state p {
  max-width: 560px;
  font-size: 15px;
  line-height: 1.75;
}

.suggestions {
  display: flex;
  max-width: 680px;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}

.suggestions button {
  min-height: 42px;
  padding: 9px 15px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface-1);
  color: var(--muted);
  cursor: pointer;
  font-size: 14px;
}

.suggestions button:hover:not(:disabled) {
  border-color: var(--blue);
  color: var(--text);
}

.suggestions button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.unavailable {
  align-self: stretch;
  padding: 14px 18px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--surface-1);
  color: var(--muted);
  font-size: 14px;
}

.mode-bar {
  display: flex;
  width: 100%;
  max-width: 1180px;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
  margin: 0 auto;
  padding: 8px 24px 0;
}

.mode-button {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 42px;
  padding: 9px 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface-2);
  color: var(--muted);
  cursor: pointer;
  font-size: 14px;
}

.mode-button.active {
  border-color: var(--green);
  background: var(--green-soft);
  color: var(--green);
}

.mode-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--muted);
}

.mode-button.active .mode-dot {
  background: var(--green);
}

.mode-bar > span {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.doctor-input-bar {
  display: flex;
  width: 100%;
  max-width: 1180px;
  flex: 0 0 auto;
  align-items: flex-end;
  gap: 10px;
  margin: 0 auto;
  padding: 12px 24px 16px;
  border-top: 1px solid var(--border);
  background: var(--surface-1);
}

.doctor-input-bar textarea {
  min-width: 0;
  min-height: 50px;
  max-height: 120px;
  flex: 1;
  resize: none;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text);
  font-size: 15px;
  line-height: 1.55;
}

.doctor-input-bar textarea:focus {
  border-color: var(--blue);
}

.doctor-input-bar textarea:disabled {
  opacity: 0.4;
}

.doctor-send {
  display: grid;
  width: 50px;
  height: 50px;
  flex: 0 0 50px;
  place-items: center;
  border-radius: 8px;
  background: var(--blue);
  color: white;
  cursor: pointer;
  font-size: 17px;
}

.doctor-send:disabled {
  cursor: not-allowed;
  opacity: 0.3;
}

.footnote {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 24px 10px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  text-align: center;
}

@media (max-width: 980px) {
  .doctor-workspace {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(220px, 34dvh) minmax(0, 1fr);
  }

}

@media (max-width: 760px) {
  .patient-bar {
    flex-wrap: wrap;
    padding: 10px 12px;
  }

  .patient-bar > input {
    min-width: 0;
    flex: 1;
  }

  .patient-tag {
    order: 3;
    width: 100%;
    justify-content: space-between;
  }

  .mobile-workspace-tabs {
    display: grid;
    flex: 0 0 auto;
    grid-template-columns: 1fr 1fr;
    gap: 4px;
    margin: 10px 12px 0;
    padding: 4px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface-1);
  }

  .mobile-workspace-tabs button {
    min-height: 44px;
    border-radius: 7px;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-size: 15px;
    font-weight: 600;
  }

  .mobile-workspace-tabs button.active {
    background: var(--blue);
    color: white;
  }

  .doctor-workspace {
    display: block;
    min-height: 0;
  }

  .doctor-workspace.mobile-record .case-browser,
  .doctor-workspace.mobile-cases .doctor-main {
    display: none;
  }

  .case-browser,
  .doctor-main {
    height: 100%;
  }

  .doctor-messages {
    padding: 16px 12px;
  }

  .mode-bar {
    align-items: flex-start;
    padding: 8px 12px 0;
  }

  .mode-bar > span {
    display: none;
  }

  .doctor-input-bar {
    padding: 10px 12px;
  }

  .footnote {
    padding: 0 12px 8px;
  }
}
</style>
