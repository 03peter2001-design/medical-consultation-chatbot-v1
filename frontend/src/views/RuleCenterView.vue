<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import AppHeader from '../components/AppHeader.vue'
import DiseaseVoteGovernance from '../components/DiseaseVoteGovernance.vue'
import FactLabelGovernance from '../components/FactLabelGovernance.vue'
import SafetyRuleGovernance from '../components/SafetyRuleGovernance.vue'
import { api, connectionError } from '../services/backend.js'

const sessionId = `rule_admin_${Date.now()}`
const rulebook = ref(null)
const loading = ref(true)
const authorized = ref(false)
const authorizing = ref(false)
const error = ref('')
const success = ref('')
const adminToken = ref('')
const advancedDefinitionsOpen = ref(false)

const routeLabels = {
  chest: '胸痛',
  headache: '頭痛',
  abdomen: '腹痛',
}

async function loadRules() {
  loading.value = true
  error.value = ''
  try {
    rulebook.value = await api.loadRuleCenter()
  } catch (requestError) {
    error.value = connectionError(requestError)
  } finally {
    loading.value = false
  }
}

async function unlockEditing() {
  if (!adminToken.value.trim() || authorizing.value) return
  authorizing.value = true
  error.value = ''
  try {
    await api.authorizeRuleEditor(adminToken.value)
    authorized.value = true
    success.value = '權杖驗證成功，可以開始治理規則。'
  } catch (requestError) {
    authorized.value = false
    error.value = requestError.message
  } finally {
    authorizing.value = false
  }
}

function lockEditing() {
  authorized.value = false
  adminToken.value = ''
  success.value = ''
  error.value = ''
}

function handleRulebookSaved(updated) {
  rulebook.value = updated
}

onMounted(loadRules)
</script>

<template>
  <div class="app-shell rule-center-app">
    <AppHeader
      icon="⚙"
      title="醫師端規則中心"
      subtitle="全局決策邏輯 / Safety / 疾病表版本"
      :status="
        loading
          ? '載入中…'
          : authorized
            ? '已同步 · 已解鎖'
            : rulebook?.edit_enabled
              ? '已同步 · 已鎖定'
            : '唯讀檢視已同步'
      "
      status-tone="online"
    >
      <RouterLink class="nav-link" to="/doctor">← 返回醫師工作區</RouterLink>
      <RouterLink class="nav-link" to="/doctor/terminology/snomed">
        SNOMED CT
      </RouterLink>
      <RouterLink class="nav-link" to="/">病患問診端</RouterLink>
    </AppHeader>

    <main class="rule-center">
      <div v-if="loading" class="state-card">正在載入規則…</div>
      <div v-else-if="!rulebook" class="state-card error">{{ error }}</div>

      <template v-else>
        <section class="page-heading">
          <div>
            <span>GLOBAL LOGIC</span>
            <h1>問診決策全貌</h1>
            <p>
              此處呈現實際執行中的確定性規則；Safety 永遠優先於疾病投票。
            </p>
          </div>
          <div class="revision">
            <small>目前版本</small>
            <code>{{ rulebook.revision.slice(0, 12) }}</code>
          </div>
        </section>

        <section class="flow-grid" aria-label="全局決策流程">
          <article v-for="item in rulebook.flow" :key="item.step">
            <b>{{ item.step }}</b>
            <div>
              <h2>{{ item.name }}</h2>
              <p>{{ item.description }}</p>
            </div>
          </article>
        </section>

        <section class="rule-section">
          <div class="section-heading">
            <div>
              <span>ROUTE PROFILES</span>
              <h2>三路由投票政策</h2>
            </div>
            <strong>{{ rulebook.fact_count }} 個 ClinicalFact</strong>
          </div>
          <div class="route-grid">
            <article v-for="route in rulebook.routes" :key="route.route">
              <header>
                <h3>{{ routeLabels[route.route] }}</h3>
                <span v-if="route.provisional">未經醫師校準</span>
              </header>
              <dl>
                <div>
                  <dt>疾病表</dt>
                  <dd>{{ route.profile_version }}</dd>
                </div>
                <div>
                  <dt>疾病方向</dt>
                  <dd>{{ route.profile_count }} 項</dd>
                </div>
                <div>
                  <dt>不能漏診</dt>
                  <dd>{{ route.must_not_miss_count }} 項</dd>
                </div>
                <div>
                  <dt>完整度門檻</dt>
                  <dd>{{ route.policy.coverage_threshold * 100 }}%</dd>
                </div>
                <div>
                  <dt>最多輪數</dt>
                  <dd>{{ route.policy.max_turns }}</dd>
                </div>
              </dl>
            </article>
          </div>
        </section>

        <section class="rule-section access-section">
          <div class="section-heading">
            <div>
              <span>GOVERNANCE ACCESS</span>
              <h2>規則治理權限</h2>
              <p>同一組管理權限同時保護 Safety 規則與疾病票數發布。</p>
            </div>
          </div>
          <div v-if="!rulebook.edit_enabled" class="readonly-note">
            目前為唯讀。請由系統管理員在後端設定
            <code>SAFETY_RULE_ADMIN_TOKEN</code> 後重新啟動。
          </div>
          <form
            v-else-if="!authorized"
            class="unlock-panel"
            @submit.prevent="unlockEditing"
          >
            <div>
              <strong>先驗證管理權杖</strong>
              <p>驗證成功後才會顯示 Safety 與疾病票數編輯控制。</p>
            </div>
            <input
              v-model="adminToken"
              type="password"
              autocomplete="off"
              placeholder="SAFETY_RULE_ADMIN_TOKEN"
              aria-label="規則管理權杖"
            />
            <button
              class="primary-action"
              :disabled="!adminToken.trim() || authorizing"
            >
              {{ authorizing ? '驗證中…' : '解鎖治理功能' }}
            </button>
          </form>
          <div v-else class="authorized-bar">
            <div>
              <span class="authorized-dot" />
              <strong>治理權杖已驗證</strong>
              <small>可調整 Safety 規則與疾病票數</small>
            </div>
            <button class="secondary-action" @click="lockEditing">
              鎖定並清除權杖
            </button>
          </div>
          <div v-if="success" class="success-note">{{ success }}</div>
          <div v-if="error" class="error-note">{{ error }}</div>
        </section>

        <DiseaseVoteGovernance
          :rulebook="rulebook"
          :authorized="authorized"
          :admin-token="adminToken"
          :session-id="sessionId"
          @saved="handleRulebookSaved"
        />

        <details
          class="advanced-safety-definition"
          @toggle="advancedDefinitionsOpen = $event.currentTarget.open"
        >
          <summary>
            <span>進階設定</span>
            <div>
              <strong>ClinicalFact 標籤與 Safety 行為</strong>
              <small>編輯標籤說明，或勾選成命中即停止的 Safety 標籤</small>
            </div>
            <b aria-hidden="true">{{ advancedDefinitionsOpen ? '收合' : '展開' }}</b>
          </summary>
          <FactLabelGovernance
            :rulebook="rulebook"
            :authorized="authorized"
            :admin-token="adminToken"
            :session-id="sessionId"
            @saved="handleRulebookSaved"
          />
          <details class="conditional-safety-definition">
            <summary>
              <div>
                <strong>組合與原文 Safety 規則</strong>
                <small>僅管理需要多個條件、特定原文或 FHIR 風險才停止的進階規則</small>
              </div>
              <span>{{ rulebook.safety_groups.length }} 組</span>
            </summary>
            <SafetyRuleGovernance
              :rulebook="rulebook"
              :authorized="authorized"
              :admin-token="adminToken"
              :session-id="sessionId"
              @saved="handleRulebookSaved"
            />
          </details>
        </details>

      </template>
    </main>
  </div>
</template>

<style scoped>
.rule-center-app {
  min-height: 100dvh;
  background: var(--bg);
}

.rule-center {
  flex: 1;
  min-height: 0;
  width: min(1240px, 100%);
  margin: 0 auto;
  padding: 28px;
  overflow-y: auto;
}

.page-heading,
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.page-heading span,
.section-heading span {
  color: var(--blue);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.page-heading h1 {
  margin: 4px 0;
  font-size: 28px;
}

.page-heading p,
.section-heading p {
  color: var(--muted);
  line-height: 1.6;
}

.revision {
  display: grid;
  gap: 4px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
}

.revision small {
  color: var(--muted);
}

.flow-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-top: 22px;
}

.flow-grid article {
  display: flex;
  gap: 12px;
  min-height: 126px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-1);
}

.flow-grid article > b {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  place-items: center;
  border-radius: 50%;
  background: var(--blue-soft);
  color: var(--blue);
}

.flow-grid h2 {
  margin: 2px 0 7px;
  font-size: 15px;
}

.flow-grid p {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}

.rule-section {
  margin-top: 20px;
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-1);
}

.section-heading h2 {
  margin-top: 3px;
  font-size: 20px;
}

.section-heading > strong {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.route-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 16px;
}

.route-grid article {
  padding: 15px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
}

.route-grid header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.route-grid header span {
  padding: 3px 6px;
  border-radius: 999px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 10px;
}

.route-grid dl {
  display: grid;
  gap: 8px;
  margin-top: 13px;
}

.route-grid dl div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
}

.route-grid dt {
  color: var(--muted);
}

.route-grid dd {
  overflow-wrap: anywhere;
  text-align: right;
}

.primary-action,
.secondary-action {
  min-height: 42px;
  padding: 9px 15px;
  border-radius: 7px;
  cursor: pointer;
  font-weight: 700;
}

.primary-action {
  background: var(--blue);
  color: white;
}

.secondary-action {
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text);
}

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.readonly-note,
.success-note,
.error-note {
  margin-top: 14px;
  padding: 11px 13px;
  border-radius: 7px;
  font-size: 13px;
  line-height: 1.55;
}

.readonly-note {
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--muted);
}

.unlock-panel,
.authorized-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
}

.unlock-panel > div {
  flex: 1;
}

.unlock-panel p,
.authorized-bar small {
  color: var(--muted);
  font-size: 11px;
}

.unlock-panel input {
  flex: 0 1 360px;
  width: 100%;
  height: 44px;
  max-width: 340px;
  min-width: 220px;
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text);
  box-shadow: inset 0 1px 2px rgb(37 67 91 / 4%);
  transition:
    border-color 0.16s,
    box-shadow 0.16s;
}

.unlock-panel input::placeholder {
  color: color-mix(in srgb, var(--muted) 76%, transparent);
}

.unlock-panel input:hover {
  border-color: var(--border-strong);
}

.unlock-panel input:focus {
  border-color: var(--blue);
  box-shadow: 0 0 0 3px var(--blue-soft);
}

.unlock-panel .primary-action {
  flex: 0 0 auto;
  height: 44px;
  min-height: 44px;
  white-space: nowrap;
}

.authorized-bar {
  justify-content: space-between;
  border-color: rgb(8 127 109 / 35%);
  background: var(--green-soft);
}

.authorized-bar > div {
  display: flex;
  align-items: center;
  gap: 8px;
}

.authorized-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
}

.success-note {
  border: 1px solid rgb(10 146 126 / 35%);
  background: var(--green-soft);
  color: var(--green);
}

.error-note,
.state-card.error {
  border: 1px solid rgb(190 45 45 / 35%);
  background: #fff5f5;
  color: var(--danger);
}

.state-card {
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-1);
}

.advanced-safety-definition {
  margin-top: 20px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-1);
}

.advanced-safety-definition > summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  cursor: pointer;
  list-style: none;
}

.advanced-safety-definition > summary::-webkit-details-marker {
  display: none;
}

.advanced-safety-definition > summary > span {
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--blue-soft);
  color: var(--blue);
  font-size: 10px;
  font-weight: 700;
}

.advanced-safety-definition > summary > div {
  display: grid;
  flex: 1;
  gap: 2px;
}

.advanced-safety-definition > summary small,
.advanced-safety-definition > summary b {
  color: var(--muted);
  font-size: 11px;
}

.advanced-safety-definition[open] > summary b {
  color: var(--blue);
}

.advanced-safety-definition[open] > summary {
  border-bottom: 1px solid var(--border);
}

.conditional-safety-definition {
  margin: 0 22px 22px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-2);
  overflow: hidden;
}

.conditional-safety-definition > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px;
  cursor: pointer;
}

.conditional-safety-definition > summary > div {
  display: grid;
  gap: 3px;
}

.conditional-safety-definition > summary small,
.conditional-safety-definition > summary > span {
  color: var(--muted);
  font-size: 11px;
}

.conditional-safety-definition > summary > span {
  flex: 0 0 auto;
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--surface-1);
}

.conditional-safety-definition[open] > summary {
  border-bottom: 1px solid var(--border);
}

.advanced-safety-definition :deep(.safety-governance) {
  margin-top: 0;
  border: 0;
}

@media (max-width: 900px) {
  .flow-grid {
    grid-template-columns: 1fr 1fr;
  }

  .route-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 620px) {
  .rule-center {
    padding: 16px 12px;
  }

  .rule-section {
    padding: 12px;
  }

  .page-heading,
  .section-heading {
    display: grid;
  }

  .flow-grid,
  .route-grid {
    display: flex;
    padding-bottom: 6px;
    overflow-x: auto;
    scroll-snap-type: x proximity;
    scrollbar-width: thin;
  }

  .flow-grid article {
    flex: 0 0 min(270px, 82vw);
    min-height: 112px;
    scroll-snap-align: start;
  }

  .route-grid article {
    flex: 0 0 min(295px, 88vw);
    scroll-snap-align: start;
  }

  .unlock-panel,
  .authorized-bar {
    align-items: stretch;
    flex-direction: column;
  }

  .unlock-panel input {
    flex-basis: auto;
    width: 100%;
    max-width: none;
    min-width: 0;
  }

  .advanced-safety-definition > summary {
    align-items: flex-start;
    padding: 14px;
  }

  .conditional-safety-definition {
    margin: 0 14px 14px;
  }

  .conditional-safety-definition > summary {
    align-items: flex-start;
    flex-direction: column;
  }
}

</style>
