<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { deleteDocument, fetchDocuments, uploadDocuments } from '../lib/api.js'
import { formatDuration } from '../lib/trace.js'

const props = defineProps({ active: { type: Boolean, default: false } })
const emit = defineEmits(['changed'])

const ACCEPT = '.pdf,.md,.markdown'
const POLL_MS = 1500
const PARSER_NAMES = { pymupdf: '内置解析', mineru: 'MinerU', markdown: 'Markdown' }

const documents = ref(null)
const loadFailed = ref(false)
const product = ref('')
const uploading = ref(false)
const dragging = ref(false)
const notices = ref([]) // 上传被拒绝的文件及原因
const opened = ref(new Set())
const confirming = ref(null)
const deleting = ref(null)
const rowError = ref({})
const fileInput = ref(null)

let timer = null
let lastWorking = 0

const working = computed(() => (documents.value || []).filter((doc) => ['pending', 'processing'].includes(doc.status)).length)
const totals = computed(() => {
  const done = (documents.value || []).filter((doc) => doc.status === 'completed')
  return {
    documents: done.length,
    chunks: done.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0),
    products: new Set(done.map((doc) => doc.product).filter(Boolean)).size,
  }
})

async function refresh() {
  try {
    documents.value = await fetchDocuments()
    loadFailed.value = false
  } catch {
    loadFailed.value = true
  }
  // 有文档刚导入完成（或失败）时，问答页的商品列表也要跟着更新
  if (working.value < lastWorking) emit('changed')
  lastWorking = working.value
  schedule()
}

function schedule() {
  clearTimeout(timer)
  if (working.value > 0) timer = setTimeout(refresh, POLL_MS)
}

async function upload(fileList) {
  const files = [...(fileList || [])]
  if (!files.length || uploading.value) return
  uploading.value = true
  notices.value = []
  try {
    const result = await uploadDocuments(files, product.value.trim())
    notices.value = result.rejected || []
    if (result.accepted?.length) product.value = ''
  } catch (error) {
    notices.value = [{ file_name: '', reason: error instanceof TypeError ? '连不上后端服务，文件没有上传。' : error.message }]
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
    await refresh()
  }
}

function onDrop(event) {
  dragging.value = false
  upload(event.dataTransfer?.files)
}

function toggle(docId) {
  const next = new Set(opened.value)
  if (next.has(docId)) next.delete(docId)
  else next.add(docId)
  opened.value = next
}

async function remove(doc) {
  if (confirming.value !== doc.doc_id) {
    confirming.value = doc.doc_id
    return
  }
  confirming.value = null
  deleting.value = doc.doc_id
  rowError.value = { ...rowError.value, [doc.doc_id]: '' }
  try {
    await deleteDocument(doc.doc_id)
    emit('changed')
  } catch (error) {
    rowError.value = { ...rowError.value, [doc.doc_id]: error.message || '删除失败' }
  } finally {
    deleting.value = null
    await refresh()
  }
}

function statusText(doc) {
  if (doc.status === 'completed') return '已入库'
  if (doc.status === 'failed') return '导入失败'
  if (doc.status === 'pending') return '排队中'
  return doc.stage || '处理中'
}

function when(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp * 1000)
  const pad = (value) => String(value).padStart(2, '0')
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

watch(
  () => props.active,
  (active) => {
    if (active) refresh()
  },
)
onMounted(refresh)
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div class="library">
    <div class="measure">
      <header class="head">
        <h2>知识库</h2>
        <p v-if="documents && documents.length">
          已入库 {{ totals.documents }} 份资料，覆盖 {{ totals.products }} 款商品，共 {{ totals.chunks }} 个片段。
        </p>
        <p v-else>上传商品的说明书、规格表或售后政策，导入后就能在“问答”里提问。</p>
      </header>

      <section
        class="dropzone"
        :class="{ dragging, uploading }"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <div class="drop-main">
          <p class="drop-title">把 PDF 或 Markdown 文件拖到这里</p>
          <p class="drop-sub">可以一次放多份，单个文件不超过 50 MB。同名文件再次上传会替换旧版本。</p>
        </div>
        <div class="drop-actions">
          <label class="field">
            <span>商品名称（可不填）</span>
            <input v-model="product" type="text" maxlength="40" placeholder="留空则从资料里自动识别" :disabled="uploading" />
          </label>
          <button type="button" class="primary" :disabled="uploading" @click="fileInput?.click()">
            {{ uploading ? '上传中…' : '选择文件' }}
          </button>
          <input ref="fileInput" class="visually-hidden" type="file" multiple :accept="ACCEPT" tabindex="-1" @change="upload($event.target.files)" />
        </div>
      </section>

      <ul v-if="notices.length" class="notices" role="alert">
        <li v-for="(notice, index) in notices" :key="index">{{ notice.reason }}</li>
      </ul>

      <p v-if="loadFailed" class="load-failed" role="alert">读不到文档列表。请确认后端服务已启动。</p>

      <section v-if="documents && documents.length" class="docs" aria-live="polite">
        <article v-for="doc in documents" :key="doc.doc_id" class="doc" :class="doc.status">
          <div class="doc-main">
            <div class="doc-title">
              <h3>{{ doc.file_name }}</h3>
              <p class="doc-sub">
                <span v-if="doc.product" class="product">{{ doc.product }}</span>
                <span>{{ when(doc.created_at) }} 上传</span>
              </p>
            </div>

            <div class="doc-state">
              <template v-if="doc.status === 'completed'">
                <p class="figures">
                  <span><b>{{ doc.chunk_count }}</b> 个片段</span>
                  <span v-if="doc.image_count"><b>{{ doc.image_count }}</b> 张图片</span>
                </p>
                <p class="state ok">已入库<template v-if="PARSER_NAMES[doc.parser]">，{{ PARSER_NAMES[doc.parser] }}</template></p>
              </template>
              <template v-else-if="doc.status === 'failed'">
                <p class="state fail">导入失败</p>
              </template>
              <template v-else>
                <div class="bar" role="progressbar" :aria-valuenow="doc.progress || 0" aria-valuemin="0" aria-valuemax="100" :aria-label="`${doc.file_name} 的导入进度`">
                  <span :style="{ width: `${Math.max(doc.progress || 0, 3)}%` }"></span>
                </div>
                <p class="state run">{{ statusText(doc) }}</p>
              </template>
            </div>

            <div class="doc-actions">
              <button v-if="doc.steps?.length" type="button" class="link" :aria-expanded="opened.has(doc.doc_id)" @click="toggle(doc.doc_id)">
                {{ opened.has(doc.doc_id) ? '收起过程' : '导入过程' }}
              </button>
              <button
                v-if="doc.status === 'completed' || doc.status === 'failed'"
                type="button"
                class="link danger"
                :disabled="deleting === doc.doc_id"
                @click="remove(doc)"
                @blur="confirming === doc.doc_id && (confirming = null)"
              >
                {{ deleting === doc.doc_id ? '删除中…' : confirming === doc.doc_id ? '确认删除' : '删除' }}
              </button>
            </div>
          </div>

          <p v-if="doc.status === 'failed' && doc.error" class="doc-error">{{ doc.error }}</p>
          <p v-if="rowError[doc.doc_id]" class="doc-error">{{ rowError[doc.doc_id] }}</p>

          <ol v-if="opened.has(doc.doc_id) && doc.steps?.length" class="steps">
            <li v-for="(step, index) in doc.steps" :key="index" :class="step.status">
              <span class="step-label">{{ step.label }}</span>
              <span class="step-detail">{{ step.detail || (step.status === 'skipped' ? '跳过' : '完成') }}</span>
              <span class="step-time">{{ step.status === 'done' ? formatDuration(step.elapsed_ms) : '' }}</span>
            </li>
          </ol>
        </article>
      </section>

      <section v-else-if="documents" class="empty">
        <h3>还没有资料</h3>
        <p>仓库里的 samples 目录有三份示例手册，可以先拿它们试试。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.library {
  height: 100%;
  overflow-y: auto;
  padding: 0 40px 48px;
  background: var(--sheet);
}
.measure {
  max-width: 980px;
  margin: 0 auto;
}

.head {
  padding: 40px 0 22px;
}
.head h2 {
  font-size: 30px;
  font-weight: 900;
  letter-spacing: 0.02em;
  color: var(--blue-deep);
}
.head p {
  margin-top: 6px;
  color: var(--ink-soft);
  font-variant-numeric: tabular-nums;
}

.dropzone {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 20px 32px;
  padding: 22px 24px;
  border: 1.5px dashed var(--blue);
  border-radius: 6px;
  background: var(--blue-wash);
}
.dropzone.dragging {
  border-style: solid;
  background: #d3e0f2;
}
.drop-title {
  font-size: 17px;
  font-weight: 800;
  color: var(--blue-deep);
}
.drop-sub {
  margin-top: 2px;
  font-size: 13px;
  color: var(--ink-soft);
}
.drop-actions {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.field {
  display: grid;
  gap: 3px;
  font-size: 12.5px;
  color: var(--ink-soft);
}
.field input {
  width: 230px;
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--rule-strong);
  border-radius: 4px;
  background: #fff;
  font-size: 14px;
}
.field input::placeholder {
  color: var(--ink-faint);
}
.primary {
  height: 40px;
  padding: 0 20px;
  border: 0;
  border-radius: 4px;
  background: var(--blue);
  color: #fff;
  font-weight: 700;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.primary:hover:not(:disabled) {
  background: var(--blue-deep);
}
.primary:disabled {
  background: var(--rule-strong);
}

.notices {
  list-style: none;
  margin: 12px 0 0;
  padding: 10px 14px;
  border-left: 3px solid var(--fail);
  background: var(--fail-wash);
  color: var(--fail);
  font-size: 14px;
}
.load-failed {
  margin-top: 16px;
  color: var(--fail);
}

.docs {
  margin-top: 28px;
  border-top: 2px solid var(--ink);
}
.doc {
  padding: 16px 4px;
  border-bottom: 1px solid var(--rule);
}
.doc-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px 150px;
  align-items: center;
  gap: 8px 24px;
}
.doc-title h3 {
  font-size: 16px;
  font-weight: 700;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.doc-sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
}
.product {
  padding: 0 8px;
  border: 1px solid var(--blue);
  border-radius: 3px;
  background: var(--blue-wash);
  color: var(--blue);
  font-weight: 600;
  line-height: 1.7;
}

.figures {
  display: flex;
  gap: 14px;
  font-size: 13.5px;
  color: var(--ink-soft);
  font-variant-numeric: tabular-nums;
}
.figures b {
  font-size: 17px;
  font-weight: 800;
  color: var(--ink);
}
.state {
  margin-top: 2px;
  font-size: 12.5px;
}
.state.ok {
  color: var(--ok);
}
.state.fail {
  color: var(--fail);
  font-weight: 700;
  font-size: 14px;
}
.state.run {
  color: var(--blue);
}
.bar {
  height: 6px;
  border-radius: 3px;
  background: var(--rule);
  overflow: hidden;
}
.bar span {
  display: block;
  height: 100%;
  background: var(--blue);
  transition: width 0.4s ease;
}

.doc-actions {
  display: flex;
  justify-content: flex-end;
  gap: 16px;
}
.link {
  border: 0;
  background: none;
  padding: 0;
  color: var(--blue);
  font-size: 13.5px;
  text-decoration: underline;
  text-underline-offset: 3px;
  white-space: nowrap;
}
.link.danger {
  color: var(--fail);
}
.link:disabled {
  color: var(--ink-faint);
}

.doc-error {
  margin-top: 10px;
  padding: 8px 12px;
  border-left: 3px solid var(--fail);
  background: var(--fail-wash);
  color: var(--fail);
  font-size: 13.5px;
  overflow-wrap: anywhere;
}

.steps {
  list-style: none;
  margin: 12px 0 0;
  padding: 4px 0 4px 14px;
  border-left: 2px solid var(--rule);
  font-size: 13px;
}
.steps li {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) auto;
  gap: 12px;
  padding: 3px 0;
}
.step-label {
  font-weight: 600;
}
.step-detail {
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}
.step-time {
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.steps li.skipped {
  color: var(--ink-faint);
}
.steps li.skipped .step-label {
  font-weight: 400;
}

.empty {
  margin-top: 28px;
  padding: 28px 4px;
  border-top: 2px solid var(--ink);
}
.empty h3 {
  font-size: 17px;
  font-weight: 800;
}
.empty p {
  margin-top: 4px;
  color: var(--ink-soft);
}

@media (max-width: 860px) {
  .dropzone {
    grid-template-columns: minmax(0, 1fr);
  }
  .drop-actions {
    flex-wrap: wrap;
  }
  .doc-main {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .doc-title {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .library {
    padding: 0 18px 32px;
  }
  .head {
    padding-top: 26px;
  }
  .field,
  .field input {
    width: 100%;
  }
  .field {
    flex: 1 1 100%;
  }
}
</style>
