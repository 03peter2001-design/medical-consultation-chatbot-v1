<script setup>
defineProps({
  changedGroups: { type: Array, required: true },
  confirmationText: { type: String, required: true },
  validationError: { type: String, default: '' },
  canSave: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['cancel', 'save'])
const changeNote = defineModel('changeNote', { type: String, default: '' })
const confirmation = defineModel('confirmation', {
  type: String,
  default: '',
})
</script>

<template>
  <form class="publish-panel" @submit.prevent="emit('save')">
    <header>
      <div>
        <span>CLINICAL SIGN-OFF</span>
        <h3>覆核並發布 Safety 規則</h3>
      </div>
      <button type="button" class="secondary-action" @click="emit('cancel')">
        放棄草稿
      </button>
    </header>

    <div v-if="changedGroups.length" class="change-preview">
      <strong>本次變更（{{ changedGroups.length }}）</strong>
      <ul>
        <li v-for="group in changedGroups" :key="group.original_label">
          {{ group.original_label }} → {{ group.label }}
        </li>
      </ul>
    </div>
    <p v-else class="governance-note">尚未修改任何 Safety 規則。</p>

    <div class="signoff-grid">
      <label>
        變更理由
        <textarea
          v-model="changeNote"
          rows="3"
          maxlength="500"
          placeholder="例如：依急診科會議調整視力警訊用語"
        />
      </label>
      <label>
        輸入「{{ confirmationText }}」確認
        <input v-model="confirmation" :placeholder="confirmationText" />
      </label>
    </div>

    <p v-if="validationError" class="validation-error">
      {{ validationError }}
    </p>
    <div class="publish-actions">
      <p>發布後會保存前版快照、檢查版本衝突，並立即套用至後續新問診。</p>
      <button type="submit" class="primary-action" :disabled="!canSave || saving">
        {{ saving ? '驗證與發布中…' : '簽署並發布 Safety 規則' }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.publish-panel {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid color-mix(in srgb, var(--blue) 45%, var(--border));
  border-radius: 12px;
  background: color-mix(in srgb, var(--blue-soft) 35%, var(--surface-1));
}

.publish-panel > header,
.publish-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.publish-panel h3 {
  margin: 4px 0 5px;
}

.publish-panel header span {
  color: var(--blue);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.primary-action,
.secondary-action {
  padding: 9px 13px;
  border-radius: 8px;
  cursor: pointer;
}

.primary-action {
  border: 0;
  background: var(--blue);
  color: #fff;
  font-weight: 700;
}

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.secondary-action {
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text);
}

.change-preview {
  margin: 14px 0;
  padding: 12px;
  border-radius: 8px;
  background: var(--surface-1);
}

.change-preview ul {
  max-height: 150px;
  margin: 8px 0 0;
  padding-left: 20px;
  overflow: auto;
}

.governance-note,
.validation-error {
  margin: 12px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--muted);
}

.validation-error {
  background: #fff0f1;
  color: var(--danger);
}

.signoff-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 12px;
}

.signoff-grid label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.signoff-grid input,
.signoff-grid textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  padding: 8px 9px;
  font: inherit;
}

.publish-actions {
  margin-top: 15px;
}

.publish-actions p {
  margin: 0;
  color: var(--muted);
}

@media (max-width: 720px) {
  .publish-panel > header,
  .publish-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .signoff-grid {
    grid-template-columns: 1fr;
  }
}
</style>
