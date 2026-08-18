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
import AvatarSettings from '../components/AvatarSettings.vue'
import AvatarStage from '../components/AvatarStage.vue'
import ChatMessage from '../components/ChatMessage.vue'
import PainLocationInput from '../components/PainLocationInput.vue'
import QuestionnaireControl from '../components/QuestionnaireControl.vue'
import QueueCard from '../components/QueueCard.vue'
import StartConsultationOverlay from '../components/StartConsultationOverlay.vue'
import TypingIndicator from '../components/TypingIndicator.vue'
import VoiceWaveform from '../components/VoiceWaveform.vue'
import { useAvatar } from '../composables/useAvatar.js'
import { getPainMapPreset } from '../data/bodyPainRegions.js'
import { api, connectionError } from '../services/backend.js'
import {
  PATIENT_IDENTIFIER_TYPES,
  buildPatientPrefill,
  directFhirEnabled,
  fhirBaseUrl,
  isPatientIdentifierFormat,
  loadPatientByIdentifier,
  normalizePatientIdentifier,
  patientDisplayName,
} from '../services/fhir.js'
import {
  hasSmartLaunchContext,
  initializeSmartPatient,
} from '../services/smart.js'
import {
  AUTO_SEND_REVIEW_MS,
  AVATAR_SILENCE_MS,
  normalizeVoiceLevel,
  rootMeanSquare,
  updateVoiceActivity,
} from '../services/voiceActivity.js'
const sessionId = `pt_${Date.now()}`
const maxBirthDate = new Date().toISOString().slice(0, 10)
const smartLaunchDetected = hasSmartLaunchContext()

const avatar = useAvatar({
  getStatus: api.avatarStatus,
  warmup: api.avatarWarmup,
  synthesize: api.speakAvatar,
  initialProvider: import.meta.env.VITE_AVATAR_PROVIDER,
})
const avatarClientKey = ref(import.meta.env.VITE_DID_CLIENT_KEY?.trim() || '')
const avatarAgentId = ref(import.meta.env.VITE_DID_AGENT_ID?.trim() || '')
const messages = ref([])
const queueNumber = ref('')
const input = ref('')
const started = ref(false)
const consultationAvatarSettingsOpen = ref(false)
const consultationLanguage = ref(null)
const starting = ref(false)
const sending = ref(false)
const completed = ref(false)
const typing = ref(false)
const startError = ref('')
const overlayVisible = ref(true)
const identifierType = ref(PATIENT_IDENTIFIER_TYPES.NATIONAL_ID)
const nationalId = ref('A000000000')
const syntheaDefaultId = ref('')
const fhirPatient = ref(null)
const fhirResourceCount = ref(0)
const smartContext = ref(null)
const selectedPainLocationIds = ref([])
const questionInput = ref(null)
const questionnaireInfo = ref(null)
const canGoBack = ref(false)
const progressState = ref({ current: 0, total: 1, percent: 0 })
const triageState = ref({
  level: 'routine',
  message: '',
  possible_conditions: [],
})
const recording = ref(false)
const voiceProcessing = ref(false)
const autoSendPending = ref(false)
const voiceNotice = ref('')
const voiceLevel = ref(0)
const voiceDetected = ref(false)
const chatbox = ref(null)
const textInput = ref(null)
const questionnaireControl = ref(null)

let mediaRecorder = null
let mediaStream = null
let audioChunks = []
let recordingTimeout = null
let voiceActivityTimer = null
let autoSendTimeout = null
let audioContext = null
let audioSource = null
let analyser = null
let analyserSamples = null
let voiceActivityState = { speechStarted: false, lastVoiceAt: 0 }
let recordingAutoSubmit = false
let stopOnSilence = false

const progress = computed(() => progressState.value.percent ?? 0)
const progressLabel = computed(() =>
  progress.value >= 100 ? '完成 ✓' : `${progress.value}%`,
)
const inputsDisabled = computed(
  () =>
    !started.value ||
    starting.value ||
    sending.value ||
    recording.value ||
    voiceProcessing.value ||
    completed.value,
)
const consultationAvatarVisible = computed(
  () =>
    avatar.isConnected.value ||
    avatar.isConnecting.value ||
    avatar.rendering.value ||
    avatar.talking.value,
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
const patientIdentifier = computed(() =>
  identifierType.value === PATIENT_IDENTIFIER_TYPES.SYNTHEA_DEFAULT_ID
    ? syntheaDefaultId.value
    : nationalId.value,
)
const patientIdentifierValid = computed(() =>
  isPatientIdentifierFormat(identifierType.value, patientIdentifier.value),
)
const loadedPatientName = computed(() =>
  fhirPatient.value ? patientDisplayName(fhirPatient.value) : '',
)
const effectiveDirectFhirEnabled = computed(
  () => directFhirEnabled && !smartLaunchDetected,
)
const patientContextStatus = computed(() =>
  smartContext.value ? 'SMART 已授權' : 'FHIR 已載入',
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
  cancelAutoSend()
  questionInput.value = data.question_input ?? null
  questionnaireInfo.value = data.questionnaire ?? null
  canGoBack.value = Boolean(data.can_go_back)
  progressState.value =
    data.progress ?? progressState.value
  triageState.value =
    data.triage ?? triageState.value
  input.value = ''
  voiceNotice.value = ''
}

async function initializeBackendSession(patientRecord = null) {
  return api.patientChat(
    '',
    sessionId,
    [],
    patientRecord ? buildPatientPrefill(patientRecord) : null,
    consultationLanguage.value || avatar.language.value,
  )
}

async function finishConsultationStart(
  patientRecord = null,
  {
    successMessage = '',
  } = {},
) {
  consultationLanguage.value = avatar.language.value
  let data
  try {
    data = await initializeBackendSession(patientRecord)
  } catch (error) {
    consultationLanguage.value = null
    throw error
  }
  started.value = true
  overlayVisible.value = false
  setQuestionState(data)
  if (successMessage) addMessage('ai', successMessage)
  addMessage('ai', data.reply)
  void avatar.speak(data.reply)
  focusInput()
}

async function startSmartConsultation() {
  if (started.value || starting.value) return
  starting.value = true
  startError.value = ''

  try {
    const record = await initializeSmartPatient()
    fhirPatient.value = record.patient
    fhirResourceCount.value = record.resources.length
    smartContext.value = record.smart
    const encounter = record.smart.encounterId
      ? `，Encounter/${record.smart.encounterId}`
      : ''
    await finishConsultationStart(record, {
      successMessage:
        `已透過 SMART on FHIR 授權載入 ${patientDisplayName(record.patient)}` +
        `（Patient/${record.patient.id}${encounter}），共 ${record.resources.length} 筆相關 FHIR Resources。` +
        '已帶入基本資料與既往病史；只有病歷未提供的欄位會再詢問。',
    })
  } catch (error) {
    startError.value =
      `無法完成 SMART on FHIR 授權或載入病歷（${error.message}）。` +
      '\n請回到 EHR 重新選擇病人並啟動此 App。'
  } finally {
    starting.value = false
  }
}

async function startConsultation({ skipFhir = false } = {}) {
  if (started.value || starting.value) return
  if (smartLaunchDetected && !skipFhir) {
    await startSmartConsultation()
    return
  }
  starting.value = true
  startError.value = ''
  let startStage =
    effectiveDirectFhirEnabled.value && !skipFhir ? 'fhir' : 'backend'

  try {
    let patient = null
    let patientRecord = null
    if (effectiveDirectFhirEnabled.value && !skipFhir) {
      const normalizedIdentifier = normalizePatientIdentifier(
        identifierType.value,
        patientIdentifier.value,
      )
      if (
        identifierType.value === PATIENT_IDENTIFIER_TYPES.SYNTHEA_DEFAULT_ID
      ) {
        syntheaDefaultId.value = normalizedIdentifier
      } else {
        nationalId.value = normalizedIdentifier
      }
      const record = await loadPatientByIdentifier(
        identifierType.value,
        normalizedIdentifier,
        {
          baseUrl: fhirBaseUrl,
        },
      )
      patient = record.patient
      patientRecord = record
      fhirPatient.value = patient
      fhirResourceCount.value = record.resources.length
      startStage = 'backend'
    }

    await finishConsultationStart(patientRecord, {
      successMessage: patient
        ? `已從測試 HAPI 載入 ${patientDisplayName(patient)}（Patient/${patient.id}），共 ${fhirResourceCount.value} 筆相關 FHIR Resources。已帶入基本資料；只有病歷未提供的病史欄位會再詢問。`
        : '',
    })
  } catch (error) {
    startError.value =
      startStage === 'fhir'
        ? `無法從測試 HAPI 載入病人（${error.message}）。\n嘗試連線：${fhirBaseUrl}`
        : connectionError(error)
  } finally {
    starting.value = false
  }
}

onMounted(() => {
  void connectAvatar()
  if (smartLaunchDetected) void startSmartConsultation()
})

function handleResponse(data, rawFallback) {
  addMessage('user', data.user_display ?? rawFallback)
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

  cancelAutoSend()
  sending.value = true
  typing.value = true
  try {
    const data = await api.patientChat(
      text,
      sessionId,
      painLocationIds,
      null,
      consultationLanguage.value,
    )
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

function trimLastAnsweredTurn() {
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    if (messages.value[index].role === 'user') {
      messages.value.splice(index)
      return
    }
  }
}

async function goToPreviousQuestion() {
  if (!canGoBack.value || inputsDisabled.value) return

  sending.value = true
  try {
    const data = await api.patientBack(sessionId, consultationLanguage.value)
    trimLastAnsweredTurn()
    selectedPainLocationIds.value = []
    completed.value = false
    queueNumber.value = ''
    setQuestionState(data)
  } catch (error) {
    addMessage('ai', `⚠️ ${connectionError(error)}`)
  } finally {
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
    clientKey: avatarClientKey.value,
    agentId: avatarAgentId.value,
  })
  if (!connected) return
  if (started.value) {
    const latestAssistant = [...messages.value]
      .reverse()
      .find((message) => message.role === 'ai' && message.text)
    if (latestAssistant) await avatar.speak(latestAssistant.text)
  }
}

function cancelAutoSendForEditing() {
  if (!autoSendPending.value) return
  cancelAutoSend()
  voiceNotice.value = '已暫停自動送出，您可以修改文字後手動送出。'
}

function cancelAutoSend() {
  if (autoSendTimeout) window.clearTimeout(autoSendTimeout)
  autoSendTimeout = null
  autoSendPending.value = false
}

function scheduleAutoSend() {
  cancelAutoSend()
  autoSendPending.value = true
  voiceNotice.value = '語音辨識完成，3 秒後自動送出；開始編輯可取消。'
  autoSendTimeout = window.setTimeout(() => {
    autoSendTimeout = null
    autoSendPending.value = false
    const text = input.value.trim()
    if (text && !sending.value && !completed.value) void submitMessage(text)
  }, AUTO_SEND_REVIEW_MS)
}

function structuredVoiceMessage(result, transcript) {
  if (result?.status === 'mapped') {
    return `已辨識「${transcript}」並填入答案，請確認後再送出。`
  }
  if (result?.status === 'other') {
    return `已辨識「${transcript}」並填入其他／補充說明，請確認後再送出。`
  }
  return `已辨識「${transcript}」，但無法安全轉成目前題目的答案，請手動作答或重新錄音。`
}

function stopVoiceActivityDetection() {
  if (voiceActivityTimer) window.clearInterval(voiceActivityTimer)
  voiceActivityTimer = null
  try {
    audioSource?.disconnect()
  } catch {
    // The stream may already be disconnected during browser teardown.
  }
  audioSource = null
  analyser = null
  analyserSamples = null
  voiceLevel.value = 0
  voiceDetected.value = false
  stopOnSilence = false
  const context = audioContext
  audioContext = null
  if (context && context.state !== 'closed') void context.close()
}

function startVoiceActivityDetection(stream, { autoStop = false } = {}) {
  stopVoiceActivityDetection()
  const AudioContextClass = window.AudioContext || window.webkitAudioContext
  if (!AudioContextClass) return false
  audioContext = new AudioContextClass()
  analyser = audioContext.createAnalyser()
  analyser.fftSize = 2048
  analyser.smoothingTimeConstant = 0.15
  analyserSamples = new Uint8Array(analyser.fftSize)
  audioSource = audioContext.createMediaStreamSource(stream)
  audioSource.connect(analyser)
  voiceActivityState = { speechStarted: false, lastVoiceAt: 0 }
  stopOnSilence = autoStop
  voiceActivityTimer = window.setInterval(() => {
    if (!analyser || !analyserSamples || !recording.value) return
    analyser.getByteTimeDomainData(analyserSamples)
    const rms = rootMeanSquare(analyserSamples)
    voiceLevel.value = normalizeVoiceLevel(rms)
    voiceActivityState = updateVoiceActivity(voiceActivityState, {
      rms,
      now: Date.now(),
    })
    voiceDetected.value = voiceActivityState.speechStarted
    if (stopOnSilence && voiceActivityState.shouldStop) {
      stopRecording({ autoSubmit: true, reason: 'silence' })
    }
  }, 100)
  return true
}

function stopRecording({ autoSubmit = false, reason = 'manual' } = {}) {
  if (mediaRecorder?.state !== 'recording') return
  recordingAutoSubmit = autoSubmit
  voiceNotice.value =
    reason === 'silence'
      ? `已偵測到 ${AVATAR_SILENCE_MS / 1000} 秒停頓，正在完成錄音…`
      : '正在結束錄音…'
  stopVoiceActivityDetection()
  mediaRecorder.stop()
}

async function startVoiceRecording({ autoSubmitOnSilence = false } = {}) {
  if (completed.value || voiceProcessing.value) return
  if (recording.value || sending.value) return
  if (input.value.trim()) return

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true,
      },
    })
    const preferredType = [
      'audio/webm;codecs=opus',
      'audio/mp4',
      'audio/webm',
    ].find((type) => window.MediaRecorder?.isTypeSupported?.(type))
    const options = preferredType ? { mimeType: preferredType } : undefined
    mediaRecorder = new MediaRecorder(mediaStream, options)
    audioChunks = []
    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) audioChunks.push(event.data)
    }
    mediaRecorder.onstop = () => void processRecording()
    mediaRecorder.start()
    recording.value = true
    recordingAutoSubmit = false
    const activityDetectionReady = startVoiceActivityDetection(mediaStream, {
      autoStop: autoSubmitOnSilence,
    })
    const silenceDetectionReady = autoSubmitOnSilence && activityDetectionReady
    voiceNotice.value = silenceDetectionReady
      ? currentInputKind.value === 'text'
        ? `請直接說話；開始說話後停頓 ${AVATAR_SILENCE_MS / 1000} 秒會完成辨識並自動送出。`
        : `請直接說話；開始說話後停頓 ${AVATAR_SILENCE_MS / 1000} 秒會完成辨識並填入答案，仍需確認後送出。`
      : activityDetectionReady
        ? '錄音中；音波會跟著收到的聲音變化，再按一次麥克風停止。'
        : '錄音中，再按一次麥克風停止（最長 60 秒）。'
    recordingTimeout = window.setTimeout(() => {
      if (mediaRecorder?.state === 'recording') {
        stopRecording({
          autoSubmit: autoSubmitOnSilence && voiceActivityState.speechStarted,
          reason: 'timeout',
        })
      }
    }, 60_000)
  } catch (error) {
    voiceNotice.value = ''
    mediaStream?.getTracks().forEach((track) => track.stop())
    mediaStream = null
    addMessage('ai', `⚠️ 無法存取麥克風：${error.message}`)
  }
}

async function toggleVoice() {
  if (recording.value) {
    stopRecording({ autoSubmit: false })
    return
  }
  await startVoiceRecording({
    autoSubmitOnSilence: avatar.isConnected.value,
  })
}

async function processRecording() {
  const shouldAutoSubmit = recordingAutoSubmit
  recordingAutoSubmit = false
  recording.value = false
  if (recordingTimeout) window.clearTimeout(recordingTimeout)
  recordingTimeout = null
  stopVoiceActivityDetection()
  mediaStream?.getTracks().forEach((track) => track.stop())
  mediaStream = null
  voiceProcessing.value = true
  voiceNotice.value = '正在使用 Breeze ASR 辨識錄音…'

  try {
    const audioBlob = new Blob(audioChunks, {
      type: mediaRecorder?.mimeType || 'audio/webm',
    })
    const transcript = await api.transcribe(audioBlob)
    const text = transcript.text?.trim()
    if (!text) {
      await askPatientToRepeat()
      return
    }
    const latency = Number(transcript.latency_seconds)
    const latencyLabel = Number.isFinite(latency)
      ? `，${latency.toFixed(1)} 秒`
      : ''
    const providerLabel =
      transcript.provider === 'breeze' ? 'Breeze ASR' : '語音 ASR'
    if (currentInputKind.value === 'text') {
      input.value = text
      voiceNotice.value = `語音辨識完成（${providerLabel}${latencyLabel}），請確認文字後再送出。`
    } else {
      const result = questionnaireControl.value?.applyVoiceTranscript(text)
      voiceNotice.value = structuredVoiceMessage(result, text)
    }
    voiceProcessing.value = false
    await nextTick()
    focusInput()
    if (shouldAutoSubmit && currentInputKind.value === 'text') {
      scheduleAutoSend()
    }
  } catch (error) {
    await askPatientToRepeat(error.message)
  } finally {
    voiceProcessing.value = false
    audioChunks = []
    mediaRecorder = null
  }
}

async function askPatientToRepeat(detail = '') {
  const prompt = '對不起，我沒有聽清楚，請再講一次。'
  voiceNotice.value = detail ? `語音辨識失敗：${detail}` : '未辨識到語音內容。'
  addMessage('ai', prompt)
  if (avatar.isConnected.value) await avatar.speak(prompt)
}

watch(
  () => avatar.talking.value,
  (talking, wasTalking) => {
    if (
      wasTalking &&
      !talking &&
      avatar.isConnected.value &&
      started.value &&
      !completed.value
    ) {
      window.setTimeout(() => {
        void startVoiceRecording({ autoSubmitOnSilence: true })
      }, 250)
    }
  },
)

watch(
  () => avatar.isConnected.value,
  (connected) => {
    if (connected) return
    cancelAutoSend()
    if (recording.value) stopRecording({ autoSubmit: false })
  },
)

onBeforeUnmount(() => {
  cancelAutoSend()
  stopVoiceActivityDetection()
  if (recordingTimeout) window.clearTimeout(recordingTimeout)
  if (mediaRecorder?.state === 'recording') {
    mediaRecorder.onstop = null
    mediaRecorder.stop()
  }
  mediaStream?.getTracks().forEach((track) => track.stop())
})
</script>

<template>
  <div class="app-shell patient-app">
    <StartConsultationOverlay
      v-model:identifier-type="identifierType"
      v-model:national-id="nationalId"
      v-model:synthea-default-id="syntheaDefaultId"
      v-model:avatar-client-key="avatarClientKey"
      v-model:avatar-agent-id="avatarAgentId"
      :avatar="avatar"
      :visible="overlayVisible"
      :direct-fhir-enabled="effectiveDirectFhirEnabled"
      :fhir-base-url="fhirBaseUrl"
      :identifier-valid="patientIdentifierValid"
      :smart-launch="smartLaunchDetected"
      :starting="starting"
      :error="startError"
      @start="startConsultation"
      @connect-avatar="connectAvatar"
    />

    <AppHeader
      icon="🩺"
      title="AI 預問診系統"
      :status="completed ? '問診完成' : avatar.headerStatus.value"
      :status-tone="completed ? 'online' : avatar.headerTone.value"
    >
      <RouterLink class="nav-link" to="/doctor">醫師端 →</RouterLink>
    </AppHeader>

    <main class="patient-layout">
      <section class="consultation-panel">
        <div v-if="fhirPatient" class="patient-context-bar">
          <span class="context-status">{{ patientContextStatus }}</span>
          <strong>{{ loadedPatientName }}</strong>
          <span>Patient/{{ fhirPatient.id }}</span>
          <span v-if="smartContext?.encounterId">
            Encounter/{{ smartContext.encounterId }}
          </span>
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
        <AvatarStage
          v-if="started && consultationAvatarVisible"
          :avatar="avatar"
          @connect="connectAvatar"
        />
        <div v-if="started" class="consultation-avatar-settings">
          <button
            class="avatar-settings-toggle"
            type="button"
            aria-controls="consultation-avatar-settings"
            :aria-expanded="consultationAvatarSettingsOpen"
            @click="consultationAvatarSettingsOpen = !consultationAvatarSettingsOpen"
          >
            <span class="avatar-settings-toggle-label">Avatar 設定</span>
            <span class="avatar-settings-toggle-summary">
              {{
                consultationAvatarVisible
                  ? `${avatar.providerLabel.value} · ${avatar.languageLabel.value}`
                  : avatar.status.value
              }}
            </span>
            <span aria-hidden="true">
              {{ consultationAvatarSettingsOpen ? '隱藏 ↑' : '顯示 ↓' }}
            </span>
          </button>
          <div
            v-show="consultationAvatarSettingsOpen"
            id="consultation-avatar-settings"
            class="consultation-avatar-settings-content"
          >
            <AvatarSettings
              v-model:client-key="avatarClientKey"
              v-model:agent-id="avatarAgentId"
              :avatar="avatar"
              :language-locked="started"
              @connect="connectAvatar"
            />
          </div>
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
          <button
            v-if="!completed && canGoBack"
            class="previous-question-button"
            type="button"
            :disabled="inputsDisabled"
            @click="goToPreviousQuestion"
          >
            ← 回到上一題
          </button>
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
            @input="cancelAutoSendForEditing"
            @keydown="handleInputKeydown"
          />
          <VoiceWaveform
            v-if="recording"
            :level="voiceLevel"
            :received="voiceDetected"
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
        <p
          v-if="!completed && currentInputKind === 'text' && voiceNotice"
          class="voice-notice"
          role="status"
        >
          {{ voiceNotice }}
        </p>
        <div
          v-if="!completed && currentInputKind !== 'text'"
          class="structured-input-hint"
        >
          {{
            currentInputKind === 'duration'
              ? '請在上方選擇快捷時間、輸入時間，或使用語音作答。'
              : currentInputKind === 'date'
                ? '請選擇日期，或使用語音說出西元／民國年月日。'
                : '請在上方選擇答案，或使用語音作答後確認辨識結果。'
          }}
        </div>
        <div
          v-if="!completed && currentInputKind !== 'text'"
          class="structured-voice-bar"
        >
          <span>{{ recording ? '正在聆聽您的答案' : '也可以用語音回答這一題' }}</span>
          <VoiceWaveform
            v-if="recording"
            :level="voiceLevel"
            :received="voiceDetected"
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
        </div>
        <p
          v-if="!completed && currentInputKind !== 'text' && voiceNotice"
          class="voice-notice"
          role="status"
        >
          {{ voiceNotice }}
        </p>
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

.consultation-avatar-settings {
  flex: 0 0 auto;
  border-bottom: 1px solid var(--border);
  background: var(--surface-1);
}

.avatar-settings-toggle {
  display: flex;
  width: 100%;
  min-height: 48px;
  align-items: center;
  gap: 12px;
  padding: 8px 20px;
  border: 0;
  background: var(--surface-1);
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
  text-align: left;
}

.avatar-settings-toggle:hover,
.avatar-settings-toggle:focus-visible {
  background: var(--green-soft);
  color: var(--green);
}

.avatar-settings-toggle:focus-visible {
  outline: 3px solid rgb(10 146 126 / 20%);
  outline-offset: -3px;
}

.avatar-settings-toggle-label {
  color: var(--text);
  font-size: 14px;
  font-weight: 700;
}

.avatar-settings-toggle-summary {
  flex: 1;
  overflow: hidden;
  font-family: 'JetBrains Mono', monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.consultation-avatar-settings-content {
  padding: 0 12px 12px;
  background: var(--surface-2);
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

.previous-question-button {
  min-height: 42px;
  align-self: flex-start;
  padding: 9px 14px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--blue);
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.previous-question-button:hover:not(:disabled) {
  border-color: var(--blue);
  background: var(--blue-soft);
}

.previous-question-button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
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

.voice-notice {
  margin: 0;
  padding: 7px 18px;
  border-top: 1px solid var(--border);
  background: var(--blue-soft);
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
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

.structured-voice-bar {
  display: flex;
  min-height: 64px;
  flex: 0 0 64px;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 7px 18px;
  border-top: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
}

.structured-voice-bar > span:first-child {
  margin-right: auto;
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

  .avatar-settings-toggle {
    gap: 8px;
    padding: 8px 12px;
  }

  .avatar-settings-toggle-summary {
    font-size: 10px;
  }

  .consultation-avatar-settings-content {
    padding: 0 8px 8px;
  }

  .patient-input-bar {
    height: 70px;
    flex-basis: 70px;
    padding: 0 10px;
  }

  .structured-voice-bar {
    padding: 7px 10px;
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
