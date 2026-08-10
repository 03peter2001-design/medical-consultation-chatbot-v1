<script setup>
const props = defineProps({
  avatar: { type: Object, required: true },
})

const emit = defineEmits(['connect'])
const clientKey = defineModel('clientKey', { type: String, default: '' })
const agentId = defineModel('agentId', { type: String, default: '' })
</script>

<template>
  <section class="avatar-controls" aria-labelledby="avatar-controls-title">
    <div class="controls-heading">
      <div>
        <span>AVATAR CONTROL</span>
        <h3 id="avatar-controls-title">醫師 Avatar 設定</h3>
      </div>
      <div
        class="config-status"
        :class="`tone-${avatar.statusTone.value}`"
        role="status"
        aria-live="polite"
      >
        <span class="status-dot" aria-hidden="true" />
        {{ avatar.status.value }}
      </div>
    </div>

    <form class="controls-grid" @submit.prevent="emit('connect')">
      <label>
        <span>提供者</span>
        <select
          :value="avatar.provider.value"
          :disabled="avatar.isConnecting.value"
          @change="avatar.setProvider($event.target.value)"
        >
          <option value="local">本地 · CosyVoice3 + MuseTalk</option>
          <option value="did">D-ID 雲端 Avatar</option>
        </select>
      </label>

      <label v-if="avatar.isLocal.value">
        <span>醫生說話語言</span>
        <select
          :value="avatar.language.value"
          :disabled="avatar.isConnecting.value"
          @change="avatar.setLanguage($event.target.value)"
        >
          <option value="mandarin">國語</option>
          <option value="minnan">閩南語</option>
        </select>
      </label>

      <template v-else>
        <label>
          <span>CLIENT KEY</span>
          <input
            v-model="clientKey"
            type="password"
            placeholder="ck_..."
            autocomplete="off"
            spellcheck="false"
          />
        </label>
        <label>
          <span>AGENT ID</span>
          <input
            v-model="agentId"
            type="text"
            placeholder="v2_agt_..."
            autocomplete="off"
            spellcheck="false"
          />
        </label>
      </template>

      <button
        v-if="!avatar.isConnected.value"
        class="avatar-primary"
        type="submit"
        :disabled="avatar.isConnecting.value"
      >
        {{ avatar.isConnecting.value ? '模型準備中…' : `啟用 ${avatar.providerLabel.value}` }}
      </button>
      <button
        v-else
        class="avatar-secondary"
        type="button"
        @click="avatar.disconnect"
      >
        中斷連線
      </button>
    </form>

    <div v-if="avatar.isLocal.value" class="model-strip">
      <span>語音模型</span>
      <strong>{{ avatar.speechModel.value }}</strong>
      <span>唇形動畫</span>
      <strong>{{ avatar.animationModel.value }}</strong>
      <small>語音與影片皆在院內主機產生；第一次載入可能需要較長時間。</small>
    </div>
    <p v-else class="privacy-note">
      D-ID 會將朗讀文字送往雲端。Client Key 只保存在本頁記憶體；請使用限制網域的
      Browser／Embed Key，切勿輸入伺服器私鑰。
      <a href="https://studio.d-id.com" target="_blank" rel="noopener noreferrer">
        開啟 D-ID Studio
      </a>
    </p>
  </section>
</template>

<style scoped>
.avatar-controls {
  width: 100%;
  padding: 18px 20px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: rgb(255 255 255 / 94%);
  text-align: left;
}

.controls-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.controls-heading > div:first-child span {
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.14em;
}

.controls-heading h3 {
  margin-top: 3px;
  font-size: 17px;
  font-weight: 720;
}

.config-status {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 7px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  text-align: right;
}

.status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 14%, transparent);
}

.config-status.tone-success { color: var(--green); }
.config-status.tone-error { color: var(--danger); }
.config-status.tone-waiting { color: var(--blue); }

.controls-grid {
  display: grid;
  grid-template-columns: minmax(190px, 1.2fr) minmax(150px, 0.8fr) minmax(150px, auto);
  align-items: end;
  gap: 12px;
}

.controls-grid label {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
}

.controls-grid label > span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
}

.controls-grid input,
.controls-grid select {
  width: 100%;
  min-height: 44px;
  padding: 9px 11px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.controls-grid input:focus,
.controls-grid select:focus {
  border-color: var(--green);
  outline: 3px solid rgb(10 146 126 / 12%);
}

.avatar-primary,
.avatar-secondary {
  min-height: 44px;
  padding: 9px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 720;
  white-space: nowrap;
}

.avatar-primary {
  border: 1px solid var(--green);
  background: var(--green);
  color: white;
}

.avatar-secondary {
  border: 1px solid var(--border-strong);
  background: var(--surface-1);
  color: var(--muted);
}

.avatar-primary:disabled {
  cursor: wait;
  opacity: 0.48;
}

.model-strip {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 5px 10px;
  margin-top: 12px;
  padding-top: 11px;
  border-top: 1px solid var(--border);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
}

.model-strip span { color: var(--muted); }
.model-strip strong { overflow-wrap: anywhere; color: var(--text); }
.model-strip small {
  grid-column: 1 / -1;
  margin-top: 3px;
  color: var(--muted);
  font-family: 'Noto Sans TC', sans-serif;
  line-height: 1.5;
}

.privacy-note {
  margin-top: 12px;
  padding-top: 11px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 12px;
  line-height: 1.65;
}

.privacy-note a {
  color: var(--blue);
  text-decoration: none;
}

@media (max-width: 760px) {
  .avatar-controls {
    padding: 14px;
  }

  .controls-heading {
    align-items: flex-start;
  }

  .config-status {
    max-width: 54%;
    line-height: 1.4;
  }

  .controls-grid {
    grid-template-columns: 1fr 1fr;
  }

  .controls-grid button {
    grid-column: 1 / -1;
  }

  .model-strip {
    grid-template-columns: auto minmax(0, 1fr);
  }
}

@media (max-width: 480px) {
  .controls-grid {
    grid-template-columns: 1fr;
  }

  .controls-grid button {
    grid-column: auto;
  }

  .controls-heading {
    flex-direction: column;
    gap: 8px;
  }

  .config-status {
    max-width: none;
    text-align: left;
  }
}
</style>
