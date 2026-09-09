<script setup>
import { computed, ref, watch } from 'vue'

import {
  BODY_PAIN_REGIONS,
  getPainRegions,
  getPainMapPreset,
  togglePainRegionSelection,
} from '../data/bodyPainRegions.js'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  highlightedRegionIds: { type: Array, default: () => [] },
  readonly: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
  showRegionOptions: { type: Boolean, default: true },
  preset: {
    type: Object,
    default: () => getPainMapPreset(),
  },
})

const emit = defineEmits(['update:modelValue'])

const initialView =
  getPainRegions(props.modelValue)[0]?.view === 'back' ? 'back' : 'front'
const activeView = ref(initialView)
const allowedRegionSet = computed(
  () => new Set(props.preset.allowedRegionIds || []),
)
const selectedSet = computed(() => new Set(props.modelValue))
const highlightedSet = computed(() => new Set(props.highlightedRegionIds))
const selectedRegions = computed(() =>
  getPainRegions(props.modelValue).filter(
    (region) => props.readonly || allowedRegionSet.value.has(region.id),
  ),
)
const highlightedRegions = computed(() =>
  getPainRegions(props.highlightedRegionIds).filter(
    (region) =>
      !selectedSet.value.has(region.id) &&
      (props.readonly || allowedRegionSet.value.has(region.id)),
  ),
)
const visibleRegions = computed(() =>
  BODY_PAIN_REGIONS.filter(
    (region) =>
      region.view === activeView.value &&
      (props.readonly || allowedRegionSet.value.has(region.id)),
  ),
)
const counts = computed(() => ({
  front: [...selectedRegions.value, ...highlightedRegions.value].filter(
    (region) => region.view === 'front',
  ).length,
  back: [...selectedRegions.value, ...highlightedRegions.value].filter(
    (region) => region.view === 'back',
  ).length,
}))

const availableViews = computed(() =>
  ['front', 'back'].filter((view) =>
    BODY_PAIN_REGIONS.some(
      (region) =>
        region.view === view &&
        (props.readonly || allowedRegionSet.value.has(region.id)),
    ),
  ),
)

watch(
  () => props.modelValue,
  (value) => {
    if (!value.length) return
    const currentHasSelection = getPainRegions(value).some(
      (region) => region.view === activeView.value,
    )
    if (!currentHasSelection && props.readonly) {
      activeView.value = getPainRegions(value)[0]?.view || 'front'
    }
  },
)

watch(
  () => props.preset.key,
  () => {
    const nextView = availableViews.value.includes(activeView.value)
      ? activeView.value
      : availableViews.value[0] || 'front'
    activeView.value = nextView
    if (props.readonly) return
    const allowedSelections = props.modelValue.filter((id) =>
      allowedRegionSet.value.has(id),
    )
    if (allowedSelections.length !== props.modelValue.length) {
      emit('update:modelValue', allowedSelections)
    }
  },
)

function toggleRegion(region) {
  if (props.readonly) return
  const next = togglePainRegionSelection(
    props.modelValue,
    region.id,
    props.preset.allowedRegionIds,
  )
  emit('update:modelValue', next)
}

function handleRegionKeydown(event, region) {
  if (props.readonly || !['Enter', ' '].includes(event.key)) return
  event.preventDefault()
  toggleRegion(region)
}
</script>

<template>
  <section
    class="body-map"
    :class="[
      { readonly, compact },
      `focus-${preset.key || 'all'}`,
    ]"
    aria-label="人體疼痛位置圖"
  >
    <div class="map-toolbar">
      <div class="view-tabs" role="tablist" aria-label="切換人體正背面">
        <button
          v-for="view in availableViews"
          :key="view"
          type="button"
          role="tab"
          :aria-selected="activeView === view"
          :class="{ active: activeView === view }"
          @click="activeView = view"
        >
          {{ view === 'front' ? '正面' : '背面' }}
          <span v-if="counts[view]">{{ counts[view] }}</span>
        </button>
      </div>
      <button
        v-if="!readonly && modelValue.length"
        class="clear-map"
        type="button"
        @click="emit('update:modelValue', [])"
      >
        清除
      </button>
    </div>

    <div class="figure-stage">
      <span class="side-label side-right">病人右側</span>
      <span class="side-label side-left">病人左側</span>
      <svg
        :viewBox="preset.viewBox || '0 0 220 450'"
        role="img"
        :aria-label="activeView === 'front' ? '人體正面疼痛位置' : '人體背面疼痛位置'"
      >
        <g class="body-silhouette" aria-hidden="true">
          <circle cx="110" cy="39" r="29" />
          <path d="M94 66h32l4 20 29 8 16 66 17 78-20 5-22-78-7-30 8 108-8 82 17 112h-29l-19-111h-4L89 437H60l17-112-8-82 8-108-7 30-22 78-20-5 17-78 16-66 29-8z" />
        </g>

        <g :class="{ interactive: !readonly }">
          <path
            v-for="region in visibleRegions"
            :key="region.id"
            class="pain-region"
            :class="{
              selected: selectedSet.has(region.id),
              highlighted:
                !selectedSet.has(region.id) && highlightedSet.has(region.id),
            }"
            :data-region-id="region.id"
            :d="region.d"
            :tabindex="readonly ? undefined : 0"
            :role="readonly ? undefined : 'button'"
            :aria-label="region.label"
            :aria-pressed="readonly ? undefined : selectedSet.has(region.id)"
            @click="toggleRegion(region)"
            @keydown="handleRegionKeydown($event, region)"
          >
            <title>{{ region.label }}</title>
          </path>
        </g>

        <g
          v-if="(preset.key || 'all') === 'all'"
          class="orientation"
          aria-hidden="true"
        >
          <text x="28" y="438">R</text>
          <text x="184" y="438">L</text>
        </g>
      </svg>
    </div>

    <fieldset
      v-if="!readonly && showRegionOptions"
      class="region-options"
    >
      <legend>
        {{ activeView === 'front' ? '正面' : '背面' }}部位選項
      </legend>
      <div class="region-option-grid">
        <label
          v-for="region in visibleRegions"
          :key="region.id"
          class="region-option"
          :class="{
            selected: selectedSet.has(region.id),
            highlighted:
              !selectedSet.has(region.id) && highlightedSet.has(region.id),
          }"
          :data-region-id="region.id"
        >
          <input
            type="checkbox"
            :checked="selectedSet.has(region.id)"
            @change="toggleRegion(region)"
          />
          <span>{{ region.label }}</span>
        </label>
      </div>
    </fieldset>

    <div v-if="selectedRegions.length" class="selected-regions">
      <span
        v-for="region in selectedRegions"
        :key="region.id"
        class="region-chip"
      >
        <i aria-hidden="true" />
        {{ region.label }}
      </span>
    </div>
    <p v-else-if="highlightedRegions.length" class="map-guidance">
      已依下方問卷選項標示可能範圍；可直接點圖指定更精確的位置。
    </p>
    <p v-else class="map-empty">
      {{ readonly ? '未記錄圖像化疼痛位置' : '尚未選擇疼痛位置' }}
    </p>
  </section>
</template>

<style scoped>
.body-map {
  width: min(100%, 390px);
  overflow: hidden;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background:
    radial-gradient(circle at 50% 38%, rgb(37 104 178 / 5%), transparent 46%),
    var(--surface-1);
}

.map-toolbar {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  padding: 7px;
  border-bottom: 1px solid var(--border);
}

.view-tabs {
  display: flex;
  gap: 4px;
}

.view-tabs button,
.clear-map {
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.view-tabs button {
  display: flex;
  min-width: 68px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 38px;
  padding: 7px 11px;
}

.view-tabs button.active {
  border-color: var(--border-strong);
  background: var(--blue-soft);
  color: var(--text);
}

.view-tabs button span {
  display: grid;
  width: 17px;
  height: 17px;
  place-items: center;
  border-radius: 50%;
  background: var(--danger);
  color: white;
  font-size: 9px;
}

.clear-map {
  min-height: 38px;
  padding: 7px 10px;
}

.clear-map:hover {
  color: var(--danger);
}

.figure-stage {
  position: relative;
  display: flex;
  height: 350px;
  align-items: center;
  justify-content: center;
  padding: 10px 34px 6px;
}

.focus-headache .figure-stage {
  height: 300px;
}

.focus-chest .figure-stage,
.focus-abdomen .figure-stage {
  height: 320px;
}

.figure-stage svg {
  width: auto;
  height: 100%;
  overflow: hidden;
}

.body-silhouette {
  fill: #e7eef5;
  stroke: #7895ad;
  stroke-linejoin: round;
  stroke-width: 1.5;
}

.pain-region {
  fill: rgb(37 104 178 / 6%);
  stroke: rgb(37 104 178 / 25%);
  stroke-width: 1.2;
  transition:
    fill 0.16s ease,
    filter 0.16s ease,
    stroke 0.16s ease;
}

.interactive .pain-region {
  cursor: pointer;
}

.interactive .pain-region:hover,
.interactive .pain-region:focus-visible {
  fill: rgb(10 146 126 / 20%);
  stroke: var(--green);
  outline: none;
}

.pain-region.selected {
  fill: rgb(198 64 79 / 62%);
  filter: drop-shadow(0 0 6px rgb(198 64 79 / 28%));
  stroke: #ad2f3e;
  stroke-width: 2;
}

.pain-region.highlighted {
  fill: rgb(10 146 126 / 24%);
  stroke: var(--green);
  stroke-width: 1.8;
}

.side-label {
  position: absolute;
  top: 14px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.08em;
  writing-mode: vertical-rl;
}

.side-right {
  left: 12px;
}

.side-left {
  right: 12px;
}

.orientation {
  fill: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.region-options {
  min-width: 0;
  margin: 0;
  padding: 12px;
  border: 0;
  border-top: 1px solid var(--border);
}

.region-options legend {
  padding: 0 5px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.region-option-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.region-option {
  display: flex;
  min-width: 0;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-2);
  cursor: pointer;
  font-size: 13px;
  line-height: 1.35;
}

.region-option:hover {
  border-color: var(--green);
}

.region-option.selected {
  border-color: rgb(198 64 79 / 45%);
  background: #fdecee;
}

.region-option.highlighted {
  border-color: rgb(10 146 126 / 45%);
  background: var(--green-soft);
}

.region-option input {
  width: 17px;
  height: 17px;
  flex: 0 0 auto;
  accent-color: var(--danger);
}

.region-option:focus-within {
  outline: 2px solid var(--green);
  outline-offset: 2px;
}

.selected-regions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--border);
}

.region-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid rgb(198 64 79 / 30%);
  border-radius: 999px;
  background: #fdecee;
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.region-chip i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--danger);
}

.map-empty,
.map-guidance {
  padding: 10px 12px 12px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  text-align: center;
}

.map-guidance {
  color: var(--green);
}

.compact {
  width: 300px;
}

.compact .figure-stage {
  height: 270px;
}

@media (max-width: 480px) {
  .figure-stage {
    height: 310px;
  }

  .region-option-grid {
    grid-template-columns: 1fr;
  }
}
</style>
