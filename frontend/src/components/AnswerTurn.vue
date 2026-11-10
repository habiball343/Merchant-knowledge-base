<script setup>
import { computed } from 'vue'
import SourceList from './SourceList.vue'
import TraceLine from './TraceLine.vue'
import { citedIndexes } from '../lib/citations.js'
import { renderAnswer } from '../lib/markdown.js'

const props = defineProps({
  turn: { type: Object, required: true },
  busy: { type: Boolean, default: false },
  // 窄屏时出处直接列在回答下面；宽屏时由右侧的出处栏展示
  inlineSources: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  focus: { type: Object, default: null },
})
const emit = defineEmits(['cite', 'pick', 'open-library', 'select'])

const html = computed(() => renderAnswer(props.turn.answer, props.turn.sources))
const cited = computed(() => citedIndexes(props.turn.answer))
const running = computed(() => props.turn.status === 'running')
// 知识库为空时后端同样要求"澄清"，但没有可选的商品
const libraryEmpty = computed(
  () => props.turn.clarification && props.turn.options.length === 0 && props.turn.status === 'done',
)

function citeFromEvent(event) {
  const target = event.target.closest?.('sup.cite')
  if (!target) return
  if (event.type === 'keydown') {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
  }
  emit('cite', Number(target.dataset.cite))
}
</script>

<template>
  <article class="turn" :class="{ selected }">
    <h2 class="question">{{ turn.question }}</h2>

    <p v-if="turn.products.length" class="products">
      <span class="visually-hidden">针对的商品：</span>
      <span v-for="name in turn.products" :key="name" class="product">{{ name }}</span>
    </p>

    <TraceLine v-if="!turn.restored" :trace="turn.trace" :running="running" :elapsed-ms="turn.elapsedMs" />

    <div v-if="turn.answer" class="answer">
      <div class="prose" @click="citeFromEvent" @keydown="citeFromEvent" v-html="html"></div>
      <span v-if="running && !turn.clarification" class="caret" aria-hidden="true"></span>
    </div>

    <ul v-if="turn.options.length" class="options" aria-label="可选的商品">
      <li v-for="option in turn.options" :key="option">
        <button type="button" :disabled="busy" @click="emit('pick', option)">{{ option }}</button>
      </li>
    </ul>

    <p v-if="libraryEmpty" class="follow">
      <button type="button" class="link" @click="emit('open-library')">去知识库上传资料</button>
    </p>

    <p v-if="turn.error" class="error" role="alert">{{ turn.error }}</p>

    <template v-if="turn.sources.length">
      <details v-if="inlineSources" class="inline-sources" :open="Boolean(focus)">
        <summary>{{ turn.sources.length }} 条出处</summary>
        <SourceList :sources="turn.sources" :cited="cited" :focus="focus" />
      </details>
      <p v-else-if="!selected && turn.status !== 'running'" class="follow">
        <button type="button" class="link" @click="emit('select')">在右侧查看这次回答的 {{ turn.sources.length }} 条出处</button>
      </p>
    </template>
  </article>
</template>

<style scoped>
.turn {
  padding: 30px 0 32px;
  border-bottom: 1px solid var(--rule);
}
.turn:last-child {
  border-bottom: 0;
}

.question {
  font-size: 21px;
  font-weight: 800;
  line-height: 1.45;
  letter-spacing: 0.01em;
  overflow-wrap: anywhere;
}

.products {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.product {
  padding: 1px 9px;
  border: 1px solid var(--blue);
  border-radius: 3px;
  color: var(--blue);
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.7;
  background: var(--blue-wash);
}

.answer {
  margin-top: 18px;
  max-width: 44em;
}
.caret {
  display: inline-block;
  width: 8px;
  height: 17px;
  margin-top: 6px;
  background: var(--blue);
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  to {
    visibility: hidden;
  }
}

.options {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 14px 0 0;
  padding: 0;
}
.options button {
  padding: 7px 14px;
  border: 1px solid var(--blue);
  border-radius: 4px;
  background: var(--sheet);
  color: var(--blue-deep);
  font-weight: 600;
}
.options button:hover:not(:disabled) {
  background: var(--blue);
  color: #fff;
}
.options button:disabled {
  border-color: var(--rule-strong);
  color: var(--ink-faint);
}

.follow {
  margin-top: 14px;
  font-size: 13px;
}
.link {
  border: 0;
  background: none;
  padding: 0;
  color: var(--blue);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.error {
  margin-top: 16px;
  padding: 10px 14px;
  border-left: 3px solid var(--fail);
  background: var(--fail-wash);
  color: var(--fail);
  font-size: 14px;
}

.inline-sources {
  margin-top: 18px;
  border-top: 1px solid var(--rule);
}
.inline-sources summary {
  padding: 10px 0 2px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--blue);
  cursor: pointer;
}
</style>
