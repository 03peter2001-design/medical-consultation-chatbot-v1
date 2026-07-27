<script setup>
import {
  computed,
  nextTick,
  onMounted,
  ref,
  watch,
} from 'vue'
import { RouterLink } from 'vue-router'

import AppHeader from '../components/AppHeader.vue'
import ChatMessage from '../components/ChatMessage.vue'
import PatientRecordCard from '../components/PatientRecordCard.vue'
import StructuredReport from '../components/StructuredReport.vue'
import TypingIndicator from '../components/TypingIndicator.vue'
import { api, backendUrl, connectionError } from '../services/backend.js'

const sessionId = `dr_${Date.now()}`
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
const patientType = computed(() => {
  if (!loadedPatient.value) return ''
  return (
    {
      chest: '胸痛',
      headache: '頭痛',
      abdomen: '腹痛',
    }[loadedPatient.value.type] || loadedPatient.value.type
  )
})

watch(
  [() => items.value.length, typing],
  async () => {
    const shouldAutoScroll = !preservePatientTop.value
    await nextTick()
    if (chatbox.value && shouldAutoScroll) {
      chatbox.value.scrollTop = chatbox.value.scrollHeight
    }
  },
)

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

async function loadPatient() {
  const queueNumber = queueInput.value.trim()
  if (!queueNumber || isLoadingPatient.value) return

  isLoadingPatient.value = true
  preservePatientTop.value = true
  try {
    const record = await api.loadPatient(queueNumber, sessionId)
    loadedPatient.value = record
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
          text:
            record.rag_enabled === false
            ? 'RAG 向量庫尚未啟用，無法自動產生結構化分析。請先執行 ingest.py 建立知識庫。'
            : '自動產生結構化分析失敗，可切換下方「手動再次分析」模式重新產生。',
      })
    }

    await nextTick()
    if (chatbox.value) chatbox.value.scrollTop = 0
  } catch (error) {
    window.alert(`⚠️ ${error.message}\n後端：${backendUrl}`)
  } finally {
    preservePatientTop.value = false
    isLoadingPatient.value = false
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

onMounted(checkHealth)
</script>

<template>
  <div class="app-shell doctor-app">
    <AppHeader
      icon="📚"
      title="醫師端 RAG 文獻助手"
      subtitle="Medscape EM / ID / Lab Medicine"
      :status="connectionText"
      :status-tone="healthState === 'online' ? 'online' : 'idle'"
    >
      <RouterLink class="nav-link" to="/">← 病患問診端</RouterLink>
      <button class="utility-button clear-button" @click="clearChat">
        清除對話
      </button>
    </AppHeader>

    <section class="patient-bar" aria-label="病人查詢">
      <input
        v-model="queueInput"
        type="text"
        maxlength="16"
        placeholder="輸入問診編號（5碼）查詢病人..."
        :disabled="isLoadingPatient"
        @keydown.enter.prevent="loadPatient"
      />
      <button
        class="load-patient-button"
        :disabled="isLoadingPatient || !queueInput.trim()"
        @click="loadPatient"
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

    <main class="doctor-main">
      <div ref="chatbox" class="messages doctor-messages" aria-live="polite">
        <section v-if="!items.length" class="empty-state">
          <div class="empty-icon">🩻</div>
          <p>
            輸入問診編號載入病人後，AI 會自動產生六段式結構化病歷分析
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

.patient-bar {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-1);
}

.patient-bar > input {
  width: 240px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.patient-bar > input:focus {
  border-color: var(--blue);
}

.load-patient-button {
  padding: 8px 16px;
  border-radius: 6px;
  background: var(--blue);
  color: #001420;
  cursor: pointer;
  font-size: 12px;
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
  padding: 6px 12px;
  border: 1px solid rgb(0 200 150 / 35%);
  border-radius: 6px;
  background: rgb(0 200 150 / 8%);
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.patient-tag button {
  background: transparent;
  color: var(--green);
  cursor: pointer;
}

.doctor-main {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
}

.doctor-messages {
  width: 100%;
  max-width: 900px;
  flex: 1;
  gap: 16px;
  margin: 0 auto;
  padding: 24px;
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
  max-width: 430px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.9;
}

.suggestions {
  display: flex;
  max-width: 540px;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}

.suggestions button {
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface-1);
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
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
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.mode-bar {
  display: flex;
  width: 100%;
  max-width: 900px;
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
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface-2);
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
}

.mode-button.active {
  border-color: var(--green);
  background: rgb(0 200 150 / 12%);
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
  font-size: 11px;
}

.doctor-input-bar {
  display: flex;
  width: 100%;
  max-width: 900px;
  flex: 0 0 auto;
  align-items: flex-end;
  gap: 10px;
  margin: 0 auto;
  padding: 10px 24px 14px;
  border-top: 1px solid var(--border);
  background: var(--surface-1);
}

.doctor-input-bar textarea {
  min-width: 0;
  min-height: 44px;
  max-height: 120px;
  flex: 1;
  resize: none;
  padding: 11px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 14px;
  line-height: 1.5;
}

.doctor-input-bar textarea:focus {
  border-color: var(--blue);
}

.doctor-input-bar textarea:disabled {
  opacity: 0.4;
}

.doctor-send {
  display: grid;
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  place-items: center;
  border-radius: 8px;
  background: var(--blue);
  color: #001420;
  cursor: pointer;
  font-size: 17px;
}

.doctor-send:disabled {
  cursor: not-allowed;
  opacity: 0.3;
}

.footnote {
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
  padding: 0 24px 10px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  text-align: center;
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
