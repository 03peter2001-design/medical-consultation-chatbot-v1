<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
} from 'vue'
import { RouterLink } from 'vue-router'

import AppHeader from '../components/AppHeader.vue'
import AmieTracePanel from '../components/AmieTracePanel.vue'
import AvatarSettings from '../components/AvatarSettings.vue'
import ChatMessage from '../components/ChatMessage.vue'
import PainLocationInput from '../components/PainLocationInput.vue'
import QuestionnaireControl from '../components/QuestionnaireControl.vue'
import QueueCard from '../components/QueueCard.vue'
import StartConsultationOverlay from '../components/StartConsultationOverlay.vue'
import TypingIndicator from '../components/TypingIndicator.vue'
import { useAvatar } from '../composables/useAvatar.js'
import { getPainMapPreset } from '../data/bodyPainRegions.js'
import { api, connectionError } from '../services/backend.js'
import {
  buildPatientPrefill,
  directFhirEnabled,
  fhirBaseUrl,
  isNationalIdFormat,
  loadPatientByNationalId,
  normalizeNationalId,
  patientDisplayName,
} from '../services/fhir.js'
const sessionId = `pt_${Date.now()}`
const maxBirthDate = new Date().toISOString().slice(0, 10)

const avatar = useAvatar()
const messages = ref([])
const amieTraces = ref([])
const queueNumber = ref('')
const input = ref('')
const started = ref(false)
const starting = ref(false)
const sending = ref(false)
const completed = ref(false)
const typing = ref(false)
const startError = ref('')
const overlayVisible = ref(true)
const nationalId = ref('A000000000')
const fhirPatient = ref(null)
const fhirResourceCount = ref(0)
const clientKey = ref('')
const agentId = ref('')
const mobileAvatarOpen = ref(false)
const selectedPainLocationIds = ref([])
const questionInput = ref(null)
const questionnaireInfo = ref(null)
const progressState = ref({ current: 0, total: 1, percent: 0 })
const triageState = ref({
  level: 'routine',
  message: '',
  possible_conditions: [],
})
const recording = ref(false)
const voiceProcessing = ref(false)
const chatbox = ref(null)
const textInput = ref(null)
const questionnaireControl = ref(null)

let mediaRecorder = null
let mediaStream = null
let audioChunks = []

const progress = computed(() => progressState.value.percent ?? 0)
const progressLabel = computed(() =>
  progress.value >= 100 ? '完成 ✓' : `${progress.value}%`,
)
const inputsDisabled = computed(
  () =>
    !started.value ||
    starting.value ||
    sending.value ||
    voiceProcessing.value ||
    completed.value,
)
const microphoneLabel = computed(() => {
  if (voiceProcessing.value) return '⏳'
  if (recording.value) return '⏹️'
  return '🎤'
})
const showBodyMap = computed(
  () =>
    started.value &&
    (questionInput.value?.base_field ?? questionInput.value?.field) ===
      'location' &&
    questionnaireInfo.value?.section === 'disease' &&
    !completed.value,
)
const currentInputKind = computed(
  () => questionInput.value?.kind ?? 'text',
)
const nationalIdValid = computed(() =>
  isNationalIdFormat(nationalId.value),
)
const loadedPatientName = computed(() =>
  fhirPatient.value ? patientDisplayName(fhirPatient.value) : '',
)
const painMapPreset = computed(() =>
  getPainMapPreset(questionnaireInfo.value?.route),
)
const urgentConditions = computed(() =>
  Array.isArray(triageState.value?.possible_conditions)
    ? triageState.value.possible_conditions.filter(
        (condition) => typeof condition === 'string' && condition.trim(),
      )
    : [],
)

watch(
  [() => messages.value.length, typing, queueNumber],
  async () => {
    await nextTick()
    if (chatbox.value) {
      chatbox.value.scrollTop = chatbox.value.scrollHeight
    }
  },
)

function focusInput() {
  nextTick(() => {
    if (currentInputKind.value !== 'text') {
      questionnaireControl.value?.focus()
    } else {
      textInput.value?.focus()
    }
  })
}

function addMessage(role, text) {
  if (!text) return
  messages.value.push({
    id: `${Date.now()}_${messages.value.length}`,
    role,
    text,
  })
}

function setQuestionState(data) {
  questionInput.value = data.question_input ?? null
  questionnaireInfo.value = data.questionnaire ?? null
  progressState.value =
    data.progress ?? progressState.value
  triageState.value =
    data.triage ?? triageState.value
  input.value = ''
}

async function initializeBackendSession(patientRecord = null) {
  return api.patientChat(
    '',
    sessionId,
    [],
    patientRecord ? buildPatientPrefill(patientRecord) : null,
  )
}

async function startConsultation({ skipFhir = false } = {}) {
  if (started.value || starting.value) return
  starting.value = true
  startError.value = ''
  let startStage =
    directFhirEnabled && !skipFhir ? 'fhir' : 'backend'

  try {
    let patient = null
    let patientRecord = null
    if (directFhirEnabled && !skipFhir) {
      nationalId.value = normalizeNationalId(nationalId.value)
      const record = await loadPatientByNationalId(nationalId.value, {
        baseUrl: fhirBaseUrl,
      })
      patient = record.patient
      patientRecord = record
      fhirPatient.value = patient
      fhirResourceCount.value = record.resources.length
      startStage = 'backend'
    }

    const data = await initializeBackendSession(patientRecord)
    started.value = true
    overlayVisible.value = false
    setQuestionState(data)
    if (patient) {
      addMessage(
        'ai',
        `已從測試 HAPI 載入 ${patientDisplayName(patient)}（Patient/${patient.id}），共 ${fhirResourceCount.value} 筆相關 FHIR Resources。已帶入基本資料；只有病歷未提供的病史欄位會再詢問。`,
      )
    }
    addMessage('ai', data.reply)
    void avatar.speak(data.reply)
    focusInput()
  } catch (error) {
    startError.value =
      startStage === 'fhir'
        ? `無法從測試 HAPI 載入病人（${error.message}）。\n嘗試連線：${fhirBaseUrl}`
        : connectionError(error)
  } finally {
    starting.value = false
  }
}

function handleResponse(data, rawFallback) {
  addMessage('user', data.user_display ?? rawFallback)
  if (data.amie_debug) {
    amieTraces.value.push(data.amie_debug)
  }
  setQuestionState(data)

  if (data.completed) {
    if (data.queue_number) {
      queueNumber.value = data.queue_number
    } else {
      addMessage('ai', data.reply)
    }
    completed.value = true
  } else {
    addMessage('ai', data.reply)
    focusInput()
  }

  void avatar.speak(data.reply)
}

async function submitMessage(
  message = input.value,
  painLocationIds = [],
) {
  const text = message.trim()
  if (!text || inputsDisabled.value) return

  sending.value = true
  typing.value = true
  try {
    const data = await api.patientChat(text, sessionId, painLocationIds)
    handleResponse(data, text)
    selectedPainLocationIds.value = []
  } catch (error) {
    addMessage('ai', `⚠️ ${connectionError(error)}`)
  } finally {
    typing.value = false
    sending.value = false
    if (!completed.value) focusInput()
  }
}

function handleInputKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void submitMessage()
  }
}

async function connectAvatar() {
  const connected = await avatar.connect({
    clientKey: clientKey.value,
    agentId: agentId.value,
  })
  if (connected) mobileAvatarOpen.value = false
}

async function toggleVoice() {
  if (completed.value || voiceProcessing.value) return
  if (recording.value) {
    mediaRecorder?.stop()
    return
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true,
      },
    })
    const preferredType = 'audio/webm;codecs=opus'
    const options =
      window.MediaRecorder?.isTypeSupported?.(preferredType)
        ? { mimeType: preferredType }
        : undefined
    mediaRecorder = new MediaRecorder(mediaStream, options)
    audioChunks = []
    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) audioChunks.push(event.data)
    }
    mediaRecorder.onstop = processRecording
    mediaRecorder.start()
    recording.value = true
  } catch (error) {
    addMessage('ai', `⚠️ 無法存取麥克風：${error.message}`)
  }
}

async function processRecording() {
  recording.value = false
  mediaStream?.getTracks().forEach((track) => track.stop())
  mediaStream = null
  voiceProcessing.value = true

  try {
    const audioBlob = new Blob(audioChunks, {
      type: mediaRecorder?.mimeType || 'audio/webm',
    })
    const transcript = await api.transcribe(audioBlob)
    const text = transcript.text?.trim()
    if (!text) {
      addMessage('ai', '⚠️ 未偵測到語音內容，請再試一次。')
      return
    }
    voiceProcessing.value = false
    await submitMessage(text)
  } catch (error) {
    addMessage('ai', `⚠️ 語音辨識失敗（${error.message}），請重試。`)
  } finally {
    voiceProcessing.value = false
    audioChunks = []
    mediaRecorder = null
  }
}

onBeforeUnmount(() => {
  if (mediaRecorder?.state === 'recording') mediaRecorder.stop()
  mediaStream?.getTracks().forEach((track) => track.stop())
})
</script>

<template>
  <div
    class="app-shell patient-app"
    :class="{ 'drawer-open': mobileAvatarOpen }"
  >
    <StartConsultationOverlay
      v-model:national-id="nationalId"
      :visible="overlayVisible"
      :direct-fhir-enabled="directFhirEnabled"
      :fhir-base-url="fhirBaseUrl"
      :national-id-valid="nationalIdValid"
      :starting="starting"
      :error="startError"
      @start="startConsultation"
    />

    <AppHeader
      icon="🩺"
      title="AI 預問診系統"
      :status="completed ? '問診完成' : avatar.headerStatus.value"
      :status-tone="completed ? 'online' : avatar.headerTone.value"
    >
      <button
        class="utility-button avatar-toggle"
        type="button"
        aria-controls="avatar-settings"
        :aria-expanded="mobileAvatarOpen"
        @click="mobileAvatarOpen = !mobileAvatarOpen"
      >
        Avatar
      </button>
      <RouterLink class="nav-link" to="/doctor">醫師端 →</RouterLink>
    </AppHeader>

    <AvatarSettings
      v-model:client-key="clientKey"
      v-model:agent-id="agentId"
      :avatar="avatar"
      :open="mobileAvatarOpen"
      @close="mobileAvatarOpen = false"
      @connect="connectAvatar"
    />

    <main class="patient-layout">
      <section class="consultation-panel">
        <div v-if="fhirPatient" class="patient-context-bar">
          <span class="context-status">FHIR 已載入</span>
          <strong>{{ loadedPatientName }}</strong>
          <span>Patient/{{ fhirPatient.id }}</span>
          <span>{{ fhirResourceCount }} 筆 Resources</span>
        </div>
        <div
          v-if="triageState.level === 'urgent'"
          class="urgent-care-banner"
          role="alert"
          aria-live="assertive"
        >
          <div class="urgent-care-heading">
            <span class="urgent-care-icon" aria-hidden="true">!</span>
            <div>
              <strong>安全警示：問診已中斷</strong>
              <p>{{ triageState.message }}</p>
            </div>
          </div>
          <div
            v-if="urgentConditions.length"
            class="urgent-condition-alert"
          >
            <span>可能涉及的緊急疾病</span>
            <strong>{{ urgentConditions.join('、') }}</strong>
          </div>
          <p class="urgent-care-disclaimer">
            以上僅為安全規則提示，不代表診斷；請勿等待線上問診結果。
          </p>
        </div>
        <div class="progress-bar" aria-label="問診進度">
          <span
            v-if="questionnaireInfo"
            class="questionnaire-badge"
          >
            {{ questionnaireInfo.label }}
            <template v-if="questionnaireInfo.route_label">
              · {{ questionnaireInfo.route_label }}
            </template>
          </span>
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: `${progress}%` }" />
          </div>
          <span class="progress-label">
            {{ progressState.current }}/{{ progressState.total }}
            · {{ progressLabel }}
          </span>
        </div>

        <div ref="chatbox" class="messages patient-messages" aria-live="polite">
          <ChatMessage
            v-for="message in messages"
            :key="message.id"
            :role="message.role"
            :text="message.text"
          />
          <QueueCard
            v-if="queueNumber"
            :queue-number="queueNumber"
            :triage-level="triageState.level"
          />
          <AmieTracePanel :traces="amieTraces" />
          <PainLocationInput
            v-if="showBodyMap"
            v-model="selectedPainLocationIds"
            :preset="painMapPreset"
            :sending="sending"
            @submit="submitMessage"
          />
          <QuestionnaireControl
            v-if="!completed && currentInputKind !== 'text'"
            ref="questionnaireControl"
            :spec="questionInput"
            :disabled="inputsDisabled"
            :sending="sending"
            :max-birth-date="maxBirthDate"
            @submit="submitMessage"
          />
          <TypingIndicator v-if="typing" />
        </div>

        <div
          v-if="!completed && currentInputKind === 'text'"
          class="patient-input-bar"
        >
          <input
            ref="textInput"
            v-model="input"
            type="text"
            :placeholder="
              questionInput?.placeholder || '請輸入您的回覆...'
            "
            :disabled="inputsDisabled"
            @keydown="handleInputKeydown"
          />
          <button
            class="input-icon"
            :class="{ recording }"
            :disabled="inputsDisabled && !recording"
            :aria-label="recording ? '停止錄音' : '開始語音輸入'"
            @click="toggleVoice"
          >
            {{ microphoneLabel }}
          </button>
          <button
            class="input-icon send"
            aria-label="送出訊息"
            :disabled="inputsDisabled || !input.trim()"
            @click="submitMessage()"
          >
            ➤
          </button>
        </div>
        <div
          v-else-if="!completed"
          class="structured-input-hint"
        >
          {{
            currentInputKind === 'duration'
              ? '請在上方選擇快捷時間，或輸入時間長度與單位。'
              : '請在上方選擇答案；找不到合適選項時可使用「其他／補充說明」。'
          }}
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.patient-app {
  --brand-accent: var(--green);
  --message-accent: var(--green);
}

.patient-layout {
  display: flex;
  flex: 1;
  min-height: 0;
}

.consultation-panel {
  display: flex;
  width: min(1120px, calc(100% - 40px));
  max-width: 1120px;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  margin: 20px auto;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-1);
  box-shadow: 0 12px 32px rgb(37 67 91 / 8%);
}

.patient-context-bar {
  display: flex;
  min-height: 46px;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  padding: 9px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--green-soft);
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.patient-context-bar strong {
  color: var(--text);
  font-family: 'Noto Sans TC', sans-serif;
  font-size: 14px;
}

.context-status {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgb(10 146 126 / 12%);
  color: var(--green);
}

.urgent-care-banner {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: 10px;
  padding: 16px 20px;
  border-bottom: 1px solid rgb(180 35 53 / 34%);
  background: #fff0f1;
  color: #6f1622;
  font-size: 14px;
  line-height: 1.5;
}

.urgent-care-heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.urgent-care-heading > div {
  min-width: 0;
}

.urgent-care-heading strong {
  display: block;
  color: #a41624;
  font-family: 'Noto Sans TC', sans-serif;
  font-size: 18px;
  letter-spacing: 0.04em;
}

.urgent-care-heading p {
  margin-top: 2px;
}

.urgent-care-icon {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  place-items: center;
  border-radius: 50%;
  background: #b42335;
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  font-weight: 800;
}

.urgent-condition-alert {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border: 2px solid #c21f35;
  border-radius: 8px;
  background: #fff;
}

.urgent-condition-alert span {
  color: #831421;
  font-size: 13px;
  font-weight: 700;
}

.urgent-condition-alert strong {
  color: #b00020;
  font-family: 'Noto Sans TC', sans-serif;
  font-size: clamp(18px, 2vw, 22px);
  line-height: 1.45;
}

.urgent-care-disclaimer {
  color: #7f3a43;
  font-size: 12px;
}

.progress-bar {
  display: flex;
  height: 56px;
  flex: 0 0 56px;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-1);
}

.progress-track {
  flex: 1;
  height: 6px;
  overflow: hidden;
  border-radius: 2px;
  background: #e6edf3;
}

.progress-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--green);
  transition: width 0.4s ease;
}

.progress-bar span {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.progress-bar .questionnaire-badge {
  padding: 6px 10px;
  border: 1px solid rgb(10 146 126 / 32%);
  border-radius: 999px;
  background: var(--green-soft);
  color: var(--green);
  white-space: nowrap;
}

.progress-label {
  white-space: nowrap;
}

.patient-messages {
  flex: 1;
  padding: 24px;
  background: #fbfdff;
}

.patient-input-bar {
  display: flex;
  height: 74px;
  flex: 0 0 74px;
  align-items: center;
  gap: 8px;
  padding: 0 18px;
  border-top: 1px solid var(--border);
  background: var(--surface-1);
}

.structured-input-hint {
  min-height: 52px;
  flex: 0 0 52px;
  padding: 15px 18px;
  border-top: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}

.patient-input-bar input {
  min-width: 0;
  height: 50px;
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text);
  font-size: 16px;
}

.patient-input-bar input:disabled {
  opacity: 0.35;
}

.input-icon {
  display: grid;
  width: 50px;
  height: 50px;
  flex: 0 0 50px;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  cursor: pointer;
  font-size: 17px;
}

.input-icon.send {
  border-color: var(--green);
  background: var(--green);
  color: white;
}

.input-icon.recording {
  border-color: var(--danger);
  background: var(--danger);
}

.input-icon:disabled {
  cursor: not-allowed;
  opacity: 0.3;
}

@media (max-width: 760px) {
  .consultation-panel {
    width: 100%;
    margin: 0;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }

  .patient-messages {
    padding: 16px 12px;
  }

  .patient-context-bar {
    flex-wrap: wrap;
    gap: 5px 8px;
    padding: 7px 12px;
  }

  .patient-context-bar span:last-child {
    display: none;
  }

  .urgent-care-banner {
    padding: 14px 12px;
  }

  .urgent-care-heading strong {
    font-size: 17px;
  }

  .urgent-condition-alert strong {
    font-size: 18px;
  }

  .patient-input-bar {
    height: 70px;
    flex-basis: 70px;
    padding: 0 10px;
  }

  .questionnaire-badge {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .progress-bar {
    height: 52px;
    flex-basis: 52px;
    gap: 8px;
    padding: 0 12px;
  }

  .progress-bar span {
    font-size: 12px;
  }
}
</style>
