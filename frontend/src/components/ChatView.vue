<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import AnswerTurn from './AnswerTurn.vue'
import SourceList from './SourceList.vue'
import { askQuestion, clearHistory, fetchHistory, fetchProducts } from '../lib/api.js'
import { citedIndexes } from '../lib/citations.js'
import { applyStage, createTrace, finishTrace } from '../lib/trace.js'

const emit = defineEmits(['open-library'])

const SESSION_KEY = 'zhiku.session'
const WIDE_QUERY = '(min-width: 1080px)'

const turns = ref([])
const draft = ref('')
const busy = ref(false)
const products = ref(null) // null：还没加载到；[]：知识库为空
const sessionId = ref('')
const selectedId = ref(null)
const focus = ref(null) // { turnId, index, nonce }
const wide = ref(true)
const threadEl = ref(null)
const inputEl = ref(null)

let media = null
const onMedia = (event) => (wide.value = event.matches)

// 右侧出处栏展示哪一次回答：用户点选过的那次，否则是最近一次有出处的回答
const railTurn = computed(() => {
  const chosen = turns.value.find((turn) => turn.id === selectedId.value && turn.sources.length)
  return chosen || [...turns.value].reverse().find((turn) => turn.sources.length) || null
})
const railCited = computed(() => (railTurn.value ? citedIndexes(railTurn.value.answer) : []))
const railFocus = computed(() => (focus.value && focus.value.turnId === railTurn.value?.id ? focus.value : null))

function stored(action, value) {
  // 隐私模式等场景下 localStorage 可能不可用；会话记不住也不影响问答
  try {
    if (action === 'get') return localStorage.getItem(SESSION_KEY) || ''
    if (action === 'set') localStorage.setItem(SESSION_KEY, value)
    else localStorage.removeItem(SESSION_KEY)
  } catch {
    // 忽略
  }
  return ''
}

function newTurn(question) {
  return reactive({
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    question,
    status: 'running',
    trace: createTrace(),
    products: [],
    sources: [],
    answer: '',
    options: [],
    clarification: false,
    error: null,
    elapsedMs: null,
    final: false,
    restored: false,
  })
}

async function refreshProducts() {
  try {
    products.value = await fetchProducts()
  } catch {
    products.value = null
  }
}

async function restore() {
  const saved = stored('get')
  if (!saved) return
  try {
    const { items } = await fetchHistory(saved)
    const restored = []
    for (const item of items) {
      if (item.role === 'user') {
        restored.push({ ...newTurn(item.text), status: 'done', restored: true })
      } else if (restored.length) {
        const turn = restored[restored.length - 1]
        turn.answer = item.text
        turn.products = item.products || []
        turn.sources = item.sources || []
      }
    }
    if (restored.length && !turns.value.length) {
      turns.value = restored.map((turn) => reactive(turn))
      sessionId.value = saved
      scrollToLatest(false)
    }
  } catch {
    // 历史取不回来就从空白开始
  }
}

function nearBottom() {
  const el = threadEl.value
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 160
}

function scrollToLatest(smooth = true) {
  nextTick(() => {
    const el = threadEl.value
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  })
}

function handle(turn, event) {
  switch (event.type) {
    case 'session':
      sessionId.value = event.session_id
      stored('set', event.session_id)
      break
    case 'stage':
      applyStage(turn.trace, event)
      break
    case 'products':
      turn.products = event.items || []
      break
    case 'options':
      turn.clarification = true
      turn.answer = event.message || ''
      turn.options = event.items || []
      break
    case 'sources':
      turn.sources = event.items || []
      break
    case 'delta':
      turn.answer += event.text || ''
      break
    case 'final':
      turn.final = true
      turn.answer = event.answer || turn.answer
      turn.products = event.products || []
      turn.sources = event.sources || []
      turn.options = event.options || []
      turn.clarification = Boolean(event.needs_clarification)
      break
    case 'error':
      turn.error = event.message || '问答失败'
      break
  }
}

async function ask(text) {
  const question = (text ?? draft.value).trim()
  if (!question || busy.value) return
  if (text === undefined) draft.value = ''
  busy.value = true

  const turn = newTurn(question)
  turns.value.push(turn)
  selectedId.value = null
  focus.value = null
  scrollToLatest()

  const startedAt = performance.now()
  try {
    await askQuestion(question, sessionId.value, (event) => {
      const follow = nearBottom()
      handle(turn, event)
      if (follow) scrollToLatest(false)
    })
    // 流一旦开始，HTTP 状态码就是 200；是否成功要看有没有收到终态事件
    if (!turn.final && !turn.error) turn.error = '连接中断，回答没有收完。请重新提问。'
  } catch (error) {
    turn.error = error instanceof TypeError ? '连不上后端服务。请确认它已启动。' : error.message || '请求失败'
  } finally {
    finishTrace(turn.trace, { failed: Boolean(turn.error) })
    turn.elapsedMs = Math.round(performance.now() - startedAt)
    turn.status = turn.error ? 'error' : 'done'
    busy.value = false
    nextTick(() => inputEl.value?.focus())
  }
}

// 澄清时点选商品：带着选中的商品把原问题重新问一遍，不依赖模型去猜上下文
function pick(turn, option) {
  ask(`${turn.question}（${option}）`)
}

function cite(turn, index) {
  selectedId.value = turn.id
  focus.value = { turnId: turn.id, index, nonce: Date.now() }
}

async function startOver() {
  if (busy.value) return
  const previous = sessionId.value
  turns.value = []
  sessionId.value = ''
  selectedId.value = null
  focus.value = null
  stored('clear')
  if (previous) clearHistory(previous).catch(() => {})
  refreshProducts()
  nextTick(() => inputEl.value?.focus())
}

function useProduct(name) {
  draft.value = `${name} `
  nextTick(() => inputEl.value?.focus())
}

function onKeydown(event) {
  // 回车发送；输入法组词时的回车、Shift+回车换行都不发送
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    ask()
  }
}

onMounted(() => {
  media = window.matchMedia(WIDE_QUERY)
  wide.value = media.matches
  media.addEventListener('change', onMedia)
  refreshProducts()
  restore()
})
onBeforeUnmount(() => media?.removeEventListener('change', onMedia))

defineExpose({ refreshProducts })
</script>

<template>
  <div class="chat">
    <section class="column">
      <div ref="threadEl" class="thread">
        <div class="measure">
          <div v-if="turns.length === 0" class="opening">
            <h2>问商品，答有出处。</h2>
            <p class="lead">
              把说明书、规格表、售后政策交给智库。提问时它先确认你问的是哪款商品，再从资料里找出相关段落作答，并在回答里标出每个说法的出处。
            </p>

            <template v-if="products && products.length">
              <h3>已收录 {{ products.length }} 款商品的资料</h3>
              <ul class="shelf">
                <li v-for="product in products" :key="product.name">
                  <button type="button" @click="useProduct(product.name)">
                    <span class="name">{{ product.name }}</span>
                    <span class="count">{{ product.documents }} 份资料</span>
                  </button>
                </li>
              </ul>
              <p class="note">点一下商品名把它填进输入框，接着写你的问题。</p>
            </template>
            <template v-else-if="products">
              <h3>知识库还是空的</h3>
              <p class="note">先上传一份商品手册（PDF 或 Markdown），导入完成后就能提问。</p>
              <button type="button" class="primary" @click="emit('open-library')">去知识库上传资料</button>
            </template>
          </div>

          <div v-else aria-live="polite">
            <AnswerTurn
              v-for="turn in turns"
              :key="turn.id"
              :turn="turn"
              :busy="busy"
              :inline-sources="!wide"
              :selected="railTurn?.id === turn.id"
              :focus="!wide && focus?.turnId === turn.id ? focus : null"
              @cite="cite(turn, $event)"
              @pick="pick(turn, $event)"
              @select="selectedId = turn.id"
              @open-library="emit('open-library')"
            />
          </div>
        </div>
      </div>

      <form class="composer" @submit.prevent="ask()">
        <div class="measure row">
          <label class="visually-hidden" for="question-input">输入问题</label>
          <textarea
            id="question-input"
            ref="inputEl"
            v-model="draft"
            rows="1"
            maxlength="2000"
            placeholder="例如：ZG-12 数字万用表怎么换电池？"
            @keydown="onKeydown"
          ></textarea>
          <button type="submit" class="primary" :disabled="busy || !draft.trim()">{{ busy ? '回答中…' : '提问' }}</button>
          <button v-if="turns.length" type="button" class="quiet" :disabled="busy" @click="startOver">新对话</button>
        </div>
      </form>
    </section>

    <aside class="rail" aria-label="出处">
      <header>
        <h2>出处</h2>
        <p v-if="railTurn">{{ railTurn.question }}</p>
      </header>
      <SourceList v-if="railTurn" :sources="railTurn.sources" :cited="railCited" :focus="railFocus" />
      <div v-else class="rail-empty">
        <p>
          <span class="callout" aria-hidden="true">1</span>
          回答用到的资料会列在这里。正文里的橙色编号和这里的编号一一对应，点一下编号就能看到原文。
        </p>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.chat {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--rail-width);
  height: 100%;
  min-height: 0;
}

.column {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 0;
  background: var(--sheet);
}
.thread {
  overflow-y: auto;
  padding: 0 40px;
}
.measure {
  max-width: 780px;
  margin: 0 auto;
}

.opening {
  padding: 64px 0 40px;
}
.opening h2 {
  font-size: clamp(32px, 4.4vw, 46px);
  font-weight: 900;
  line-height: 1.2;
  letter-spacing: 0.02em;
  color: var(--blue-deep);
}
.opening .lead {
  margin-top: 16px;
  max-width: 34em;
  font-size: 16px;
  color: var(--ink-soft);
}
.opening h3 {
  margin-top: 40px;
  font-size: 15px;
  font-weight: 700;
}
.shelf {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  border-top: 2px solid var(--ink);
}
.shelf button {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 16px;
  width: 100%;
  padding: 12px 4px;
  border: 0;
  border-bottom: 1px solid var(--rule);
  background: none;
  text-align: left;
}
.shelf button:hover {
  background: var(--blue-wash);
}
.shelf .name {
  font-size: 17px;
  font-weight: 700;
}
.shelf .count {
  flex: none;
  font-size: 13px;
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
}
.note {
  margin-top: 10px;
  font-size: 13px;
  color: var(--ink-faint);
}
.opening .primary {
  margin-top: 16px;
}

.composer {
  padding: 12px 40px 18px;
  border-top: 1px solid var(--rule);
  background: var(--sheet);
}
.row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}
textarea {
  flex: 1;
  min-width: 0;
  resize: none;
  field-sizing: content;
  min-height: 44px;
  max-height: 140px;
  padding: 10px 14px;
  border: 1px solid var(--rule-strong);
  border-radius: 4px;
  background: #fff;
  line-height: 1.5;
}
textarea::placeholder {
  color: var(--ink-faint);
}
textarea:focus-visible {
  outline: 2px solid var(--blue);
  outline-offset: 0;
  border-color: var(--blue);
}
.primary {
  height: 44px;
  padding: 0 22px;
  border: 0;
  border-radius: 4px;
  background: var(--blue);
  color: #fff;
  font-weight: 700;
  letter-spacing: 0.06em;
  white-space: nowrap;
}
.primary:hover:not(:disabled) {
  background: var(--blue-deep);
}
.primary:disabled {
  background: var(--rule-strong);
}
.quiet {
  height: 44px;
  padding: 0 12px;
  border: 0;
  background: none;
  color: var(--ink-soft);
  font-size: 13.5px;
  white-space: nowrap;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.quiet:hover:not(:disabled) {
  color: var(--blue);
}

.rail {
  overflow-y: auto;
  padding: 0 22px 24px;
  border-left: 1px solid var(--rule-strong);
  background: var(--paper);
}
.rail header {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 22px 0 10px;
  background: var(--paper);
  border-bottom: 2px solid var(--ink);
}
.rail h2 {
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0.08em;
}
.rail header p {
  margin-top: 2px;
  font-size: 12.5px;
  color: var(--ink-soft);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rail-empty p {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 12px;
  padding-top: 16px;
  font-size: 13.5px;
  color: var(--ink-soft);
}

@media (max-width: 1079px) {
  .chat {
    grid-template-columns: minmax(0, 1fr);
  }
  .rail {
    display: none;
  }
}

@media (max-width: 720px) {
  .thread {
    padding: 0 18px;
  }
  .composer {
    padding: 10px 14px 12px;
  }
  .opening {
    padding: 36px 0 28px;
  }
  .row {
    flex-wrap: wrap;
  }
  .quiet {
    height: 28px;
    padding: 0;
    order: 3;
  }
}
</style>
