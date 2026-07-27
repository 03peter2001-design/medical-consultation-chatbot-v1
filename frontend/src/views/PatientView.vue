<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
  watchEffect,
} from 'vue'
import { RouterLink } from 'vue-router'

import AppHeader from '../components/AppHeader.vue'
import BodyPainMap from '../components/BodyPainMap.vue'
import ChatMessage from '../components/ChatMessage.vue'
import QueueCard from '../components/QueueCard.vue'
import TypingIndicator from '../components/TypingIndicator.vue'
import { useAvatar } from '../composables/useAvatar.js'
import { formatPainRegions } from '../data/bodyPainRegions.js'
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
import {
  composeQuestionAnswer,
  isQuestionAnswerReady,
  toggleQuestionOption,
} from '../services/questionnaire.js'

const sessionId = `pt_${Date.now()}`
const maxBirthDate = new Date().toISOString().slice(0, 10)

const avatar = useAvatar()
const messages = ref([])
const queueNumber = ref('')
const input = ref('')
const step = ref(0)
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
const selectedOptions = ref([])
const otherText = ref('')
const quickOption = ref('')
const durationNumber = ref('')
const durationUnit = ref('')
const recording = ref(false)
const voiceProcessing = ref(false)
const chatbox = ref(null)
const textInput = ref(null)
const otherInput = ref(null)
const dateInput = ref(null)
const durationInput = ref(null)
const videoElement = ref(null)

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
    questionInput.value?.field === 'location' &&
    questionnaireInfo.value?.section === 'disease' &&
    !completed.value,
)
const currentInputKind = computed(
  () => questionInput.value?.kind ?? 'text',
)
const answerReady = computed(() =>
  isQuestionAnswerReady(questionInput.value, {
    text: input.value,
    selectedOptions: selectedOptions.value,
    otherText: otherText.value,
    quickOption: quickOption.value,
    durationNumber: durationNumber.value,
    durationUnit: durationUnit.value,
  }),
)
const nationalIdValid = computed(() =>
  isNationalIdFormat(nationalId.value),
)
const loadedPatientName = computed(() =>
  fhirPatient.value ? patientDisplayName(fhirPatient.value) : '',
)

watchEffect(() => {
  if (videoElement.value) {
    videoElement.value.srcObject = avatar.videoStream.value
  }
})

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
    if (currentInputKind.value === 'choice') {
      otherInput.value?.focus()
    } else if (currentInputKind.value === 'date') {
      dateInput.value?.focus()
    } else if (currentInputKind.value === 'duration') {
      durationInput.value?.focus()
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
  selectedOptions.value = []
  otherText.value = ''
  quickOption.value = ''
  durationNumber.value = ''
  durationUnit.value =
    data.question_input?.units?.find((unit) => unit === '小時前') ||
    data.question_input?.units?.[0] ||
    ''
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
    step.value = data.step ?? 0
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
  step.value = data.step ?? step.value
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
  message = null,
  painLocationIds = [],
) {
  const answer =
    message ??
    composeQuestionAnswer(questionInput.value, {
      text: input.value,
      selectedOptions: selectedOptions.value,
      otherText: otherText.value,
      quickOption: quickOption.value,
      durationNumber: durationNumber.value,
      durationUnit: durationUnit.value,
    })
  const text = answer.trim()
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

function selectOption(option) {
  selectedOptions.value = toggleQuestionOption(
    selectedOptions.value,
    option,
    questionInput.value,
  )
  if (!questionInput.value?.multiple) otherText.value = ''
}

function handleOtherInput() {
  if (!questionInput.value?.multiple && otherText.value.trim()) {
    selectedOptions.value = []
  }
}

function selectQuickDuration(option) {
  quickOption.value = option
  durationNumber.value = ''
  otherText.value = ''
}

function handleDurationNumber() {
  quickOption.value = ''
  otherText.value = ''
}

function handleDurationUnit() {
  if (durationNumber.value) quickOption.value = ''
}

function handleDurationOther() {
  if (otherText.value.trim()) {
    quickOption.value = ''
    durationNumber.value = ''
  }
}

function submitPainLocations() {
  const text = formatPainRegions(selectedPainLocationIds.value)
  if (!text) return
  void submitMessage(text, selectedPainLocationIds.value)
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
    <div v-if="overlayVisible" class="start-overlay">
      <div class="overlay-logo">🩺</div>
      <h2>AI 預問診系統</h2>
      <div v-if="directFhirEnabled" class="test-mode-badge">
        測試模式 · 前端直連 HAPI
      </div>
      <div v-if="directFhirEnabled" class="identity-lookup">
        <label for="national-id">身分證字號</label>
        <input
          id="national-id"
          v-model="nationalId"
          type="text"
          maxlength="10"
          autocomplete="off"
          spellcheck="false"
          placeholder="A000000000"
          :aria-invalid="nationalId.length > 0 && !nationalIdValid"
          @input="nationalId = normalizeNationalId(nationalId)"
          @keydown.enter.prevent="nationalIdValid && startConsultation()"
        />
        <small>
          直接以 Patient.identifier 查詢 {{ fhirBaseUrl }}
        </small>
      </div>
      <p>
        Avatar 為選用功能<br />
        未連接也可以直接開始文字或語音問診
      </p>
      <p v-if="startError" class="start-error">{{ startError }}</p>
      <button
        class="start-button"
        :disabled="starting || (directFhirEnabled && !nationalIdValid)"
        @click="startConsultation"
      >
        {{
          starting
            ? '載入中…'
            : startError
              ? '重新載入'
              : directFhirEnabled
                ? '載入病歷並開始問診'
                : '開始問診'
        }}
      </button>
      <button
        v-if="directFhirEnabled"
        class="skip-id-button"
        type="button"
        :disabled="starting"
        @click="startConsultation({ skipFhir: true })"
      >
        略過身分證，直接進入問卷
      </button>
    </div>

    <AppHeader
      icon="🩺"
      title="AI 預問診系統"
      :status="completed ? '問診完成' : avatar.headerStatus.value"
      :status-tone="completed ? 'online' : avatar.headerTone.value"
    >
      <button
        class="utility-button avatar-toggle"
        type="button"
        @click="mobileAvatarOpen = !mobileAvatarOpen"
      >
        Avatar
      </button>
      <RouterLink class="nav-link" to="/doctor">醫師端 →</RouterLink>
    </AppHeader>

    <div
      v-if="mobileAvatarOpen"
      class="drawer-backdrop"
      @click="mobileAvatarOpen = false"
    />

    <main class="patient-layout">
      <aside class="avatar-sidebar" :class="{ open: mobileAvatarOpen }">
        <div class="avatar-preview">
          <div
            v-if="!avatar.videoStream.value"
            class="avatar-placeholder"
          >
            <div class="avatar-symbol">👤</div>
            <div>Avatar 為選用功能<br />未連接也可正常問診</div>
          </div>
          <video
            ref="videoElement"
            autoplay
            playsinline
            :class="{ visible: avatar.videoStream.value }"
          />
          <div class="wave-overlay" :class="{ visible: avatar.talking.value }">
            <span /><span /><span /><span /><span />
          </div>
          <button
            class="drawer-close"
            type="button"
            aria-label="關閉 Avatar 設定"
            @click="mobileAvatarOpen = false"
          >
            ✕
          </button>
        </div>

        <div class="avatar-config">
          <div class="config-title">D-ID Avatar（選用）</div>
          <label>
            <span>CLIENT KEY</span>
            <input
              v-model="clientKey"
              type="password"
              placeholder="ck_..."
              autocomplete="off"
            />
          </label>
          <label>
            <span>AGENT ID</span>
            <input
              v-model="agentId"
              type="text"
              placeholder="v2_agt_..."
              autocomplete="off"
            />
          </label>
          <button
            v-if="!avatar.isConnected.value"
            class="avatar-primary"
            :disabled="avatar.isConnecting.value"
            @click="connectAvatar"
          >
            {{ avatar.isConnecting.value ? '連接中…' : '連接 Avatar' }}
          </button>
          <button
            v-else
            class="avatar-secondary"
            @click="avatar.disconnect"
          >
            中斷連線
          </button>
          <div
            class="config-status"
            :class="`tone-${avatar.statusTone.value}`"
          >
            {{ avatar.status.value }}
          </div>
          <hr />
          <div class="config-title">取得金鑰方式</div>
          <div class="config-hint">
            1. 前往
            <a
              href="https://studio.d-id.com"
              target="_blank"
              rel="noopener noreferrer"
            >
              studio.d-id.com
            </a>
            <br />
            2. 建立 Agent → Embed → 複製金鑰<br />
            3. 填入上方欄位後連接
          </div>
        </div>
      </aside>

      <section class="consultation-panel">
        <div v-if="fhirPatient" class="patient-context-bar">
          <span class="context-status">FHIR 已載入</span>
          <strong>{{ loadedPatientName }}</strong>
          <span>Patient/{{ fhirPatient.id }}</span>
          <span>{{ fhirResourceCount }} 筆 Resources</span>
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
          <QueueCard v-if="queueNumber" :queue-number="queueNumber" />
          <section v-if="showBodyMap" class="pain-map-card">
            <div class="pain-map-heading">
              <div>
                <h3>請直接點選疼痛部位</h3>
                <p>可複選正面與背面；左右以病人本人為準。</p>
              </div>
              <span>{{ selectedPainLocationIds.length }} 個位置</span>
            </div>
            <BodyPainMap v-model="selectedPainLocationIds" />
            <button
              class="confirm-pain-button"
              type="button"
              :disabled="!selectedPainLocationIds.length || sending"
              @click="submitPainLocations"
            >
              {{ sending ? '傳送中…' : '確認疼痛位置' }}
            </button>
            <p class="pain-map-alternative">
              找不到適合的位置時，也可以在下方直接用文字描述。
            </p>
          </section>
          <section
            v-if="
              !completed &&
              currentInputKind === 'duration' &&
              questionInput
            "
            class="question-control-card duration-control"
          >
            <div class="duration-section">
              <span class="control-label">快捷選擇</span>
              <div class="duration-quick-grid">
                <button
                  v-for="option in questionInput.quick_options"
                  :key="option"
                  type="button"
                  class="duration-quick-option"
                  :class="{ selected: quickOption === option }"
                  :disabled="inputsDisabled"
                  @click="selectQuickDuration(option)"
                >
                  {{ option }}
                </button>
              </div>
            </div>
            <div class="duration-divider"><span>或自行輸入</span></div>
            <div class="duration-custom-row">
              <label>
                <span class="control-label">時間長度</span>
                <input
                  ref="durationInput"
                  v-model="durationNumber"
                  type="number"
                  min="0.1"
                  step="any"
                  inputmode="decimal"
                  placeholder="例如：3"
                  :disabled="inputsDisabled"
                  @input="handleDurationNumber"
                  @keydown.enter.prevent="answerReady && submitMessage()"
                />
              </label>
              <label>
                <span class="control-label">單位</span>
                <select
                  v-model="durationUnit"
                  :disabled="inputsDisabled"
                  @change="handleDurationUnit"
                >
                  <option
                    v-for="unit in questionInput.units"
                    :key="unit"
                    :value="unit"
                  >
                    {{ unit }}
                  </option>
                </select>
              </label>
            </div>
            <label
              v-if="questionInput.allow_other"
              class="other-answer"
            >
              <span>{{ questionInput.other_label }}</span>
              <input
                v-model="otherText"
                type="text"
                placeholder="例如：昨天晚上開始、剛剛開始"
                :disabled="inputsDisabled"
                @input="handleDurationOther"
                @keydown.enter.prevent="answerReady && submitMessage()"
              />
            </label>
            <button
              class="confirm-question-button"
              type="button"
              :disabled="inputsDisabled || !answerReady"
              @click="submitMessage()"
            >
              {{ sending ? '傳送中…' : '確認開始時間' }}
            </button>
          </section>
          <section
            v-if="
              !completed &&
              currentInputKind === 'choice' &&
              questionInput
            "
            class="question-control-card"
          >
            <div class="choice-grid">
              <label
                v-for="option in questionInput.options"
                :key="option"
                class="choice-option"
                :class="{
                  selected: selectedOptions.includes(option),
                }"
              >
                <input
                  :type="questionInput.multiple ? 'checkbox' : 'radio'"
                  name="question-choice"
                  :checked="selectedOptions.includes(option)"
                  :disabled="inputsDisabled"
                  @change="selectOption(option)"
                />
                <span>{{ option }}</span>
              </label>
            </div>
            <label
              v-if="questionInput.allow_other"
              class="other-answer"
            >
              <span>{{ questionInput.other_label }}</span>
              <input
                ref="otherInput"
                v-model="otherText"
                type="text"
                placeholder="找不到合適選項時可直接輸入"
                :disabled="inputsDisabled"
                @input="handleOtherInput"
                @keydown.enter.prevent="answerReady && submitMessage()"
              />
            </label>
            <button
              class="confirm-question-button"
              type="button"
              :disabled="inputsDisabled || !answerReady"
              @click="submitMessage()"
            >
              {{ sending ? '傳送中…' : '確認答案' }}
            </button>
          </section>
          <section
            v-if="
              !completed &&
              currentInputKind === 'date' &&
              questionInput
            "
            class="question-control-card date-control"
          >
            <label>
              <span>出生日期</span>
              <input
                ref="dateInput"
                v-model="input"
                type="date"
                :max="maxBirthDate"
                :disabled="inputsDisabled"
                @keydown.enter.prevent="answerReady && submitMessage()"
              />
            </label>
            <button
              class="confirm-question-button"
              type="button"
              :disabled="inputsDisabled || !answerReady"
              @click="submitMessage()"
            >
              {{ sending ? '傳送中…' : '確認日期' }}
            </button>
          </section>
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
            :disabled="inputsDisabled || !answerReady"
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

.start-overlay {
  position: fixed;
  z-index: 100;
  inset: var(--header-height) 0 0 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  padding: 24px;
  background: rgb(11 15 20 / 93%);
  backdrop-filter: blur(8px);
  text-align: center;
}

.overlay-logo {
  display: grid;
  width: 64px;
  height: 64px;
  place-items: center;
  border-radius: 18px;
  background: var(--green);
  box-shadow: 0 0 40px rgb(0 200 150 / 30%);
  font-size: 32px;
}

.start-overlay h2 {
  font-size: 24px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.start-overlay p {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.9;
  white-space: pre-wrap;
}

.start-overlay .start-error {
  max-width: 560px;
  color: var(--danger);
}

.test-mode-badge {
  padding: 5px 10px;
  border: 1px solid rgb(79 163 224 / 45%);
  border-radius: 999px;
  background: rgb(79 163 224 / 10%);
  color: var(--blue);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
}

.identity-lookup {
  display: flex;
  width: min(100%, 420px);
  flex-direction: column;
  gap: 7px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-1);
  text-align: left;
}

.identity-lookup label {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.identity-lookup input {
  width: 100%;
  padding: 11px 13px;
  border: 1px solid var(--border-strong);
  border-radius: 7px;
  background: var(--bg);
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.identity-lookup input[aria-invalid='true'] {
  border-color: var(--danger);
}

.identity-lookup small {
  overflow: hidden;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.start-button {
  min-width: 180px;
  padding: 14px 32px;
  border-radius: 10px;
  background: var(--green);
  color: #001a12;
  cursor: pointer;
  font-size: 16px;
  font-weight: 600;
  box-shadow: 0 0 24px rgb(0 200 150 / 40%);
}

.start-button:disabled {
  cursor: wait;
  opacity: 0.55;
}

.skip-id-button {
  padding: 9px 16px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 13px;
}

.skip-id-button:hover {
  border-color: var(--green);
  color: var(--green);
}

.skip-id-button:disabled {
  cursor: wait;
  opacity: 0.4;
}

@media (max-height: 650px) {
  .start-overlay {
    justify-content: flex-start;
    gap: 10px;
    overflow-y: auto;
    padding: 14px 24px;
  }

  .overlay-logo {
    display: none;
  }

  .identity-lookup {
    padding: 12px;
  }

  .start-overlay p {
    line-height: 1.5;
  }
}

.patient-layout {
  display: flex;
  flex: 1;
  min-height: 0;
}

.avatar-sidebar {
  z-index: 30;
  display: flex;
  width: 300px;
  flex: 0 0 300px;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--border);
  background: var(--surface-1);
}

.avatar-preview {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  flex: 0 0 auto;
  overflow: hidden;
  background: var(--surface-2);
}

.avatar-preview video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
}

.avatar-preview video.visible {
  opacity: 1;
}

.avatar-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

.avatar-symbol {
  font-size: 40px;
  opacity: 0.25;
}

.wave-overlay {
  position: absolute;
  bottom: 10px;
  left: 50%;
  display: none;
  height: 20px;
  align-items: flex-end;
  gap: 3px;
  transform: translateX(-50%);
}

.wave-overlay.visible {
  display: flex;
}

.wave-overlay span {
  width: 4px;
  height: 8px;
  border-radius: 3px;
  background: var(--blue);
  animation: wave 0.7s ease-in-out infinite;
}

.wave-overlay span:nth-child(2) {
  height: 16px;
  animation-delay: 0.1s;
}

.wave-overlay span:nth-child(3) {
  height: 10px;
  animation-delay: 0.2s;
}

.wave-overlay span:nth-child(4) {
  height: 18px;
  animation-delay: 0.3s;
}

.wave-overlay span:nth-child(5) {
  animation-delay: 0.4s;
}

.drawer-close,
.avatar-toggle {
  display: none;
}

.avatar-config {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  padding: 16px;
}

.config-title,
.avatar-config label span {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.avatar-config label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.avatar-config input {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.avatar-primary,
.avatar-secondary {
  width: 100%;
  padding: 9px 12px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.avatar-primary {
  background: var(--green);
  color: #001a12;
}

.avatar-secondary {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
}

.avatar-primary:disabled {
  cursor: wait;
  opacity: 0.4;
}

.config-status {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  text-align: center;
}

.config-status.tone-success {
  color: var(--green);
}

.config-status.tone-error {
  color: var(--danger);
}

.config-status.tone-waiting {
  color: var(--blue);
}

.avatar-config hr {
  border: 0;
  border-top: 1px solid var(--border);
}

.config-hint {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  line-height: 1.8;
}

.config-hint a {
  color: var(--blue);
  text-decoration: none;
}

.consultation-panel {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}

.patient-context-bar {
  display: flex;
  min-height: 38px;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  padding: 7px 20px;
  border-bottom: 1px solid var(--border);
  background: rgb(0 200 150 / 5%);
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
}

.patient-context-bar strong {
  color: var(--text);
  font-family: 'Noto Serif TC', serif;
  font-size: 12px;
}

.context-status {
  padding: 3px 7px;
  border-radius: 999px;
  background: rgb(0 200 150 / 13%);
  color: var(--green);
}

.progress-bar {
  display: flex;
  height: 44px;
  flex: 0 0 44px;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-1);
}

.progress-track {
  flex: 1;
  height: 4px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--border-strong);
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
  font-size: 11px;
}

.progress-bar .questionnaire-badge {
  padding: 4px 8px;
  border: 1px solid rgb(0 200 150 / 28%);
  border-radius: 999px;
  background: rgb(0 200 150 / 9%);
  color: var(--green);
  white-space: nowrap;
}

.progress-label {
  white-space: nowrap;
}

.patient-messages {
  flex: 1;
  padding: 20px;
}

.question-control-card {
  display: flex;
  width: min(100%, 620px);
  align-self: flex-start;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
}

.choice-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.duration-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.control-label {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.04em;
}

.duration-quick-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.duration-quick-option {
  min-height: 42px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text);
  cursor: pointer;
  font-size: 13px;
}

.duration-quick-option:hover,
.duration-quick-option.selected {
  border-color: rgb(0 200 150 / 65%);
  background: rgb(0 200 150 / 10%);
  color: var(--green);
}

.duration-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
}

.duration-divider::before,
.duration-divider::after {
  height: 1px;
  flex: 1;
  background: var(--border);
  content: '';
}

.duration-custom-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(140px, 0.65fr);
  gap: 10px;
}

.duration-custom-row label {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.duration-custom-row input,
.duration-custom-row select {
  width: 100%;
  min-height: 42px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
}

.choice-option {
  display: flex;
  min-height: 44px;
  align-items: center;
  gap: 9px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  cursor: pointer;
  font-size: 13px;
  line-height: 1.45;
}

.choice-option:hover,
.choice-option.selected {
  border-color: rgb(0 200 150 / 65%);
  background: rgb(0 200 150 / 8%);
}

.choice-option input {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  accent-color: var(--green);
}

.other-answer,
.date-control label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
}

.other-answer input,
.date-control input {
  width: 100%;
  min-height: 42px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
  font-family: 'Noto Sans TC', sans-serif;
  font-size: 14px;
}

.date-control input {
  color-scheme: dark;
}

.confirm-question-button {
  width: 100%;
  min-height: 42px;
  border-radius: 8px;
  background: var(--green);
  color: #001a12;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

.confirm-question-button:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}

.pain-map-card {
  display: flex;
  width: min(100%, 430px);
  align-self: flex-start;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
}

.pain-map-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.pain-map-heading h3 {
  margin-bottom: 4px;
  font-size: 14px;
  font-weight: 600;
}

.pain-map-heading p,
.pain-map-alternative {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  line-height: 1.6;
}

.pain-map-heading > span {
  flex: 0 0 auto;
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
}

.confirm-pain-button {
  width: 100%;
  padding: 10px 14px;
  border-radius: 7px;
  background: var(--green);
  color: #001a12;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

.confirm-pain-button:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}

.pain-map-alternative {
  text-align: center;
}

.patient-input-bar {
  display: flex;
  height: 64px;
  flex: 0 0 64px;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  border-top: 1px solid var(--border);
  background: var(--surface-1);
}

.structured-input-hint {
  min-height: 44px;
  flex: 0 0 44px;
  padding: 13px 18px;
  border-top: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  text-align: center;
}

.patient-input-bar input {
  min-width: 0;
  height: 42px;
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 14px;
}

.patient-input-bar input:disabled {
  opacity: 0.35;
}

.input-icon {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  cursor: pointer;
  font-size: 17px;
}

.input-icon.send {
  border-color: var(--green);
  background: var(--green);
  color: #001a12;
}

.input-icon.recording {
  border-color: var(--danger);
  background: var(--danger);
}

.input-icon:disabled {
  cursor: not-allowed;
  opacity: 0.3;
}

.drawer-backdrop {
  display: none;
}

@keyframes wave {
  50% {
    transform: scaleY(0.3);
  }
}

@media (max-width: 760px) {
  .start-overlay {
    inset: var(--header-height) 0 0;
  }

  .avatar-toggle {
    display: block;
  }

  .avatar-sidebar {
    position: fixed;
    top: var(--header-height);
    bottom: 0;
    left: 0;
    width: min(320px, 88vw);
    transform: translateX(-102%);
    transition: transform 0.25s ease;
  }

  .avatar-sidebar.open {
    transform: translateX(0);
  }

  .drawer-backdrop {
    position: fixed;
    z-index: 20;
    inset: var(--header-height) 0 0;
    display: block;
    background: rgb(0 0 0 / 55%);
  }

  .drawer-close {
    position: absolute;
    top: 10px;
    right: 10px;
    display: grid;
    width: 32px;
    height: 32px;
    place-items: center;
    border: 1px solid var(--border-strong);
    border-radius: 8px;
    background: rgb(11 15 20 / 78%);
    color: var(--text);
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

  .patient-input-bar {
    padding: 0 10px;
  }

  .choice-grid {
    grid-template-columns: 1fr;
  }

  .duration-quick-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .duration-custom-row {
    grid-template-columns: 1fr;
  }

  .questionnaire-badge {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
</style>
