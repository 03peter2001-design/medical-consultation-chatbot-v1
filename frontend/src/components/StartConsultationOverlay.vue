<script setup>
import AvatarSettings from './AvatarSettings.vue'
import AvatarStage from './AvatarStage.vue'
import { normalizeNationalId } from '../services/fhir.js'

defineProps({
  avatar: { type: Object, required: true },
  visible: { type: Boolean, default: false },
  directFhirEnabled: { type: Boolean, default: false },
  fhirBaseUrl: { type: String, default: '' },
  nationalIdValid: { type: Boolean, default: false },
  smartLaunch: { type: Boolean, default: false },
  starting: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['start', 'connect-avatar'])
const nationalId = defineModel('nationalId', {
  type: String,
  default: 'A000000000',
})
const avatarClientKey = defineModel('avatarClientKey', {
  type: String,
  default: '',
})
const avatarAgentId = defineModel('avatarAgentId', {
  type: String,
  default: '',
})

function normalizeInput() {
  nationalId.value = normalizeNationalId(nationalId.value)
}
</script>

<template>
  <div
    v-if="visible"
    class="start-overlay"
    role="dialog"
    aria-modal="true"
    aria-labelledby="start-title"
  >
    <h2 id="start-title">AI 預問診系統</h2>
    <div class="start-workspace">
      <div class="start-avatar-stage">
        <AvatarStage
          :avatar="avatar"
          @connect="emit('connect-avatar')"
        />
      </div>

      <div class="start-actions">
        <div v-if="directFhirEnabled" class="test-mode-badge">
          測試模式 · 前端直連 HAPI
        </div>
        <div v-else-if="smartLaunch" class="smart-mode-badge">
          SMART on FHIR · OAuth 授權模式
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
            @input="normalizeInput"
            @keydown.enter.prevent="nationalIdValid && emit('start')"
          />
          <small>
            直接以 Patient.identifier 查詢 {{ fhirBaseUrl }}
          </small>
        </div>
        <p v-if="smartLaunch">
          正在使用 EHR Launch Context 載入目前病人病歷<br />
          access token 只保留在這個瀏覽器工作階段
        </p>
        <p v-else>
          AI 醫師 Avatar 會自動啟用<br />
          若模型暫時無法使用，仍可直接開始文字問診
        </p>
        <p v-if="error" class="start-error">{{ error }}</p>
        <button
          class="start-button"
          :disabled="starting || (directFhirEnabled && !nationalIdValid)"
          @click="emit('start')"
        >
          {{
            starting
              ? '載入中…'
              : error
                ? '重新載入'
                : smartLaunch
                  ? '載入授權病歷並開始'
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
          @click="emit('start', { skipFhir: true })"
        >
          略過身分證，直接進入問卷
        </button>
      </div>

      <div class="start-avatar-settings">
        <AvatarSettings
          v-model:client-key="avatarClientKey"
          v-model:agent-id="avatarAgentId"
          :avatar="avatar"
          @connect="emit('connect-avatar')"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.start-overlay {
  position: fixed;
  z-index: 100;
  inset: var(--header-height) 0 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
  gap: 16px;
  padding: 24px;
  background: rgb(244 247 250 / 96%);
  backdrop-filter: blur(10px);
  text-align: center;
}

.start-overlay h2 {
  flex: 0 0 auto;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.start-workspace {
  display: grid;
  width: min(100%, 1180px);
  grid-template-columns: minmax(0, 2fr) minmax(300px, 0.9fr);
  grid-template-areas:
    'stage actions'
    'settings actions';
  align-items: start;
  gap: 14px 18px;
}

.start-avatar-stage {
  grid-area: stage;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: 0 18px 46px rgb(37 67 91 / 14%);
}

.start-actions {
  display: flex;
  grid-area: actions;
  align-self: center;
  align-items: center;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.start-avatar-settings {
  grid-area: settings;
  min-width: 0;
  overflow: hidden;
  border-radius: 14px;
  box-shadow: 0 12px 34px rgb(37 67 91 / 9%);
}

.start-overlay p {
  color: var(--muted);
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.start-overlay .start-error {
  max-width: 560px;
  color: var(--danger);
}

.test-mode-badge {
  padding: 6px 11px;
  border: 1px solid rgb(37 104 178 / 28%);
  border-radius: 999px;
  background: var(--blue-soft);
  color: var(--blue);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  letter-spacing: 0.06em;
}

.smart-mode-badge {
  padding: 6px 11px;
  border: 1px solid rgb(8 127 109 / 28%);
  border-radius: 999px;
  background: var(--green-soft);
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  letter-spacing: 0.04em;
}

.identity-lookup {
  display: flex;
  width: min(100%, 420px);
  flex-direction: column;
  gap: 7px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-1);
  box-shadow: 0 10px 30px rgb(37 67 91 / 8%);
  text-align: left;
}

.identity-lookup label {
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
}

.identity-lookup input {
  width: 100%;
  min-height: 48px;
  padding: 11px 13px;
  border: 1px solid var(--border-strong);
  border-radius: 7px;
  background: var(--surface-1);
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
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.start-button {
  min-width: 180px;
  min-height: 50px;
  padding: 13px 32px;
  border-radius: 10px;
  background: var(--green);
  color: white;
  cursor: pointer;
  font-size: 16px;
  font-weight: 600;
  box-shadow: 0 10px 24px rgb(10 146 126 / 22%);
}

.start-button:disabled {
  cursor: wait;
  opacity: 0.55;
}

.skip-id-button {
  min-height: 44px;
  padding: 10px 16px;
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

@media (max-height: 900px) {
  .start-overlay {
    justify-content: flex-start;
    gap: 10px;
    overflow-y: auto;
    padding: 14px 24px;
  }

  .identity-lookup {
    padding: 12px;
  }

  .start-overlay p {
    line-height: 1.5;
  }
}

@media (max-width: 900px) {
  .start-workspace {
    width: min(100%, 720px);
    grid-template-columns: 1fr;
    grid-template-areas:
      'stage'
      'actions'
      'settings';
  }

  .start-actions {
    width: 100%;
  }
}

@media (max-width: 760px) {
  .start-overlay {
    inset: var(--header-height) 0 0;
    justify-content: flex-start;
    overflow-y: auto;
    gap: 12px;
    padding: 20px;
  }

  .start-workspace {
    gap: 12px;
  }

  .identity-lookup {
    width: 100%;
  }
}
</style>
