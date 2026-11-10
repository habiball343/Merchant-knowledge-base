import { test } from 'node:test'
import assert from 'node:assert/strict'
import { citedIndexes, markCitations } from '../src/lib/citations.js'
import { createSseParser } from '../src/lib/sse.js'
import { applyStage, createTrace, finishTrace, formatDuration } from '../src/lib/trace.js'

test('citation numbers become callout markers', () => {
  assert.equal(
    markCitations('先断电 [1]，再拧开后盖[2][3]。'),
    '先断电 <sup class="cite" data-cite="1">1</sup>，再拧开后盖<sup class="cite" data-cite="2">2</sup><sup class="cite" data-cite="3">3</sup>。',
  )
})

test('markdown links, code and unknown numbers are left alone', () => {
  assert.equal(markCitations('见 [1](https://example.com) 和 `arr[2]`'), '见 [1](https://example.com) 和 `arr[2]`')
  assert.equal(markCitations('```\nrow[1]\n```\n正文 [1]'), '```\nrow[1]\n```\n正文 <sup class="cite" data-cite="1">1</sup>')
  assert.equal(markCitations('共 [9] 项 [1]', new Set([1])), '共 [9] 项 <sup class="cite" data-cite="1">1</sup>')
  assert.equal(markCitations('数组 [123] 不是引用'), '数组 [123] 不是引用')
  assert.equal(markCitations(null), '')
})

test('cited indexes are unique and ordered by first appearance', () => {
  assert.deepEqual(citedIndexes('甲 [2]，乙 [1][2]，丙 [3]'), [2, 1, 3])
  assert.deepEqual(citedIndexes('没有引用'), [])
})

test('sse parser reassembles events split across arbitrary chunk boundaries', () => {
  const text = 'data: {"type":"delta","text":"拧开"}\n\ndata: {"type":"final","answer":"拧开后盖"}\n\n'
  for (let size = 1; size <= 9; size += 1) {
    const events = []
    const parser = createSseParser((event) => events.push(event))
    for (const chunk of text.match(new RegExp(`[\\s\\S]{1,${size}}`, 'g'))) parser.push(chunk)
    parser.end()
    assert.deepEqual(events, [{ type: 'delta', text: '拧开' }, { type: 'final', answer: '拧开后盖' }])
  }
})

test('sse parser tolerates CRLF, comments, malformed events and a missing final blank line', () => {
  const events = []
  const parser = createSseParser((event) => events.push(event))
  parser.push(': ping\r\n\r\ndata: {broken\r\n\r\ndata: {"a":1}\r\n\r\ndata: {"b":2}')
  parser.end()
  assert.deepEqual(events, [{ a: 1 }, { b: 2 }])
})

test('stage events update status, detail and duration', () => {
  const trace = createTrace()
  applyStage(trace, { node: 'rerank', status: 'running' })
  assert.equal(trace.find((step) => step.node === 'rerank').status, 'running')
  applyStage(trace, { node: 'rerank', status: 'done', detail: '12 条候选，保留 4 条', elapsed_ms: 412 })
  const rerank = trace.find((step) => step.node === 'rerank')
  assert.deepEqual([rerank.status, rerank.detail, rerank.elapsedMs], ['done', '12 条候选，保留 4 条', 412])
  applyStage(trace, { node: 'web_search', status: 'skipped', detail: '未启用' })
  assert.equal(trace.find((step) => step.node === 'web_search').detail, '未启用')
  assert.doesNotThrow(() => applyStage(trace, { node: 'respond_directly', status: 'done' }))
})

test('finishing a trace settles running and untouched steps', () => {
  const trace = createTrace()
  applyStage(trace, { node: 'confirm_product', status: 'done' })
  applyStage(trace, { node: 'generate_answer', status: 'running' })
  finishTrace(trace, { failed: true })
  assert.equal(trace.find((step) => step.node === 'generate_answer').status, 'failed')
  assert.equal(trace.find((step) => step.node === 'fuse').status, 'idle')
  assert.equal(trace.find((step) => step.node === 'confirm_product').status, 'done')
})

test('durations switch from milliseconds to seconds', () => {
  assert.equal(formatDuration(412), '412 毫秒')
  assert.equal(formatDuration(3770), '3.8 秒')
  assert.equal(formatDuration(0), '不到 1 毫秒')
  assert.equal(formatDuration(undefined), '')
})
