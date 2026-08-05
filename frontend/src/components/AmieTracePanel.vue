<script setup>
defineProps({
  traces: { type: Array, default: () => [] },
})

function actionLabel(action) {
  return (
    {
      ask: '繼續追問',
      complete: '結束問診',
      handoff: '轉交醫療人員',
    }[action] || action || '未記錄'
  )
}

function sourceLabel(source) {
  return (
    {
      safety_rule: 'Safety 規則',
      semantic_safety_fail_closed: '語意安全保守轉交',
      route_guard: '主訴路由守門',
      deterministic_flow: '確定性流程',
      deterministic_fallback: '確定性 fallback',
      deterministic_disease_vote: '固定疾病表投票',
    }[source] || source || '未記錄'
  )
}

function phaseLabel(phase) {
  return (
    {
      broad: '廣泛區辨',
      differentiate: '候選區辨',
      confirm: '領先疾病確認',
    }[phase] || phase || '未記錄'
  )
}

function tierLabel(tier) {
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
  <details v-if="traces.length" class="amie-debug-panel">
    <summary>AMIE 測試軌跡（{{ traces.length }} 輪）</summary>
    <article
      v-for="trace in traces"
      :key="trace.turn"
      class="amie-debug-turn"
    >
      <header>
        <strong>T{{ trace.turn }}</strong>
        <span>{{ actionLabel(trace.decision?.action) }}</span>
        <span>{{ sourceLabel(trace.decision?.source) }}</span>
      </header>
      <p>
        <b>題目</b>
        {{ trace.question?.prompt || '未記錄' }}
      </p>
      <p><b>回答</b>{{ trace.answer || '未記錄' }}</p>
      <p>
        <b>結果</b>
        {{
          (trace.result?.clinical_facts || [])
            .map(
              (fact) =>
                `${fact.code}=${fact.status === 'absent' ? '否認' : '有'}`,
            )
            .join('、') || '本輪沒有新增標準線索'
        }}
      </p>
      <p>
        <b>決定</b>
        {{
          trace.decision?.next_question
            ? `下一題：${trace.decision.next_question}`
            : actionLabel(trace.decision?.action)
        }}
      </p>
      <section v-if="trace.funnel" class="trace-funnel">
        <strong>
          目前漏斗 · {{ phaseLabel(trace.funnel.selection_phase) }}
        </strong>
        <span>{{ tierLabel(trace.funnel.selection_tier) }}</span>
        <span>候選疾病 {{ trace.funnel.candidate_count }} 項</span>
        <span v-if="trace.funnel.target_fact_codes?.length">
          目標標籤：{{ trace.funnel.target_fact_codes.join('、') }}
        </span>
        <small>
          區辨
          {{ trace.funnel.funnel_score?.discrimination_score || 0 }} ·
          確認 {{ trace.funnel.funnel_score?.confirmation_score || 0 }} ·
          反證 {{ trace.funnel.funnel_score?.refutation_score || 0 }}
        </small>
      </section>
      <p><b>理由</b>{{ trace.reason || '未記錄' }}</p>
      <p v-if="trace.model_error" class="trace-warning">
        <b>Fallback</b>{{ trace.model_error }}
      </p>
    </article>
  </details>
</template>

<style scoped>
.amie-debug-panel {
  width: min(100%, 720px);
  align-self: flex-start;
  border: 1px dashed #8caeca;
  border-radius: 9px;
  background: #f4f8fc;
  color: #294860;
}

.amie-debug-panel > summary {
  padding: 11px 14px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
}

.amie-debug-turn {
  display: grid;
  gap: 5px;
  padding: 12px 14px;
  border-top: 1px solid #ccdae6;
}

.amie-debug-turn header {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.amie-debug-turn header strong,
.amie-debug-turn header span {
  padding: 2px 6px;
  border-radius: 999px;
  background: #e2edf6;
  color: #356181;
  font-size: 11px;
}

.amie-debug-turn p {
  color: #536f84;
  font-size: 12px;
  line-height: 1.55;
}

.amie-debug-turn p b {
  display: inline-block;
  min-width: 42px;
  margin-right: 5px;
  color: #294860;
}

.trace-funnel {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding: 8px 10px;
  border: 1px solid #b9d2e5;
  border-radius: 7px;
  background: #eaf3fa;
  color: #355d79;
  font-size: 11px;
}

.trace-funnel strong {
  width: 100%;
  color: #294f6c;
}

.trace-funnel span {
  padding: 2px 6px;
  border-radius: 999px;
  background: #d8e9f5;
}

.trace-funnel small {
  width: 100%;
  color: #5f7c91;
}

.amie-debug-turn .trace-warning {
  color: #ad3340;
}
</style>
