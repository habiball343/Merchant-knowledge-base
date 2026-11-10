import { createSseParser } from './sse.js'

async function json(response) {
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : body.detail?.message || ''
    } catch {
      // 响应体不是 JSON
    }
    const error = new Error(detail || `服务没有正常响应（HTTP ${response.status}）`)
    error.status = response.status
    throw error
  }
  return response.json()
}

// 提问。每收到一条 SSE 事件调用一次 onEvent；流正常结束后 resolve。
export async function askQuestion(query, sessionId, onEvent, signal) {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, session_id: sessionId || null }),
    signal,
  })
  if (response.status === 422) throw new Error('问题不能为空，且不能超过 2000 个字。')
  if (!response.ok || !response.body) throw new Error(`服务没有正常响应（HTTP ${response.status}）。请确认后端已启动。`)

  const parser = createSseParser(onEvent)
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    parser.push(decoder.decode(value, { stream: true }))
  }
  parser.push(decoder.decode())
  parser.end()
}

// 健康检查。未就绪时后端返回 503，但响应体同样是各项依赖的明细。
export async function fetchHealth() {
  return (await fetch('/api/health')).json()
}

export const fetchDocuments = async () => (await json(await fetch('/api/documents'))).items
export const fetchProducts = async () => (await json(await fetch('/api/products'))).items
export const deleteDocument = async (docId) => json(await fetch(`/api/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' }))
export const fetchHistory = async (sessionId) => json(await fetch(`/api/chat/history/${encodeURIComponent(sessionId)}`))
export const clearHistory = async (sessionId) => json(await fetch(`/api/chat/history/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }))

export async function uploadDocuments(files, product) {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  form.append('product', product || '')
  const response = await fetch('/api/documents', { method: 'POST', body: form })
  if (response.status === 400) {
    const body = await response.json()
    return { accepted: [], rejected: body.detail?.rejected || [] }
  }
  return json(response)
}
