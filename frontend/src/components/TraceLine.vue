<script setup>
import { computed } from 'vue'
import { formatDuration } from '../lib/trace.js'

const props = defineProps({
  trace: { type: Array, required: true },
  running: { type: Boolean, default: false },
  elapsedMs: { type: Number, default: null },
})

const STATUS_TEXT = { pending: '等待', running: '进行中', done: '完成', skipped: '跳过', failed: '失败', idle: '未执行' }

const current = computed(() => props.trace.find((step) => step.status === 'running'))
const touched = computed(() => props.trace.some((step) => !['pending', 'idle'].includes(step.status)))

const summary = computed(() => {
  if (props.running) return current.value ? `正在${current.value.label}…` : '正在处理…'
  const failed = props.trace.find((step) => step.status === 'failed')
  if (failed) return `${failed.label}这一步失败了`
  const total = formatDuration(props.elapsedMs)
  return total ? `查看检索过程，用时 ${total}` : '查看检索过程'
})
</script>

<template>
  <details v-if="touched || running" class="trace">
    <summary :class="{ running }">
      <span v-if="running" class="pulse" aria-hidden="true"></span>{{ summary }}
    </summary>
    <ol>
      <li v-for="step in trace" :key="step.node" :class="step.status">
        <span class="mark" aria-hidden="true"></span>
        <span class="label">{{ step.label }}</span>
        <span class="detail">{{ step.detail || STATUS_TEXT[step.status] }}</span>
        <span class="time">{{ step.status === 'done' ? formatDuration(step.elapsedMs) : '' }}</span>
      </li>
    </ol>
  </details>
</template>

<style scoped>
.trace {
  margin-top: 10px;
  font-size: 13px;
}
summary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-soft);
  cursor: pointer;
  list-style: none;
  border-bottom: 1px dashed var(--rule-strong);
  padding-bottom: 1px;
}
summary::-webkit-details-marker {
  display: none;
}
summary:hover {
  color: var(--blue);
  border-bottom-color: var(--blue);
}
summary.running {
  color: var(--blue);
  border-bottom-color: transparent;
}
.pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--blue);
  animation: pulse 1.1s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.25;
  }
}

ol {
  list-style: none;
  margin: 10px 0 0;
  padding: 2px 0 2px 14px;
  border-left: 2px solid var(--rule);
}
li {
  display: grid;
  grid-template-columns: 10px 84px minmax(0, 1fr) auto;
  align-items: baseline;
  gap: 10px;
  padding: 3px 0;
}
.mark {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 1.5px solid var(--rule-strong);
  transform: translateY(-1px);
}
li.done .mark {
  background: var(--blue);
  border-color: var(--blue);
}
li.running .mark {
  border-color: var(--blue);
  animation: pulse 1.1s ease-in-out infinite;
}
li.failed .mark {
  background: var(--fail);
  border-color: var(--fail);
}
.label {
  font-weight: 600;
}
.detail {
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}
.time {
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
li.pending,
li.idle,
li.skipped {
  color: var(--ink-faint);
}
li.pending .label,
li.idle .label,
li.skipped .label {
  font-weight: 400;
}
li.pending .detail,
li.idle .detail,
li.skipped .detail {
  color: var(--ink-faint);
}
li.failed .detail {
  color: var(--fail);
}

@media (max-width: 560px) {
  li {
    grid-template-columns: 10px 70px minmax(0, 1fr);
  }
  .time {
    display: none;
  }
}
</style>
