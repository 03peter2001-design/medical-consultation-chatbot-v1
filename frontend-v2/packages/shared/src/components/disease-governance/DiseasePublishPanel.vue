<script setup>
import { actionLabel, changeDetail } from '../../composables/diseaseGovernance.js'

defineProps({
  canPublish: { type: Boolean, required: true },
  changeNote: { type: String, default: '' },
  changes: { type: Array, default: () => [] },
  confirmation: { type: String, default: '' },
  confirmationText: { type: String, required: true },
  reviewer: { type: String, default: '' },
  routeLabel: { type: String, required: true },
  saving: { type: Boolean, required: true },
})

const emit = defineEmits([
  'cancel',
  'publish',
  'update:changeNote',
  'update:confirmation',
  'update:reviewer',
])
</script>

<template>
  <form class="publish-panel" @submit.prevent="emit('publish')">
    <header>
      <div>
        <span>CLINICAL SIGN-OFF</span>
        <h3>覆核並發布 {{ routeLabel }}疾病表</h3>
      </div>
      <button type="button" class="secondary-action" @click="emit('cancel')">放棄草稿</button>
    </header>

    <div v-if="changes.length" class="change-preview">
      <strong>本次變更（{{ changes.length }}）</strong>
      <ul>
        <li
          v-for="change in changes"
          :key="`${change.profile.id}-${change.fact || change.safetyGroup?.original_label}-${change.action}`"
        >
          <b :class="`action-${change.action}`">{{ actionLabel(change) }}</b>
          {{ change.profile.name }}
          <template v-if="change.fact"> · <code>{{ change.fact }}</code></template>
          ：{{ changeDetail(change) }}
        </li>
      </ul>
    </div>
    <p v-else class="governance-note">尚未新增、移除或調整任何標籤。</p>

    <div class="signoff-grid">
      <label>
        審查醫師姓名
        <input
          :value="reviewer"
          maxlength="80"
          placeholder="例如：王大明醫師"
          @input="emit('update:reviewer', $event.target.value)"
        />
      </label>
      <label>
        變更理由與依據
        <textarea
          :value="changeNote"
          rows="3"
          maxlength="500"
          placeholder="例如：依急診科共識調整暈厥票數與高風險觸發綁定"
          @input="emit('update:changeNote', $event.target.value)"
        />
      </label>
      <label>
        輸入「{{ confirmationText }}」確認
        <input
          :value="confirmation"
          :placeholder="confirmationText"
          @input="emit('update:confirmation', $event.target.value)"
        />
      </label>
    </div>

    <div class="publish-actions">
      <p>發布後將保存前版、投票差異與 Safety 綁定變更，並產生新疾病表版本。</p>
      <button type="submit" class="primary-action" :disabled="!canPublish || saving">
        {{ saving ? '驗證與發布中…' : '簽署並發布疾病規則' }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.publish-panel {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid color-mix(in srgb, var(--green) 45%, var(--border));
  border-radius: 12px;
  background: color-mix(in srgb, var(--green-soft) 24%, var(--surface-1));
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
  color: var(--green);
  font: 700 11px/1.2 'JetBrains Mono', monospace;
  letter-spacing: 0.12em;
}

.primary-action,
.secondary-action {
  border-radius: 8px;
  padding: 9px 13px;
  cursor: pointer;
}

.primary-action {
  border: 0;
  background: var(--green);
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
  max-height: 180px;
  margin: 8px 0 0;
  padding-left: 20px;
  overflow: auto;
}

.change-preview li b {
  display: inline-block;
  min-width: 32px;
  margin-right: 4px;
}

.change-preview code {
  color: var(--green);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.action-removed,
.action-safety_removed {
  color: var(--warning) !important;
}

.action-added,
.action-safety_added {
  color: var(--green) !important;
}

.governance-note {
  margin: 12px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--muted);
}

.signoff-grid {
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
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
  .publish-actions,
  .publish-panel > header {
    align-items: stretch;
    flex-direction: column;
  }

  .signoff-grid {
    grid-template-columns: 1fr;
  }
}
</style>
