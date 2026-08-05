<script setup>
import { computed, ref } from 'vue'

import TerminologyCode from './TerminologyCode.vue'

const props = defineProps({
  clinical: { type: Object, required: true },
})

const showAll = ref(false)
const visibleDifferentials = computed(() =>
  showAll.value
    ? props.clinical.allDifferentials
    : props.clinical.differentials,
)
const safetyDirections = computed(
  () => props.clinical.safetyTriggeredConditions || [],
)
const visibleDirectionCount = computed(() => {
  const keys = [
    ...safetyDirections.value.map(
      (item) => item.id || item.condition,
    ),
    ...visibleDifferentials.value.map(
      (item) => item.id || item.condition,
    ),
  ]
  return new Set(keys).size
})

function selectionPhaseLabel(phase) {
  return (
    {
      broad: '廣泛區辨',
      differentiate: '候選區辨',
      confirm: '領先疾病確認',
    }[phase] || phase || '未記錄'
  )
}

function selectionTierLabel(tier) {
  return (
    {
      safety_priority: 'Safety 優先題',
      required: '必要欄位',
      general: '一般追問',
    }[tier] || tier || '未記錄'
  )
}
</script>

<template>
  <div class="evidence-layout">
    <section class="evidence-panel">
      <div class="panel-heading">
        <div>
          <span>
            {{
              safetyDirections.length
                ? 'Safety 規則 · 固定鑑別方向'
                : '固定疾病表 · 線索投票'
            }}
          </span>
          <h3>鑑別方向</h3>
        </div>
        <strong>{{ visibleDirectionCount }} 項</strong>
      </div>

      <section
        v-if="safetyDirections.length"
        class="safety-directions"
        aria-label="Safety 規則觸發的鑑別方向"
      >
        <div class="safety-directions-heading">
          <strong>Safety 規則觸發的鑑別方向</strong>
          <span>優先於疾病票數</span>
        </div>
        <article
          v-for="item in safetyDirections"
          :key="item.id || item.condition"
        >
          <h4>
            <span>{{ item.condition }}</span>
            <TerminologyCode
              v-for="coding in item.codings || []"
              :key="`${coding.system}-${coding.code}`"
              :coding="coding"
            />
          </h4>
          <ul>
            <li
              v-for="trigger in item.triggers"
              :key="`${trigger.ruleCode}-${trigger.evidence}`"
            >
              <b>{{ trigger.ruleLabel || '安全規則命中' }}</b>
              <span v-if="trigger.evidence">
                證據：「{{ trigger.evidence }}」
              </span>
            </li>
          </ul>
        </article>
        <p>
          此清單來自固定 Safety 規則，不代表疾病票數、患病機率或正式診斷。
        </p>
      </section>

      <div
        v-if="clinical.diseaseAssessment.provisional"
        class="provisional-note"
      >
        疾病表尚未經醫師校準；票數是線索相容排序，不是患病機率。
      </div>

      <div v-if="visibleDifferentials.length" class="evidence-table">
        <div class="evidence-table-head" aria-hidden="true">
          <span>鑑別方向／票數</span>
          <span>支持證據</span>
          <span>反對證據</span>
        </div>
        <article
          v-for="hypothesis in visibleDifferentials"
          :key="hypothesis.id || hypothesis.condition"
          class="evidence-row"
        >
          <h4>
            <span>{{ hypothesis.condition }}</span>
            <TerminologyCode
              v-for="coding in hypothesis.codings || []"
              :key="`${coding.system}-${coding.code}`"
              :coding="coding"
            />
            <small
              v-if="!hypothesis.codings?.length"
              class="uncoded-condition"
            >
              未編碼
            </small>
            <small class="vote-summary">
              淨票 {{ hypothesis.netVotes }} · 支持
              {{ hypothesis.supportVotes }} · 反對
              {{ hypothesis.opposeVotes }}
            </small>
            <small class="coverage">
              資料完整度 {{ Math.round(hypothesis.coverage * 100) }}%
            </small>
          </h4>
          <ul class="supporting">
            <li
              v-for="item in hypothesis.supporting_evidence || []"
              :key="item"
            >
              {{ item }}
            </li>
            <li v-if="!hypothesis.supporting_evidence?.length">
              尚無支持證據
            </li>
          </ul>
          <ul class="opposing">
            <li
              v-for="item in hypothesis.opposing_evidence || []"
              :key="item"
            >
              {{ item }}
            </li>
            <li v-if="!hypothesis.opposing_evidence?.length">
              尚無反對證據
            </li>
          </ul>
          <details
            v-if="hypothesis.missingFacts?.length"
            class="missing-facts"
          >
            <summary>尚缺 {{ hypothesis.missingFacts.length }} 項線索</summary>
            <span>{{ hypothesis.missingFacts.join('、') }}</span>
          </details>
        </article>
      </div>
      <div
        v-else-if="!safetyDirections.length"
        class="panel-empty"
      >
        <strong>目前沒有足夠支持線索</strong>
        <span>請參考原始問診、臨床警訊與仍需補充的資料。</span>
      </div>

      <button
        v-if="
          clinical.allDifferentials.length >
          clinical.differentials.length
        "
        type="button"
        class="toggle-all"
        @click="showAll = !showAll"
      >
        {{ showAll ? '只顯示前五名' : `查看全部 ${clinical.allDifferentials.length} 項` }}
      </button>

      <section
        v-if="clinical.mustNotMiss.length"
        class="must-not-miss"
      >
        <strong>不能漏診</strong>
        <span
          v-for="item in clinical.mustNotMiss"
          :key="item.id"
        >
          {{ item.condition }} · 淨票 {{ item.netVotes }}
        </span>
      </section>

      <div v-if="clinical.knowledgeGaps.length" class="knowledge-gaps">
        <strong>仍需補充</strong>
        <span v-for="gap in clinical.knowledgeGaps" :key="gap">
          {{ gap }}
        </span>
      </div>

      <aside class="terminology-note">
        <strong>標準術語</strong>
        <span>
          FHIR 原始 Coding 會直接標示；疾病表只顯示已驗證並凍結的
          SNOMED CT，未驗證項目維持未編碼。
          <template v-if="clinical.terminologyReference">
            本機參照
            {{ clinical.terminologyReference.package }}#{{
              clinical.terminologyReference.version
            }}。
          </template>
        </span>
      </aside>

      <details
        v-if="clinical.legacyDifferentials.length"
        class="legacy-differentials"
      >
        <summary>
          舊版 LLM 鑑別紀錄（{{ clinical.legacyDifferentials.length }}）
        </summary>
        <p>僅供稽核，不參與目前疾病表投票。</p>
        <ul>
          <li
            v-for="item in clinical.legacyDifferentials"
            :key="item.condition"
          >
            {{ item.condition }}
          </li>
        </ul>
      </details>
    </section>

    <section class="evidence-panel timeline-panel">
      <div class="panel-heading">
        <div>
          <span>問題與判讀依據</span>
          <h3>問診時間軸</h3>
        </div>
        <strong>{{ clinical.timeline.length }} 輪</strong>
      </div>

      <ol v-if="clinical.timeline.length" class="timeline">
        <li v-for="event in clinical.timeline" :key="event.turn">
          <span class="turn">T{{ event.turn }}</span>
          <div class="trace-content">
            <div class="trace-question">
              <span v-if="event.field">{{ event.field }}</span>
              <strong>
                {{ event.question || '舊版紀錄未保存題目文字' }}
              </strong>
            </div>
            <p class="trace-answer">
              <b>病人回答</b>
              {{ event.answer || '本輪未記錄回答' }}
            </p>
            <div class="trace-badges">
              <span>{{ event.actionLabel }}</span>
              <span>{{ event.sourceLabel }}</span>
              <span v-if="event.triage === 'urgent'" class="urgent">
                urgent
              </span>
              <span v-if="event.needsRetrieval">使用 RAG</span>
              <span v-if="event.questionUtility">
                選題區辨分 {{ event.questionUtility }}
              </span>
            </div>
            <dl v-if="event.extractedFacts.length" class="trace-facts">
              <div
                v-for="fact in event.extractedFacts"
                :key="`${event.turn}-${fact.field}`"
              >
                <dt>{{ fact.label }}</dt>
                <dd>{{ fact.value }}</dd>
              </div>
            </dl>
            <div
              v-if="event.clinicalFacts.length"
              class="trace-clinical-facts"
            >
              <b>標準線索</b>
              <span
                v-for="fact in event.clinicalFacts"
                :key="`${event.turn}-${fact.code}`"
              >
                {{ fact.label }} ·
                {{ fact.status === 'absent' ? '否認' : '有' }}
                <small v-if="fact.evidence">「{{ fact.evidence }}」</small>
              </span>
            </div>
            <div
              v-if="event.diseaseVotes.length"
              class="trace-votes"
            >
              <b>本輪前五名</b>
              <span
                v-for="item in event.diseaseVotes"
                :key="`${event.turn}-${item.id}`"
              >
                {{ item.name }} {{ item.netVotes }}票 ·
                {{ Math.round(item.coverage * 100) }}%
              </span>
            </div>
            <div v-if="event.selectionPhase" class="trace-funnel">
              <b>標籤漏斗</b>
              <span>
                {{ selectionPhaseLabel(event.selectionPhase) }} ·
                {{ selectionTierLabel(event.selectionTier) }}
              </span>
              <span v-if="event.candidateFrontier.length">
                候選群：
                {{
                  event.candidateFrontier
                    .map(
                      (item) =>
                        `${item.name}（淨票 ${item.netVotes}／支持 ${item.supportVotes}／完整度 ${Math.round(item.coverage * 100)}%）`,
                    )
                    .join('、')
                }}
              </span>
              <span v-if="event.targetFacts.length">
                目標標籤：
                {{ event.targetFacts.map((item) => item.label).join('、') }}
              </span>
              <small>
                區辨 {{ event.funnelScore.discrimination }} · 確認
                {{ event.funnelScore.confirmation }} · 反證
                {{ event.funnelScore.refutation }}
              </small>
            </div>
            <p class="trace-decision">
              <b>決定</b>
              <template v-if="event.nextQuestion">
                下一題問「{{ event.nextQuestion }}」
                <small v-if="event.selectedNextField">
                  （{{ event.selectedNextField }}）
                </small>
              </template>
              <template v-else>{{ event.actionLabel }}</template>
            </p>
            <p class="trace-reason">
              <b>理由</b>
              {{ event.reason || '未提供判讀說明' }}
            </p>
            <p v-if="event.retrievalQuery" class="trace-retrieval">
              <b>RAG 查詢</b>
              {{ event.retrievalQuery }}
            </p>
            <p v-if="event.modelError" class="trace-error">
              <b>模型 fallback</b>
              {{ event.modelError }}
            </p>
          </div>
        </li>
      </ol>
      <p v-else class="panel-empty">尚無問診推理時間軸</p>
    </section>
  </div>
</template>

<style scoped>
.evidence-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.8fr);
  gap: 14px;
  margin: 14px 18px 0;
}

.evidence-panel {
  min-width: 0;
  padding: 17px;
  border: 1px solid #d6e0e9;
  border-radius: 8px;
  background: #fff;
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 13px;
}

.panel-heading span {
  color: #6b7f92;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.panel-heading h3 {
  margin-top: 1px;
  font-size: 17px;
}

.panel-heading > strong {
  color: #2568b2;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.panel-empty {
  display: grid;
  gap: 3px;
  color: #6b7f92;
  font-size: 13px;
  line-height: 1.6;
}

.provisional-note {
  margin-bottom: 12px;
  padding: 9px 11px;
  border: 1px solid #e8c77d;
  border-radius: 6px;
  background: #fff8e8;
  color: #7a5510;
  font-size: 12px;
  line-height: 1.5;
}

.safety-directions {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid #e7a9a9;
  border-left: 4px solid #b92f2f;
  border-radius: 6px;
  background: #fff7f7;
}

.safety-directions-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.safety-directions-heading strong {
  color: #8f2525;
  font-size: 13px;
}

.safety-directions-heading span {
  color: #a32929;
  font-size: 10px;
  font-weight: 700;
}

.safety-directions article {
  padding-top: 8px;
  border-top: 1px solid #f0cccc;
}

.safety-directions h4 {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: #651d1d;
  font-size: 14px;
}

.safety-directions ul {
  display: grid;
  gap: 3px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}

.safety-directions li {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  color: #714040;
  font-size: 11px;
  line-height: 1.5;
}

.safety-directions > p {
  margin: 0;
  color: #7a5555;
  font-size: 11px;
  line-height: 1.5;
}

.evidence-table {
  overflow: hidden;
  border: 1px solid #d6e0e9;
  border-radius: 6px;
}

.evidence-table-head,
.evidence-row {
  display: grid;
  grid-template-columns: minmax(140px, 0.9fr) minmax(170px, 1.2fr) minmax(170px, 1.2fr);
}

.vote-summary,
.coverage {
  display: block;
  margin-top: 5px;
  color: #536b80;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 600;
}

.missing-facts {
  grid-column: 1 / -1;
  padding: 8px 12px 10px;
  border-top: 1px dashed #d6e0e9;
  color: #6b7f92;
  font-size: 11px;
}

.missing-facts summary {
  cursor: pointer;
  font-weight: 700;
}

.missing-facts span {
  display: block;
  margin-top: 5px;
  line-height: 1.5;
}

.toggle-all {
  width: 100%;
  margin-top: 10px;
  padding: 8px 12px;
  border: 1px solid #b8cce0;
  border-radius: 6px;
  background: #f7fbff;
  color: #2568b2;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
}

.must-not-miss {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
  padding: 11px;
  border: 1px solid #efb5b5;
  border-radius: 6px;
  background: #fff7f7;
}

.must-not-miss strong {
  width: 100%;
  color: #a32929;
  font-size: 12px;
}

.must-not-miss span {
  padding: 4px 7px;
  border-radius: 999px;
  background: #fbe1e1;
  color: #8f2525;
  font-size: 11px;
  font-weight: 700;
}

.legacy-differentials {
  margin-top: 11px;
  color: #6b7f92;
  font-size: 12px;
}

.legacy-differentials summary {
  cursor: pointer;
  font-weight: 700;
}

.trace-clinical-facts,
.trace-votes,
.trace-funnel {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}

.trace-clinical-facts b,
.trace-votes b,
.trace-funnel b {
  width: 100%;
  color: #435c72;
  font-size: 11px;
}

.trace-clinical-facts span,
.trace-votes span {
  padding: 4px 6px;
  border-radius: 4px;
  background: #edf4fa;
  color: #425d73;
  font-size: 10px;
}

.trace-clinical-facts small {
  color: #6b7f92;
}

.trace-funnel span {
  width: 100%;
  color: #425d73;
  font-size: 11px;
  line-height: 1.5;
}

.trace-funnel small {
  color: #6b7f92;
  font-size: 10px;
}

.evidence-table-head {
  background: #f5f8fb;
  color: #5e7387;
  font-size: 12px;
  font-weight: 700;
}

.evidence-table-head span,
.evidence-row > * {
  min-width: 0;
  padding: 10px 12px;
}

.evidence-table-head span + span,
.evidence-row > * + * {
  border-left: 1px solid #d6e0e9;
}

.evidence-row + .evidence-row {
  border-top: 1px solid #d6e0e9;
}

.evidence-row h4 {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 7px;
  font-size: 14px;
  line-height: 1.55;
}

.uncoded-condition {
  padding: 3px 6px;
  border: 1px dashed #c5d1dc;
  border-radius: 4px;
  color: #75889a;
  font-size: 10px;
  font-weight: 500;
  line-height: 1;
}

.evidence-row ul {
  display: grid;
  gap: 5px;
  list-style: none;
}

.evidence-row li {
  position: relative;
  padding-left: 14px;
  color: #40576b;
  font-size: 12px;
  line-height: 1.55;
}

.evidence-row li::before {
  position: absolute;
  top: 0.62em;
  left: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #0a927e;
  content: '';
}

.evidence-row .opposing li::before {
  background: #c6404f;
}

.knowledge-gaps {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e2e9ef;
}

.knowledge-gaps strong {
  color: #5f7387;
  font-size: 12px;
}

.knowledge-gaps span {
  padding: 4px 7px;
  border: 1px solid #b9cde1;
  border-radius: 5px;
  background: #f5f9fd;
  color: #3e5d79;
  font-size: 12px;
}

.terminology-note {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 11px;
  border-radius: 6px;
  background: #f5f8fb;
  color: #64798c;
  font-size: 11px;
  line-height: 1.55;
}

.terminology-note strong {
  flex: 0 0 auto;
  color: #3c5b75;
}

.timeline {
  display: grid;
  gap: 0;
  list-style: none;
}

.timeline li {
  position: relative;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
  padding: 0 0 15px;
}

.timeline li:not(:last-child)::after {
  position: absolute;
  top: 27px;
  bottom: 2px;
  left: 16px;
  width: 1px;
  background: #bed0e0;
  content: '';
}

.turn {
  display: grid;
  width: 34px;
  height: 24px;
  place-items: center;
  border: 1px solid #88add3;
  border-radius: 5px;
  background: #f3f8fd;
  color: #2568b2;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.timeline strong {
  color: #263e53;
  font-size: 13px;
}

.trace-content {
  min-width: 0;
  padding-bottom: 2px;
}

.trace-question {
  display: grid;
  gap: 3px;
}

.trace-question > span {
  width: max-content;
  padding: 2px 5px;
  border-radius: 4px;
  background: #eaf2fa;
  color: #47708f;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
}

.timeline .trace-answer,
.timeline .trace-decision,
.timeline .trace-reason,
.timeline .trace-retrieval,
.timeline .trace-error {
  margin-top: 3px;
  color: #6b7f92;
  font-size: 12px;
  line-height: 1.55;
}

.timeline p b {
  margin-right: 5px;
  color: #40576b;
}

.trace-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin: 6px 0;
}

.trace-badges span {
  padding: 2px 6px;
  border: 1px solid #b8cee2;
  border-radius: 999px;
  background: #f4f8fc;
  color: #3d688d;
  font-size: 10px;
  font-weight: 700;
}

.trace-badges span.urgent {
  border-color: #e7aeb4;
  background: #fff2f3;
  color: #b72e3b;
}

.trace-facts {
  display: grid;
  gap: 3px;
  margin: 6px 0;
}

.trace-facts div {
  display: grid;
  grid-template-columns: minmax(72px, 0.38fr) minmax(0, 1fr);
  gap: 7px;
  padding: 4px 6px;
  border-left: 2px solid #76af9f;
  background: #f3f9f7;
  font-size: 11px;
}

.trace-facts dt {
  color: #577164;
  font-weight: 700;
}

.trace-facts dd {
  color: #2c4c42;
}

.timeline .trace-reason {
  color: #415e78;
}

.timeline .trace-error {
  color: #ad3340;
}

.trace-decision small {
  color: #8293a3;
  font-size: 10px;
}

@media (max-width: 1040px) {
  .evidence-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .evidence-layout {
    margin-right: 12px;
    margin-left: 12px;
  }

  .evidence-table {
    overflow: visible;
    border: 0;
  }

  .evidence-table-head {
    display: none;
  }

  .evidence-row {
    display: grid;
    grid-template-columns: 1fr;
    overflow: hidden;
    border: 1px solid #d6e0e9;
    border-radius: 7px;
  }

  .evidence-row + .evidence-row {
    margin-top: 10px;
  }

  .evidence-row > * + * {
    border-top: 1px solid #e2e9ef;
    border-left: 0;
  }

  .evidence-row ul::before {
    display: block;
    margin-bottom: 6px;
    color: #6b7f92;
    font-size: 11px;
    font-weight: 700;
  }

  .evidence-row .supporting::before {
    content: '支持證據';
  }

  .evidence-row .opposing::before {
    content: '反對證據';
  }
}
</style>
