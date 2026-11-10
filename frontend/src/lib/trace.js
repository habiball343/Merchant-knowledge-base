// 问答流程的阶段定义与状态归并。后端推送 {type:'stage', node, label, status, detail, elapsed_ms}。

export const RETRIEVERS = ['vector_search', 'hyde_search', 'web_search']

export const STAGES = [
  { node: 'confirm_product', label: '确认商品' },
  { node: 'vector_search', label: '混合检索', group: '三路检索' },
  { node: 'hyde_search', label: 'HyDE 检索', group: '三路检索' },
  { node: 'web_search', label: '联网搜索', group: '三路检索' },
  { node: 'fuse', label: '融合排序' },
  { node: 'rerank', label: '重排序' },
  { node: 'generate_answer', label: '生成回答' },
]

export const ROUTE_LABELS = { vector: '混合检索', hyde: 'HyDE', web: '联网' }

export function createTrace() {
  return STAGES.map((stage) => ({ ...stage, status: 'pending', detail: '', elapsedMs: null }))
}

// 把一条阶段事件应用到 trace 上（原地修改，便于配合 Vue 的响应式对象）
export function applyStage(trace, event) {
  const step = trace.find((item) => item.node === event.node)
  if (!step) return trace
  step.status = event.status
  if (event.detail) step.detail = event.detail
  if (event.elapsed_ms !== undefined) step.elapsedMs = event.elapsed_ms
  return trace
}

// 流程结束时收尾：没走到的步骤标记为未执行（例如需要澄清商品时不会检索）
export function finishTrace(trace, { failed }) {
  for (const step of trace) {
    if (step.status === 'running') step.status = failed ? 'failed' : 'done'
    else if (step.status === 'pending') step.status = 'idle'
  }
  return trace
}

export function formatDuration(ms) {
  if (ms === null || ms === undefined) return ''
  if (ms < 1) return '不到 1 毫秒'
  if (ms < 1000) return `${ms} 毫秒`
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} 秒`
}
