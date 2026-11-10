import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { markCitations } from './citations.js'

marked.setOptions({ gfm: true, breaks: true })

// 回答和资料正文都来自模型或上传的文档，渲染前一律做净化，只保留排版用的标签。
const ALLOWED = {
  ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'del', 'code', 'pre', 'blockquote', 'ul', 'ol', 'li', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a', 'img', 'sup', 'hr'],
  ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class', 'data-cite', 'target', 'rel'],
}

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
  // 引用标注要能用键盘操作
  if (node.tagName === 'SUP' && node.hasAttribute('data-cite')) {
    node.setAttribute('tabindex', '0')
    node.setAttribute('role', 'button')
    node.setAttribute('aria-label', `查看第 ${node.getAttribute('data-cite')} 条出处`)
  }
  if (node.tagName === 'IMG') node.setAttribute('loading', 'lazy')
})

export function renderAnswer(markdown, sources = []) {
  const valid = new Set(sources.map((source) => source.index))
  return DOMPurify.sanitize(marked.parse(markCitations(markdown, valid.size ? valid : null)), ALLOWED)
}

export function renderMarkdown(markdown) {
  return DOMPurify.sanitize(marked.parse(String(markdown ?? '')), ALLOWED)
}
