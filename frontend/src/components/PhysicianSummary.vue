<script setup>
defineProps({
  rows: { type: Array, default: () => [] },
  report: { type: String, default: '' },
})
</script>

<template>
  <section aria-labelledby="physician-summary-title">
    <header>
      <div>
        <span>CLINICIAN NOTE</span>
        <h3 id="physician-summary-title">醫師摘要</h3>
      </div>
      <strong>資料彙整草稿 · 待醫師確認</strong>
    </header>
    <dl class="physician-summary-rows">
      <div v-for="row in rows" :key="row.key">
        <dt>
          <b>{{ row.key }}</b>
          <!-- <span>{{ row.label }}</span> -->
        </dt>
        <dd>{{ row.value }}</dd>
        <small>{{ row.source }}</small>
      </div>
    </dl>
    <details class="ai-overview">
      <summary>
        <span>
          <small>AI-generated medical records</small>
          <strong>AI 合成病歷</strong>
        </span>
        <em>展開</em>
      </summary>
      <!-- <p>{{ report || '尚未產生醫師速覽摘要' }}</p> -->
      <p>
      <div v-for="row in rows" :key="row.key">
          <b>{{ row.key }}</b><br/>
          <!-- <span>{{ row.label }}</span> -->
        {{ row.value }}
      </div>
      </p>
    </details>
  </section>
</template>

<style scoped>
section {
  overflow: hidden;
  border: 1px solid #cbd7e1;
  border-radius: 7px;
  background: #fff;
}

section > header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 16px;
  border-bottom: 1px solid #dbe4ec;
}

section > header span,
section > header > strong {
  color: #6b7f92;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
}

section > header h3 {
  color: #17324d;
  font-size: 18px;
}

section > header > strong {
  color: #b83243;
  font-family: 'Noto Sans TC', system-ui, sans-serif;
  letter-spacing: 0;
}

.physician-summary-rows > div {
  display: grid;
  min-width: 0;
  grid-template-columns: 112px minmax(0, 1fr) auto;
  align-items: start;
  gap: 12px;
  padding: 11px 16px;
  border-bottom: 1px solid #e2e9ef;
}

.physician-summary-rows dt {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.physician-summary-rows dt b {
  color: #2568b2;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.physician-summary-rows dt span,
.physician-summary-rows small {
  color: #6b7f92;
  font-size: 11px;
}

.physician-summary-rows dd {
  min-width: 0;
  color: #2b4256;
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.physician-summary-rows small {
  white-space: nowrap;
}

.ai-overview summary {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 16px;
  cursor: pointer;
  list-style: none;
}

.ai-overview summary::-webkit-details-marker {
  display: none;
}

.ai-overview summary span {
  display: grid;
  gap: 1px;
}

.ai-overview summary small {
  color: #6b7f92;
  font-size: 10px;
  letter-spacing: 0.05em;
}

.ai-overview summary strong {
  color: #2b4256;
  font-size: 14px;
}

.ai-overview summary em {
  color: #2568b2;
  font-size: 12px;
  font-style: normal;
  font-weight: 650;
}

.ai-overview > p {
  padding: 13px 16px;
  border-top: 1px solid #e2e9ef;
  color: #40576b;
  line-height: 1.75;
  white-space: pre-wrap;
}

@media (max-width: 700px) {
  section > header {
    display: grid;
    align-items: start;
  }

  .physician-summary-rows > div {
    grid-template-columns: 80px minmax(0, 1fr);
    padding: 11px 12px;
  }

  .physician-summary-rows small {
    grid-column: 2;
  }

  .ai-overview summary {
    padding: 11px 12px;
  }
}
</style>
