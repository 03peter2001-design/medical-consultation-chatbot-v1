<script setup>
import { computed, nextTick, ref } from 'vue'
import { RouterLink } from 'vue-router'

import AppHeader from '../components/AppHeader.vue'
import { api, connectionError } from '../services/backend.js'

const pageSize = 20
const query = ref('')
const submittedQuery = ref('')
const results = ref([])
const total = ref(0)
const mode = ref('')
const loading = ref(false)
const loadingMore = ref(false)
const error = ref('')
const searched = ref(false)
const copiedCode = ref('')
const searchInput = ref(null)

const examples = [
  'acute coronary syndrome',
  'migraine',
  'pneumonia',
  '394659003',
]

const hasMore = computed(() => results.value.length < total.value)
const resultSummary = computed(() => {
  if (!searched.value) return '等待查詢'
  if (error.value) return '查詢失敗'
  if (loading.value) return '查詢中…'
  return `找到 ${total.value.toLocaleString()} 個概念`
})

async function runSearch({ append = false } = {}) {
  if (loading.value || loadingMore.value) return
  const normalized = query.value.trim()
  if (normalized.length < 2) {
    error.value = '請輸入至少 2 個字元或完整 concept ID。'
    await nextTick()
    searchInput.value?.focus()
    return
  }

  if (append) loadingMore.value = true
  else {
    loading.value = true
    error.value = ''
    searched.value = true
    submittedQuery.value = normalized
    results.value = []
    total.value = 0
    mode.value = ''
  }

  try {
    const response = await api.searchSnomed({
      query: append ? submittedQuery.value : normalized,
      limit: pageSize,
      offset: append ? results.value.length : 0,
    })
    results.value = append
      ? [...results.value, ...(response.items || [])]
      : response.items || []
    total.value = Number(response.total || 0)
    mode.value = response.mode || ''
  } catch (requestError) {
    error.value =
      requestError instanceof TypeError
        ? connectionError(requestError)
        : requestError.message
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function searchExample(value) {
  query.value = value
  void runSearch()
}

async function copyCode(code) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(code)
    } else {
      const input = document.createElement('textarea')
      input.value = code
      input.setAttribute('readonly', '')
      input.style.position = 'fixed'
      input.style.opacity = '0'
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      input.remove()
    }
    copiedCode.value = code
    window.setTimeout(() => {
      if (copiedCode.value === code) copiedCode.value = ''
    }, 1600)
  } catch {
    copiedCode.value = ''
  }
}
</script>

<template>
  <div class="app-shell snomed-app">
    <AppHeader
      icon="S"
      title="SNOMED CT 編碼查詢"
      subtitle="本機 RF2 索引 / HAPI FHIR 驗證"
      :status="resultSummary"
      :status-tone="error ? 'idle' : 'online'"
    >
      <RouterLink class="nav-link" to="/doctor">← 醫師工作區</RouterLink>
      <RouterLink class="nav-link" to="/doctor/rules">規則中心</RouterLink>
    </AppHeader>

    <main class="snomed-page">
      <section class="search-hero">
        <div class="eyebrow">TERMINOLOGY BROWSER</div>
        <h1>查找 SNOMED CT 概念</h1>
        <p>
          輸入英文臨床術語進行文字搜尋，或輸入完整 concept ID 精確查詢。
          結果直接來自目前部署的 SNOMED CT International Edition。
        </p>

        <form class="search-form" @submit.prevent="runSearch()">
          <label for="snomed-query">疾病名稱或 concept ID</label>
          <div class="search-control">
            <svg
              viewBox="0 0 24 24"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m16.5 16.5 4 4" />
            </svg>
            <input
              id="snomed-query"
              ref="searchInput"
              v-model="query"
              type="search"
              maxlength="120"
              autocomplete="off"
              placeholder="例如：acute coronary syndrome 或 394659003"
            />
            <button :disabled="loading || query.trim().length < 2">
              {{ loading ? '查詢中…' : '查詢' }}
            </button>
          </div>
        </form>

        <div class="examples" aria-label="查詢範例">
          <span>快速範例</span>
          <button
            v-for="example in examples"
            :key="example"
            type="button"
            @click="searchExample(example)"
          >
            {{ example }}
          </button>
        </div>
      </section>

      <section class="content-grid">
        <aside class="search-notes">
          <article>
            <span class="note-index">01</span>
            <div>
              <h2>文字搜尋</h2>
              <p>
                使用 SNOMED International 英文描述；目前不會把中文疾病名稱
                自動翻譯或猜碼。
              </p>
            </div>
          </article>
          <article>
            <span class="note-index">02</span>
            <div>
              <h2>精確查詢</h2>
              <p>
                輸入純數字 concept ID 時，系統會以
                <code>CodeSystem/$lookup</code> 驗證。
              </p>
            </div>
          </article>
          <article class="safety-note">
            <span class="note-index">!</span>
            <div>
              <h2>使用限制</h2>
              <p>
                代碼存在不代表適用於特定病人，也不取代醫師的臨床與版本審查。
              </p>
            </div>
          </article>
        </aside>

        <section class="result-panel" aria-live="polite">
          <div class="result-heading">
            <div>
              <span>
                {{
                  mode === 'code'
                    ? 'EXACT LOOKUP'
                    : mode === 'text'
                      ? 'RF2 FULL-TEXT INDEX'
                      : 'SNOMED CT'
                }}
              </span>
              <h2>
                {{
                  searched
                    ? `「${submittedQuery}」`
                    : '查詢結果'
                }}
              </h2>
            </div>
            <strong v-if="searched && !loading && !error">
              {{ total.toLocaleString() }}
            </strong>
          </div>

          <div v-if="loading" class="result-state">
            <span class="spinner" />
            正在查詢本機 HAPI terminology index…
          </div>
          <div v-else-if="error" class="result-state error">
            <strong>無法完成查詢</strong>
            <pre>{{ error }}</pre>
          </div>
          <div v-else-if="!searched" class="result-state">
            <div class="empty-mark">SCT</div>
            <strong>尚未送出查詢</strong>
            <p>可從上方範例開始，或輸入要查找的英文臨床術語。</p>
          </div>
          <div v-else-if="!results.length" class="result-state">
            <div class="empty-mark">0</div>
            <strong>找不到相符概念</strong>
            <p>請改用英文同義詞、較短關鍵字，或確認 concept ID。</p>
          </div>

          <div v-else class="result-list">
            <article
              v-for="item in results"
              :key="`${item.system}-${item.code}`"
              class="concept-card"
            >
              <div class="concept-code">
                <small>SNOMED CT</small>
                <code>{{ item.code }}</code>
              </div>
              <div class="concept-display">
                <small>Preferred display</small>
                <h3>{{ item.display || '無顯示名稱' }}</h3>
                <p>{{ item.system }}</p>
              </div>
              <button
                class="copy-button"
                type="button"
                :aria-label="`複製代碼 ${item.code}`"
                @click="copyCode(item.code)"
              >
                {{ copiedCode === item.code ? '已複製' : '複製代碼' }}
              </button>
            </article>

            <button
              v-if="hasMore"
              class="load-more"
              type="button"
              :disabled="loadingMore"
              @click="runSearch({ append: true })"
            >
              {{ loadingMore ? '載入中…' : `載入更多（已顯示 ${results.length}）` }}
            </button>
          </div>
        </section>
      </section>
    </main>
  </div>
</template>

<style scoped>
.snomed-app {
  --brand-accent: #1f6172;
}

.snomed-page {
  flex: 1;
  overflow-y: auto;
  padding: 44px clamp(20px, 5vw, 72px) 56px;
}

.search-hero {
  max-width: 1180px;
  margin: 0 auto 30px;
}

.eyebrow,
.result-heading span {
  color: var(--green);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
}

.search-hero h1 {
  margin-top: 6px;
  font-size: clamp(30px, 4vw, 48px);
  letter-spacing: -0.04em;
  line-height: 1.15;
}

.search-hero > p {
  max-width: 740px;
  margin-top: 12px;
  color: var(--muted);
  font-size: 15px;
}

.search-form {
  max-width: 920px;
  margin-top: 28px;
}

.search-form > label {
  display: block;
  margin-bottom: 8px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
}

.search-control {
  display: flex;
  align-items: center;
  min-height: 62px;
  padding: 6px 6px 6px 18px;
  border: 1px solid var(--border-strong);
  border-radius: 9px;
  background: white;
  box-shadow: 0 12px 34px rgb(35 66 89 / 8%);
}

.search-control:focus-within {
  border-color: var(--blue);
  box-shadow: 0 0 0 3px rgb(37 104 178 / 10%);
}

.search-control svg {
  flex: 0 0 22px;
  width: 22px;
  color: var(--muted);
}

.search-control input {
  flex: 1;
  min-width: 0;
  padding: 8px 14px;
  border: 0;
  outline: 0;
  color: var(--text);
  font-size: 16px;
}

.search-control button,
.load-more {
  min-height: 48px;
  padding: 0 24px;
  border-radius: 6px;
  background: var(--blue);
  color: white;
  cursor: pointer;
  font-weight: 700;
}

.search-control button:disabled,
.load-more:disabled {
  cursor: wait;
  opacity: 0.55;
}

.examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
}

.examples span {
  margin-right: 4px;
  color: var(--muted);
  font-size: 12px;
}

.examples button {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
}

.examples button:hover {
  border-color: var(--blue);
  color: var(--blue);
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  gap: 24px;
  max-width: 1180px;
  margin: 0 auto;
}

.search-notes {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.search-notes article {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--border);
  background: var(--surface-1);
}

.search-notes article:first-child {
  border-radius: 8px 8px 0 0;
}

.search-notes article:last-child {
  border-radius: 0 0 8px 8px;
}

.note-index {
  color: var(--green);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 700;
}

.search-notes h2 {
  font-size: 14px;
}

.search-notes p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.search-notes code {
  color: var(--blue);
  font-size: 11px;
}

.search-notes .safety-note {
  border-color: #ead9b9;
  background: var(--warning-soft);
}

.result-panel {
  min-height: 430px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-1);
}

.result-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px;
  border-bottom: 1px solid var(--border);
}

.result-heading h2 {
  max-width: 700px;
  overflow: hidden;
  margin-top: 3px;
  font-size: 19px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-heading strong {
  color: var(--blue);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 24px;
}

.result-state {
  display: grid;
  min-height: 340px;
  place-content: center;
  justify-items: center;
  padding: 36px;
  color: var(--muted);
  text-align: center;
}

.result-state p {
  max-width: 460px;
  margin-top: 5px;
  font-size: 13px;
}

.result-state.error {
  color: var(--danger);
}

.result-state pre {
  max-width: 620px;
  margin-top: 10px;
  overflow: auto;
  color: var(--muted);
  font: inherit;
  font-size: 12px;
  white-space: pre-wrap;
}

.empty-mark {
  display: grid;
  width: 64px;
  height: 64px;
  margin-bottom: 14px;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 50%;
  color: var(--green);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 800;
}

.spinner {
  width: 28px;
  height: 28px;
  margin-bottom: 14px;
  border: 3px solid var(--border);
  border-top-color: var(--blue);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.result-list {
  padding: 8px 22px 22px;
}

.concept-card {
  display: grid;
  grid-template-columns: minmax(150px, 0.35fr) minmax(240px, 1fr) auto;
  align-items: center;
  gap: 20px;
  padding: 18px 0;
  border-bottom: 1px solid var(--border);
}

.concept-card small {
  display: block;
  margin-bottom: 3px;
  color: var(--muted);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.concept-code code {
  color: var(--blue);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 15px;
  font-weight: 700;
}

.concept-display h3 {
  font-size: 14px;
  line-height: 1.4;
}

.concept-display p {
  margin-top: 4px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
}

.copy-button {
  min-width: 78px;
  padding: 8px 11px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--surface-2);
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
}

.copy-button:hover {
  border-color: var(--blue);
  color: var(--blue);
}

.load-more {
  display: block;
  margin: 22px auto 0;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--blue);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 820px) {
  .snomed-page {
    padding: 28px 16px 40px;
  }

  .content-grid {
    grid-template-columns: 1fr;
  }

  .search-notes {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
  }

  .search-notes article,
  .search-notes article:first-child,
  .search-notes article:last-child {
    border-radius: 7px;
  }
}

@media (max-width: 620px) {
  .search-control {
    align-items: stretch;
    padding-left: 12px;
  }

  .search-control input {
    padding-inline: 10px;
    font-size: 14px;
  }

  .search-control button {
    padding-inline: 16px;
  }

  .search-notes {
    display: none;
  }

  .result-heading {
    padding: 16px;
  }

  .result-list {
    padding: 4px 16px 18px;
  }

  .concept-card {
    grid-template-columns: 1fr auto;
    gap: 10px;
  }

  .concept-display {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .copy-button {
    grid-column: 2;
    grid-row: 1;
  }
}
</style>
