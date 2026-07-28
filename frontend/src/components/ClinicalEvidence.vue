<script setup>
import TerminologyCode from './TerminologyCode.vue'

defineProps({
  clinical: { type: Object, required: true },
})
</script>

<template>
  <div class="evidence-layout">
    <section class="evidence-panel">
      <div class="panel-heading">
        <div>
          <span>依問診證據整理</span>
          <h3>鑑別診斷</h3>
        </div>
        <strong>{{ clinical.differentials.length }} 項</strong>
      </div>

      <div v-if="clinical.differentials.length" class="evidence-table">
        <div class="evidence-table-head" aria-hidden="true">
          <span>可能診斷</span>
          <span>支持證據</span>
          <span>反對證據</span>
        </div>
        <article
          v-for="hypothesis in clinical.differentials"
          :key="hypothesis.condition"
          class="evidence-row"
        >
          <h4>
            <span>{{ hypothesis.condition }}</span>
            <TerminologyCode
              v-if="hypothesis.coding"
              :coding="hypothesis.coding"
            />
            <small v-else class="uncoded-condition">未編碼</small>
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
        </article>
      </div>
      <div v-else class="panel-empty">
        <strong>尚未建立鑑別診斷</strong>
        <span>目前資料不足，請參考臨床警訊與 AI 初步評估。</span>
      </div>

      <div v-if="clinical.knowledgeGaps.length" class="knowledge-gaps">
        <strong>仍需補充</strong>
        <span v-for="gap in clinical.knowledgeGaps" :key="gap">
          {{ gap }}
        </span>
      </div>

      <aside class="terminology-note">
        <strong>標準術語</strong>
        <span>
          僅顯示 FHIR 原始 Coding；「未編碼」不會由系統自行猜測。
          <template v-if="clinical.terminologyReference">
            本機參照
            {{ clinical.terminologyReference.package }}#{{
              clinical.terminologyReference.version
            }}。
          </template>
        </span>
      </aside>
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
