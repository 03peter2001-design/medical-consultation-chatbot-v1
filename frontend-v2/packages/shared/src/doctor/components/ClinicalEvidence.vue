<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ clinical: { type: Object, required: true } })
const showAll = ref(false)
const visibleDifferentials = computed(() =>
  showAll.value ? props.clinical.allDifferentials : props.clinical.differentials,
)
const safetyDirections = computed(
  () => props.clinical.safetyTriggeredConditions || [],
)
</script>

<template>
  <div class="evidence-layout">
    <section class="evidence-panel">
      <header class="panel-heading">
        <div><span>臨床推論</span><h3>鑑別方向與證據</h3></div>
        <strong>{{ visibleDifferentials.length }}</strong>
      </header>
      <section v-if="safetyDirections.length" class="safety-directions">
        <h4>安全規則優先方向</h4>
        <article v-for="item in safetyDirections" :key="item.id || item.condition">
          <strong>{{ item.condition }}</strong>
          <ul>
            <li v-for="trigger in item.triggers" :key="`${trigger.ruleCode}-${trigger.evidence}`">
              {{ trigger.ruleLabel || trigger.ruleCode }}：{{ trigger.evidence }}
            </li>
          </ul>
        </article>
      </section>
      <div v-if="visibleDifferentials.length" class="differential-list">
        <article v-for="hypothesis in visibleDifferentials" :key="hypothesis.id || hypothesis.condition">
          <header>
            <strong>{{ hypothesis.condition }}</strong>
            <small>淨票 {{ hypothesis.netVotes }} · 支持 {{ hypothesis.supportVotes }} · 反對 {{ hypothesis.opposeVotes }}</small>
          </header>
          <div class="evidence-columns">
            <ul><li v-for="item in hypothesis.supporting_evidence" :key="item">{{ item }}</li></ul>
            <ul class="opposing"><li v-for="item in hypothesis.opposing_evidence" :key="item">{{ item }}</li></ul>
          </div>
        </article>
      </div>
      <p v-else class="empty-state">目前尚無可顯示的鑑別方向。</p>
      <button
        v-if="clinical.allDifferentials.length > clinical.differentials.length"
        class="toggle-button"
        type="button"
        @click="showAll = !showAll"
      >{{ showAll ? '收合鑑別方向' : '顯示全部鑑別方向' }}</button>
      <div v-if="clinical.knowledgeGaps.length" class="knowledge-gaps">
        <strong>待補資訊</strong>
        <span v-for="gap in clinical.knowledgeGaps" :key="gap">{{ gap }}</span>
      </div>
    </section>
    <section v-if="clinical.timeline.length" class="timeline-panel">
      <header class="panel-heading">
        <div><span>問診軌跡</span><h3>臨床決策歷程</h3></div>
        <strong>{{ clinical.timeline.length }}</strong>
      </header>
      <ol>
        <li v-for="event in clinical.timeline" :key="`${event.turn}-${event.field}`">
          <strong>#{{ event.turn }} {{ event.actionLabel }}</strong>
          <span>{{ event.question || event.answer }}</span>
          <small>{{ event.sourceLabel }}</small>
        </li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.evidence-layout { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(260px, 0.65fr); gap: 16px; }
.evidence-panel, .timeline-panel { padding: 18px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
.panel-heading, .differential-list article > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.panel-heading span, .differential-list small, .timeline-panel small { color: var(--muted); font-size: 12px; }
.panel-heading h3 { margin: 2px 0 0; }
.safety-directions { margin: 16px 0; padding: 14px; border-left: 4px solid var(--danger); border-radius: 6px; background: var(--red-soft); }
.safety-directions article + article, .differential-list article + article { margin-top: 12px; }
.safety-directions ul, .evidence-columns ul { margin: 8px 0 0; padding-left: 20px; }
.differential-list { display: grid; gap: 12px; margin-top: 16px; }
.differential-list article { padding: 14px; border: 1px solid var(--border); border-radius: 8px; }
.evidence-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.opposing, .empty-state { color: var(--muted); }
.toggle-button { margin-top: 14px; border: 0; background: transparent; color: var(--blue); cursor: pointer; }
.knowledge-gaps { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.knowledge-gaps span { padding: 4px 8px; border-radius: 999px; background: var(--blue-soft); }
.timeline-panel ol { display: grid; gap: 12px; padding-left: 20px; }
.timeline-panel li span, .timeline-panel li small { display: block; margin-top: 3px; }
@media (max-width: 920px) { .evidence-layout, .evidence-columns { grid-template-columns: 1fr; } }
</style>
