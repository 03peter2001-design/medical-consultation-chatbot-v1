<script setup>
import { computed } from 'vue'

import {
  parseStructuredNoteBlocks,
  splitStructuredNote,
} from '../services/structuredNote.js'
import SourceTags from './SourceTags.vue'

const props = defineProps({
  text: { type: String, required: true },
  sources: { type: Array, default: () => [] },
  hideEmr: { type: Boolean, default: false },
})

const displayText = computed(() => {
  if (!props.hideEmr) return props.text
  return (
    splitStructuredNote(props.text).clinicalDecision ||
    '目前沒有其他臨床決策內容。'
  )
})

const parsedReport = computed(() => parseStructuredNoteBlocks(props.text))
const visibleSections = computed(() =>
  parsedReport.value.sections.filter(
    (section) => !props.hideEmr || section.key !== 'emr',
  ),
)
</script>

<template>
  <section
    class="structured-report"
    :aria-label="hideEmr ? '臨床決策問題總結' : '六段式臨床問題總結'"
  >
    <header class="report-heading">
      <div class="report-mark" aria-hidden="true">AI</div>
      <div>
        <small>Gemini 生成 · 待醫師確認</small>
        <h2>
          {{ hideEmr ? '臨床決策問題總結' : '六段式臨床問題總結' }}
        </h2>
      </div>
      <strong v-if="visibleSections.length">
        {{ visibleSections.length }} 個重點區塊
      </strong>
    </header>

    <div
      v-if="visibleSections.length"
      class="question-grid"
      role="list"
      aria-label="臨床問題總結"
    >
      <article
        v-for="(section, index) in visibleSections"
        :key="`${section.key}-${index}`"
        class="question-card"
        :class="[
          `tone-${section.tone}`,
          { wide: section.key === 'emr' || section.key === 'imaging' },
        ]"
        role="listitem"
      >
        <header>
          <span class="question-number" aria-hidden="true">
            {{ String(index + 1).padStart(2, '0') }}
          </span>
          <div>
            <small>{{ section.question }}</small>
            <h3>{{ section.title }}</h3>
          </div>
        </header>
        <pre>{{ section.content }}</pre>
      </article>
    </div>

    <pre v-else class="report-fallback">{{ displayText }}</pre>

    <p v-if="parsedReport.footer" class="report-provenance">
      {{ parsedReport.footer }}
    </p>
    <SourceTags :sources="sources" />
  </section>
</template>

<style scoped>
.structured-report {
  align-self: stretch;
  overflow: hidden;
  border: 1px solid #b8cde0;
  border-radius: 12px;
  background: #f8fbfd;
  box-shadow: 0 10px 28px rgb(25 62 94 / 10%);
  animation: pop-in 0.3s ease;
}

.report-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 17px 19px;
  border-bottom: 1px solid #cbdbe8;
  background: linear-gradient(115deg, #eaf4fb 0%, #f7fbfd 55%, #eef8f5 100%);
}

.report-mark {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 9px;
  background: #245f98;
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.report-heading > div:nth-child(2) {
  min-width: 0;
  flex: 1;
}

.report-heading small {
  color: #5c7489;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.report-heading h2 {
  margin-top: 2px;
  color: #173b5b;
  font-size: clamp(18px, 2vw, 22px);
  line-height: 1.25;
}

.report-heading > strong {
  flex: 0 0 auto;
  padding: 5px 9px;
  border: 1px solid #afc8db;
  border-radius: 999px;
  background: rgb(255 255 255 / 78%);
  color: #38617f;
  font-size: 11px;
}

.question-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 16px;
}

.question-card {
  --card-accent: #3977ad;
  min-width: 0;
  overflow: hidden;
  border: 1px solid #d5e0e9;
  border-top: 4px solid var(--card-accent);
  border-radius: 9px;
  background: #fff;
  box-shadow: 0 4px 12px rgb(32 66 94 / 7%);
}

.question-card.wide {
  grid-column: 1 / -1;
}

.question-card > header {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 13px 14px 10px;
  border-bottom: 1px solid #e3eaf0;
  background: color-mix(in srgb, var(--card-accent) 7%, #fff);
}

.question-number {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  place-items: center;
  border-radius: 7px;
  background: var(--card-accent);
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 800;
}

.question-card header > div {
  min-width: 0;
}

.question-card small {
  display: block;
  color: #64788a;
  font-size: 11px;
  font-weight: 650;
  line-height: 1.35;
}

.question-card h3 {
  margin-top: 2px;
  color: #203b51;
  font-size: 17px;
  line-height: 1.35;
}

.question-card pre,
.report-fallback {
  margin: 0;
  color: #1c3347;
  font-family: 'Noto Sans TC', sans-serif;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.question-card pre {
  padding: 13px 14px 15px;
}

.report-fallback {
  padding: 16px 18px;
}

.tone-emr {
  --card-accent: #087f6d;
}

.tone-danger {
  --card-accent: #c6404f;
}

.tone-physical {
  --card-accent: #2d846e;
}

.tone-laboratory {
  --card-accent: #aa6e16;
}

.tone-imaging {
  --card-accent: #6858a8;
}

.report-provenance {
  margin: 0 16px 15px;
  padding: 10px 12px;
  border: 1px solid #dce5ec;
  border-radius: 7px;
  background: #fff;
  color: #6a7d8d;
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
}

:deep(.source-list) {
  margin: 0 16px 16px;
}

@media (max-width: 720px) {
  .report-heading {
    align-items: flex-start;
    padding: 14px;
  }

  .report-heading > strong {
    display: none;
  }

  .question-grid {
    grid-template-columns: 1fr;
    padding: 12px;
  }

  .question-card.wide {
    grid-column: auto;
  }

  .question-card h3 {
    font-size: 16px;
  }
}
</style>
