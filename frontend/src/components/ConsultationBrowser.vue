<script setup>
defineProps({
  records: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  deletingQueueNumber: { type: String, default: '' },
  loadedQueueNumber: { type: String, default: '' },
  patientLoading: { type: Boolean, default: false },
  hasMore: { type: Boolean, default: false },
})

const emit = defineEmits(['refresh', 'select', 'delete', 'load-more'])
const search = defineModel('search', { type: String, default: '' })

function typeLabel(type) {
  return (
    {
      chest: '胸痛',
      headache: '頭痛',
      abdomen: '腹痛',
      other: '其他',
    }[type] || type || '未分類'
  )
}

function workflowLabel(status) {
  return (
    {
      completed: '已完成',
      manual_handoff: '安全轉交',
      synthetic_test: '測試資料',
      summary_pending: 'AI 摘要產生中',
      summary_ready: 'AI 摘要完成',
      summary_partial: 'AI 摘要部分完成',
      summary_failed: 'AI 摘要失敗',
    }[status] || status || '已完成'
  )
}

function formatCaseDate(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '時間未提供'
  return new Intl.DateTimeFormat('zh-TW', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}
</script>

<template>
  <aside class="case-browser" aria-label="病例資料庫">
    <div class="case-browser-header">
      <div>
        <span class="case-browser-kicker">CONSULTATIONS</span>
        <h2>病例資料庫</h2>
      </div>
      <button
        class="case-refresh"
        :disabled="loading"
        aria-label="重新整理病例"
        title="重新整理病例"
        @click="emit('refresh')"
      >
        ↻
      </button>
    </div>

    <div class="case-search">
      <span aria-hidden="true">⌕</span>
      <input
        v-model="search"
        type="search"
        placeholder="搜尋姓名、編號或主訴"
        aria-label="搜尋病例"
      />
      <button
        v-if="search"
        aria-label="清除搜尋"
        @click="search = ''"
      >
        ✕
      </button>
    </div>

    <div class="case-summary">
      <span>{{ search ? '搜尋結果' : '所有病例' }}</span>
      <strong>{{ total }}</strong>
    </div>

    <div class="case-list">
      <div v-if="loading && !records.length" class="case-state">
        <span class="case-loader" />
        正在讀取病例…
      </div>
      <div v-else-if="error" class="case-state case-error">
        無法載入病例：{{ error }}
        <button @click="emit('refresh')">再試一次</button>
      </div>
      <div v-else-if="!records.length" class="case-state">
        {{ search ? '找不到符合條件的病例' : '目前尚無病例' }}
      </div>

      <article
        v-for="record in records"
        :key="record.queue_number"
        class="case-card"
        :class="{
          active: loadedQueueNumber === record.queue_number,
          urgent: record.triage_level === 'urgent',
        }"
      >
        <button
          class="case-card-select"
          :disabled="
            patientLoading ||
            deletingQueueNumber === record.queue_number
          "
          :aria-current="
            loadedQueueNumber === record.queue_number ? 'true' : undefined
          "
          @click="emit('select', record.queue_number)"
        >
          <span class="case-card-top">
            <span class="case-number">#{{ record.queue_number }}</span>
            <span class="triage-badge" :class="record.triage_level">
              {{
                record.triage_level === 'urgent'
                  ? '優先處理'
                  : workflowLabel(record.workflow_status)
              }}
            </span>
          </span>
          <strong>{{ record.patient_name }}</strong>
          <span class="case-reason">
            {{ record.reason || typeLabel(record.type) }}
          </span>
          <span class="case-meta">
            {{ record.gender }} · {{ record.age }}歲 ·
            {{ typeLabel(record.type) }}
          </span>
        </button>
        <div class="case-card-footer">
          <time :datetime="record.created_at">
            {{ formatCaseDate(record.created_at) }}
          </time>
          <span
            v-if="record.workflow_status === 'summary_pending'"
            class="ai-saved-badge"
          >
            AI 摘要產生中
          </span>
          <span
            v-else-if="record.workflow_status === 'summary_failed'"
            class="ai-saved-badge"
          >
            AI 摘要失敗
          </span>
          <span
            v-else-if="
              record.workflow_status === 'summary_ready' ||
              record.workflow_status === 'summary_partial' ||
              record.has_structured_note
            "
            class="ai-saved-badge"
          >
            AI 摘要已儲存
          </span>
          <button
            class="case-delete"
            :disabled="Boolean(deletingQueueNumber)"
            :aria-label="`刪除 ${record.patient_name} 的病例`"
            @click="emit('delete', record)"
          >
            {{
              deletingQueueNumber === record.queue_number
                ? '刪除中…'
                : '刪除'
            }}
          </button>
        </div>
      </article>

      <button
        v-if="hasMore"
        class="load-more-cases"
        :disabled="loading"
        @click="emit('load-more')"
      >
        {{ loading ? '載入中…' : '載入更多病例' }}
      </button>
    </div>
  </aside>
</template>

<style scoped>
.case-browser {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--surface-1);
}

.case-browser-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 18px 14px;
}

.case-browser-kicker {
  display: block;
  margin-bottom: 3px;
  color: var(--blue);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
}

.case-browser h2 {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.case-refresh {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--muted);
  cursor: pointer;
  font-size: 18px;
}

.case-refresh:hover:not(:disabled) {
  border-color: var(--blue);
  color: var(--blue);
}

.case-refresh:disabled {
  cursor: wait;
  opacity: 0.45;
}

.case-search {
  display: flex;
  height: 46px;
  flex: 0 0 auto;
  align-items: center;
  gap: 7px;
  margin: 0 14px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--muted);
}

.case-search:focus-within {
  border-color: var(--blue);
}

.case-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text);
  font-size: 14px;
}

.case-search input::-webkit-search-cancel-button {
  display: none;
}

.case-search button {
  min-width: 32px;
  min-height: 32px;
  padding: 6px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 10px;
}

.case-summary {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px 8px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  letter-spacing: 0.05em;
}

.case-summary strong {
  min-width: 24px;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--blue-soft);
  color: var(--blue);
  font-size: 12px;
  text-align: center;
}

.case-list {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  padding: 0 10px 14px;
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
}

.case-state {
  display: flex;
  min-height: 120px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 16px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  line-height: 1.65;
  text-align: center;
}

.case-state button {
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text);
  cursor: pointer;
}

.case-error {
  color: var(--danger);
}

.case-loader {
  width: 18px;
  height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--blue);
  border-radius: 50%;
  animation: case-spin 0.8s linear infinite;
}

.case-card {
  display: flex;
  width: 100%;
  flex: 0 0 auto;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-1);
  color: var(--text);
  transition:
    border-color 0.18s,
    background 0.18s,
    transform 0.18s;
}

.case-card:hover {
  border-color: var(--border-strong);
  background: #fbfdff;
  transform: translateY(-1px);
}

.case-card.active {
  border-color: var(--blue);
  background: var(--blue-soft);
  box-shadow: inset 3px 0 0 var(--blue);
}

.case-card.urgent:not(.active) {
  border-color: rgb(198 64 79 / 28%);
}

.case-card-select {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 5px;
  padding: 14px 14px 10px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  text-align: left;
}

.case-card-select:disabled {
  cursor: wait;
  opacity: 0.55;
}

.case-card-top,
.case-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.case-number {
  color: var(--blue);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  letter-spacing: 0.08em;
}

.triage-badge {
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--green-soft);
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.triage-badge.urgent {
  background: #fdecee;
  color: var(--danger);
}

.case-card-select > strong {
  overflow: hidden;
  font-size: 16px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-reason {
  overflow: hidden;
  color: #4f6579;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-meta {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.case-card-footer {
  display: flex;
  min-height: 42px;
  align-items: center;
  gap: 7px;
  padding: 7px 10px 8px 14px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.case-card-footer time {
  white-space: nowrap;
}

.ai-saved-badge {
  margin-left: auto;
  color: var(--green);
  font-size: 11px;
}

.case-delete {
  min-height: 32px;
  padding: 6px 9px;
  border: 1px solid rgb(198 64 79 / 32%);
  border-radius: 6px;
  background: #fff8f8;
  color: var(--danger);
  cursor: pointer;
  font-size: 12px;
}

.case-delete:hover:not(:disabled) {
  border-color: var(--danger);
  background: #fdecee;
  color: var(--danger);
}

.case-delete:disabled {
  cursor: wait;
  opacity: 0.45;
}

.load-more-cases {
  flex: 0 0 auto;
  min-height: 42px;
  padding: 10px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.load-more-cases:hover:not(:disabled) {
  border-color: var(--blue);
  color: var(--blue);
}

@keyframes case-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 980px) {
  .case-browser {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }

  .case-browser-header {
    padding: 10px 14px 8px;
  }

  .case-browser h2 {
    font-size: 15px;
  }

  .case-browser-kicker {
    display: none;
  }

  .case-summary {
    padding: 8px 14px 6px;
  }

  .case-list {
    display: grid;
    grid-auto-columns: minmax(230px, 280px);
    grid-auto-flow: column;
    grid-template-rows: 1fr;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0 12px 10px;
  }

  .case-card {
    height: 100%;
    min-height: 90px;
  }

  .case-state {
    min-width: 260px;
    min-height: 90px;
  }

  .load-more-cases {
    min-width: 150px;
  }
}

@media (max-width: 760px) {
  .case-browser {
    border-bottom: 0;
  }

  .case-list {
    display: flex;
    overflow-x: hidden;
    overflow-y: auto;
  }

  .case-card {
    height: auto;
  }
}
</style>
