<script setup>
import { hasSafetyGroup } from '../../composables/diseaseGovernance.js'

defineProps({
  editing: { type: Boolean, required: true },
  groups: { type: Array, default: () => [] },
  profile: { type: Object, required: true },
  search: { type: String, default: '' },
})

const emit = defineEmits(['toggle-group', 'update:search'])
</script>

<template>
  <section class="safety-link-manager">
    <div v-if="!profile.must_not_miss" class="governance-note">
      此疾病未標記為「不能漏診」，因此不會綁定自動 urgent 觸發器。普通標籤仍只影響疾病票數。
    </div>
    <template v-else>
      <div class="safety-link-intro">
        <div>
          <strong>緊急觸發器</strong>
          <p>命中下列核准條件時，會先於疾病投票將問診標記為 urgent。</p>
        </div>
        <label>
          搜尋觸發器
          <input
            :value="search"
            type="search"
            placeholder="例如：昏厥、呼吸困難、semantic"
            @input="emit('update:search', $event.target.value)"
          />
        </label>
      </div>

      <div class="safety-trigger-grid">
        <article
          v-for="group in groups"
          :key="group.original_label"
          :class="{ selected: hasSafetyGroup(profile, group) }"
        >
          <header>
            <button
              type="button"
              class="safety-toggle"
              :disabled="!editing"
              :aria-pressed="hasSafetyGroup(profile, group)"
              @click="emit('toggle-group', group)"
            >
              {{ hasSafetyGroup(profile, group) ? '✓ 已綁定' : '+ 綁定' }}
            </button>
            <div>
              <strong>{{ group.label }}</strong>
              <small>{{ group.rules.length }} 條固定規則</small>
            </div>
          </header>
          <div class="trigger-rule-codes">
            <code v-for="rule in group.rules" :key="rule.code">{{ rule.code }}</code>
          </div>
          <p>{{ group.possible_conditions.join('、') }}</p>
        </article>
      </div>
      <p v-if="!groups.length" class="empty-state">找不到緊急觸發器。</p>
      <p class="source-note">
        Safety 綁定使用穩定 rule code，不會因疾病或顯示標籤改名而斷開。
      </p>
    </template>
  </section>
</template>

<style scoped>
.safety-link-manager {
  margin-top: 14px;
}

.governance-note {
  margin: 12px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--muted);
}

.safety-link-intro {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.safety-link-intro p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
}

.safety-link-intro > label {
  display: grid;
  flex: 0 1 360px;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}

.safety-link-intro input {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  padding: 8px 9px;
  font: inherit;
}

.safety-trigger-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  max-height: 520px;
  padding-right: 3px;
  overflow-y: auto;
}

.safety-trigger-grid article {
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-1);
}

.safety-trigger-grid article.selected {
  border-color: color-mix(in srgb, var(--danger) 38%, var(--border));
  background: color-mix(in srgb, #fff0f1 42%, var(--surface-1));
}

.safety-trigger-grid article > header {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}

.safety-trigger-grid article > header > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.safety-trigger-grid article small,
.safety-trigger-grid article > p,
.source-note {
  color: var(--muted);
  font-size: 11px;
}

.safety-trigger-grid article > p {
  margin-top: 8px;
}

.safety-toggle {
  flex: 0 0 auto;
  min-width: 70px;
  padding: 6px 7px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--muted);
  cursor: pointer;
  font-size: 11px;
}

.safety-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.safety-trigger-grid article.selected .safety-toggle {
  border-color: var(--danger);
  background: var(--danger);
  color: #fff;
}

.trigger-rule-codes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 9px;
}

.trigger-rule-codes code {
  max-width: 100%;
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--blue);
  overflow-wrap: anywhere;
  font-size: 9px;
}

.source-note {
  margin: 12px 0 0;
}

.empty-state {
  padding: 18px;
  text-align: center;
  color: var(--muted);
}

@media (max-width: 980px) {
  .safety-trigger-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .safety-link-intro {
    align-items: stretch;
    flex-direction: column;
  }

  .safety-link-intro > label {
    flex-basis: auto;
  }
}
</style>
