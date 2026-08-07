<script setup>
import { computed, nextTick, ref, watch } from 'vue'

import {
  composeQuestionAnswer,
  isQuestionAnswerReady,
  toggleQuestionOption,
} from '../services/questionnaire.js'

const props = defineProps({
  spec: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
  sending: { type: Boolean, default: false },
  maxBirthDate: { type: String, required: true },
})

const emit = defineEmits(['submit'])

const selectedOptions = ref([])
const otherText = ref('')
const quickOption = ref('')
const durationNumber = ref('')
const durationUnit = ref('')
const dateValue = ref('')
const choiceControls = ref(null)
const dateInput = ref(null)
const durationInput = ref(null)

const kind = computed(() => props.spec?.kind ?? 'text')
const answerState = computed(() => ({
  text: dateValue.value,
  selectedOptions: selectedOptions.value,
  otherText: otherText.value,
  quickOption: quickOption.value,
  durationNumber: durationNumber.value,
  durationUnit: durationUnit.value,
}))
const answerReady = computed(() =>
  isQuestionAnswerReady(props.spec, answerState.value),
)

watch(
  () => props.spec,
  (spec) => {
    selectedOptions.value = []
    otherText.value = ''
    quickOption.value = ''
    durationNumber.value = ''
    durationUnit.value =
      spec?.units?.find((unit) => unit === '小時前') ||
      spec?.units?.[0] ||
      ''
    dateValue.value = ''
  },
  { immediate: true },
)

function selectOption(option) {
  selectedOptions.value = toggleQuestionOption(
    selectedOptions.value,
    option,
    props.spec,
  )
  otherText.value = ''
}

function handleOtherInput() {
  if (otherText.value.trim()) {
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

function submit() {
  if (props.disabled || !answerReady.value) return
  emit('submit', composeQuestionAnswer(props.spec, answerState.value))
}

function focus() {
  nextTick(() => {
    if (kind.value === 'choice') {
      choiceControls.value
        ?.querySelector('input[type="radio"], input[type="checkbox"]')
        ?.focus()
    } else if (kind.value === 'date') {
      dateInput.value?.focus()
    } else if (kind.value === 'duration') {
      durationInput.value?.focus()
    }
  })
}

defineExpose({ focus })
</script>

<template>
  <section
    v-if="kind === 'duration' && spec"
    class="question-control-card duration-control"
  >
    <div class="duration-section">
      <span class="control-label">快捷選擇</span>
      <div class="duration-quick-grid">
        <button
          v-for="option in spec.quick_options"
          :key="option"
          type="button"
          class="duration-quick-option"
          :class="{ selected: quickOption === option }"
          :disabled="disabled"
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
          :disabled="disabled"
          @input="handleDurationNumber"
          @keydown.enter.prevent="submit"
        />
      </label>
      <label>
        <span class="control-label">單位</span>
        <select
          v-model="durationUnit"
          :disabled="disabled"
          @change="handleDurationUnit"
        >
          <option v-for="unit in spec.units" :key="unit" :value="unit">
            {{ unit }}
          </option>
        </select>
      </label>
    </div>
    <label v-if="spec.allow_other" class="other-answer">
      <span>{{ spec.other_label }}</span>
      <input
        v-model="otherText"
        type="text"
        placeholder="例如：昨天晚上開始、剛剛開始"
        :disabled="disabled"
        @input="handleDurationOther"
        @keydown.enter.prevent="submit"
      />
    </label>
    <button
      class="confirm-question-button"
      type="button"
      :disabled="disabled || !answerReady"
      @click="submit"
    >
      {{ sending ? '傳送中…' : '確認開始時間' }}
    </button>
  </section>

  <section v-else-if="kind === 'choice' && spec" class="question-control-card">
    <div ref="choiceControls" class="choice-grid">
      <label
        v-for="option in spec.options"
        :key="option"
        class="choice-option"
        :class="{ selected: selectedOptions.includes(option) }"
      >
        <input
          :type="spec.multiple ? 'checkbox' : 'radio'"
          name="question-choice"
          :checked="selectedOptions.includes(option)"
          :disabled="disabled"
          @click.prevent="selectOption(option)"
        />
        <span>{{ option }}</span>
      </label>
    </div>
    <label v-if="spec.allow_other" class="other-answer">
      <span>{{ spec.other_label }}</span>
      <input
        v-model="otherText"
        type="text"
        placeholder="找不到合適選項時可直接輸入"
        :disabled="disabled"
        @input="handleOtherInput"
        @keydown.enter.prevent="submit"
      />
    </label>
    <button
      class="confirm-question-button"
      type="button"
      :disabled="disabled || !answerReady"
      @click="submit"
    >
      {{ sending ? '傳送中…' : '確認答案' }}
    </button>
  </section>

  <section
    v-else-if="kind === 'date' && spec"
    class="question-control-card date-control"
  >
    <label>
      <span>出生日期</span>
      <input
        ref="dateInput"
        v-model="dateValue"
        type="date"
        :max="maxBirthDate"
        :disabled="disabled"
        @keydown.enter.prevent="submit"
      />
    </label>
    <button
      class="confirm-question-button"
      type="button"
      :disabled="disabled || !answerReady"
      @click="submit"
    >
      {{ sending ? '傳送中…' : '確認日期' }}
    </button>
  </section>
</template>

<style scoped>
.question-control-card {
  display: flex;
  width: min(100%, 720px);
  align-self: flex-start;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-1);
  box-shadow: 0 4px 14px rgb(37 67 91 / 5%);
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
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.04em;
}

.duration-quick-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.duration-quick-option {
  min-height: 48px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text);
  cursor: pointer;
  font-size: 15px;
}

.duration-quick-option:hover,
.duration-quick-option.selected {
  border-color: rgb(10 146 126 / 65%);
  background: var(--green-soft);
  color: var(--green);
}

.duration-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
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
  min-height: 48px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 15px;
}

.choice-option {
  display: flex;
  min-height: 50px;
  align-items: center;
  gap: 9px;
  padding: 11px 13px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  cursor: pointer;
  font-size: 15px;
  line-height: 1.45;
}

.choice-option:hover,
.choice-option.selected {
  border-color: rgb(10 146 126 / 65%);
  background: var(--green-soft);
}

.choice-option input {
  width: 19px;
  height: 19px;
  flex: 0 0 19px;
  accent-color: var(--green);
}

.other-answer,
.date-control label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
}

.other-answer input,
.date-control input {
  width: 100%;
  min-height: 48px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text);
  font-family: 'Noto Sans TC', sans-serif;
  font-size: 15px;
}

.date-control input {
  color-scheme: light;
}

.confirm-question-button {
  width: 100%;
  min-height: 50px;
  border-radius: 8px;
  background: var(--green);
  color: white;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
}

.confirm-question-button:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}

@media (max-width: 760px) {
  .choice-grid {
    grid-template-columns: 1fr;
  }

  .duration-quick-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .duration-custom-row {
    grid-template-columns: 1fr;
  }
}
</style>
