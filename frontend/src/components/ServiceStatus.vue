<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ health: { type: Object, default: null } })
defineEmits(['refresh'])

const open = ref(false)

const SERVICES = [
  ['milvus', '向量库 Milvus'],
  ['mongodb', '文档库 MongoDB'],
  ['embedding', '向量模型'],
  ['reranker', '重排序模型'],
]

const summary = computed(() => {
  const health = props.health
  if (!health) return { tone: 'wait', text: '正在检查服务' }
  if (health.unreachable) return { tone: 'fail', text: '连不上后端' }
  if (!health.ready) return { tone: 'fail', text: '依赖服务未就绪' }
  if (!health.model_key_configured) return { tone: 'warn', text: '未配置模型密钥' }
  if (!health.services?.reranker?.ok) return { tone: 'warn', text: '重排序不可用' }
  return { tone: 'ok', text: '服务就绪' }
})

const rows = computed(() => {
  const health = props.health
  if (!health || health.unreachable) return []
  return [
    ...SERVICES.map(([key, label]) => ({ label, ok: Boolean(health.services?.[key]?.ok), text: health.services?.[key]?.ok ? '正常' : '不可用' })),
    { label: '对话模型', ok: Boolean(health.model_key_configured), text: health.model_key_configured ? health.model : '未配置密钥' },
    { label: '图片说明', ok: null, text: health.vision_enabled ? '已启用' : '未启用' },
    { label: '联网搜索', ok: null, text: health.web_search_enabled ? '已启用' : '未启用' },
  ]
})
</script>

<template>
  <div class="status" @keydown.esc="open = false">
    <button type="button" class="pill" :class="summary.tone" :aria-expanded="open" @click="open = !open">
      <span class="dot" aria-hidden="true"></span>{{ summary.text }}
    </button>
    <div v-if="open" class="panel" role="dialog" aria-label="服务状态">
      <p v-if="health?.unreachable" class="hint">
        页面没能连上后端服务。请确认后端已经启动，再点下面的按钮重新检查。
      </p>
      <dl v-else>
        <div v-for="row in rows" :key="row.label">
          <dt>{{ row.label }}</dt>
          <dd :class="{ ok: row.ok === true, fail: row.ok === false }">{{ row.text }}</dd>
        </div>
      </dl>
      <p v-if="health && !health.unreachable && !health.services?.reranker?.ok" class="hint">
        重排序模型不可用时仍可问答，资料按融合排序的结果取用。
      </p>
      <button type="button" class="refresh" @click="$emit('refresh')">重新检查</button>
    </div>
  </div>
</template>

<style scoped>
.status {
  position: relative;
}
.pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--rule-strong);
  border-radius: 999px;
  background: var(--sheet);
  font-size: 13px;
  white-space: nowrap;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ink-faint);
}
.pill.ok .dot {
  background: var(--ok);
}
.pill.warn .dot {
  background: var(--callout);
}
.pill.fail .dot {
  background: var(--fail);
}
.pill.fail {
  border-color: var(--fail);
  color: var(--fail);
}

.panel {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  z-index: 30;
  width: 270px;
  padding: 14px 16px;
  background: var(--sheet);
  border: 1px solid var(--rule-strong);
  border-radius: 6px;
  box-shadow: 0 10px 28px rgba(22, 32, 43, 0.14);
}
dl {
  margin: 0;
}
dl div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 5px 0;
  border-bottom: 1px solid var(--rule);
  font-size: 13px;
}
dt {
  color: var(--ink-soft);
}
dd {
  margin: 0;
  text-align: right;
  overflow-wrap: anywhere;
}
dd.ok {
  color: var(--ok);
}
dd.fail {
  color: var(--fail);
  font-weight: 600;
}
.hint {
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--ink-soft);
}
.refresh {
  margin-top: 12px;
  width: 100%;
  height: 32px;
  border: 1px solid var(--blue);
  border-radius: 4px;
  background: none;
  color: var(--blue);
  font-size: 13px;
}
.refresh:hover {
  background: var(--blue-wash);
}
</style>
