<script setup>
import { nextTick, ref, watch } from 'vue'
import { renderMarkdown } from '../lib/markdown.js'
import { ROUTE_LABELS } from '../lib/trace.js'

const props = defineProps({
  sources: { type: Array, required: true },
  // 回答里实际引用到的编号；没被引用的资料排在后面并且颜色更淡
  cited: { type: Array, default: () => [] },
  // 需要定位的出处：{ index, nonce }，nonce 变化时重新滚动并展开
  focus: { type: Object, default: null },
})

const expanded = ref(new Set())
const flashed = ref(null)
const listEl = ref(null)

function toggle(index) {
  const next = new Set(expanded.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  expanded.value = next
}

function where(source) {
  if (source.source === 'web') return hostname(source.url)
  return source.file_title || source.product || ''
}

function heading(source) {
  if (source.source === 'web') return source.title || source.url
  const own = source.title || source.file_title
  // 上级标题就是文档标题时不必重复，文档名已经写在下一行
  const parent = source.parent_title
  return parent && parent !== own && parent !== source.file_title ? `${parent} › ${own}` : own
}

function hostname(url) {
  try {
    return new URL(url).hostname
  } catch {
    return '网页'
  }
}

function routes(source) {
  return (source.routes || []).map((route) => ROUTE_LABELS[route]).filter(Boolean)
}

watch(
  () => props.focus,
  (focus) => {
    if (!focus) return
    expanded.value = new Set([...expanded.value, focus.index])
    flashed.value = focus.index
    nextTick(() => {
      const card = listEl.value?.querySelector(`[data-source="${focus.index}"]`)
      card?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
    setTimeout(() => {
      if (flashed.value === focus.index) flashed.value = null
    }, 1600)
  },
)

watch(
  () => props.sources,
  () => {
    expanded.value = new Set()
  },
)
</script>

<template>
  <ol ref="listEl" class="sources">
    <li
      v-for="source in sources"
      :key="source.index"
      :data-source="source.index"
      :class="{ uncited: cited.length > 0 && !cited.includes(source.index), flash: flashed === source.index }"
    >
      <span class="callout" aria-hidden="true">{{ source.index }}</span>
      <div class="body">
        <h3>
          <span class="visually-hidden">出处 {{ source.index }}：</span>{{ heading(source) }}
        </h3>
        <p class="where">
          <a v-if="source.source === 'web' && source.url" :href="source.url" target="_blank" rel="noopener noreferrer">{{ where(source) }}</a>
          <template v-else>{{ where(source) }}</template>
        </p>

        <div
          v-if="expanded.has(source.index) && source.content"
          class="prose prose-compact content"
          v-html="renderMarkdown(source.content)"
        ></div>
        <p v-else class="snippet">{{ source.snippet }}</p>

        <p class="meta">
          <button
            v-if="source.content && source.content.trim() !== (source.snippet || '').trim()"
            type="button"
            :aria-expanded="expanded.has(source.index)"
            @click="toggle(source.index)"
          >
            {{ expanded.has(source.index) ? '收起' : '展开原文' }}
          </button>
          <span v-for="route in routes(source)" :key="route" class="route">{{ route }}</span>
          <span v-if="source.score !== null && source.score !== undefined" class="score">
            相关度 {{ Number(source.score).toFixed(2) }}
          </span>
        </p>
      </div>
    </li>
  </ol>
</template>

<style scoped>
.sources {
  list-style: none;
  margin: 0;
  padding: 0;
}
li {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid var(--rule);
  transition: background-color 0.5s ease;
}
li:last-child {
  border-bottom: 0;
}
li.flash {
  background: var(--callout-wash);
  box-shadow: -12px 0 0 var(--callout-wash), 12px 0 0 var(--callout-wash);
}
li.uncited .callout {
  background: none;
  color: var(--ink-faint);
  box-shadow: inset 0 0 0 1.5px var(--rule-strong);
}
li.uncited h3 {
  color: var(--ink-soft);
}

h3 {
  font-size: 14.5px;
  font-weight: 700;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.where {
  margin-top: 1px;
  font-size: 12.5px;
  color: var(--ink-faint);
  overflow-wrap: anywhere;
}
.where a {
  color: var(--blue);
}
.snippet {
  margin-top: 6px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}
.content {
  margin-top: 8px;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-faint);
}
.meta button {
  border: 0;
  background: none;
  padding: 0;
  color: var(--blue);
  font-size: 12.5px;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.route {
  padding: 0 6px;
  border: 1px solid var(--rule-strong);
  border-radius: 3px;
  color: var(--ink-soft);
  line-height: 1.6;
}
.score {
  font-variant-numeric: tabular-nums;
}
</style>
