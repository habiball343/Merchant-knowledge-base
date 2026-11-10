// 回答里的引用标注：把 [1]、[2][3] 这样的编号变成可以点的标注。

const CITATION = /\[(\d{1,2})\](?!\()/g

// 在交给 Markdown 渲染之前，把引用编号替换成带 data-cite 的标记。
// 代码块和行内代码里的方括号保持原样；后面紧跟圆括号的是 Markdown 链接，也不动。
export function markCitations(markdown, validIndexes = null) {
  const segments = String(markdown ?? '').split(/(```[\s\S]*?```|`[^`\n]*`)/g)
  return segments
    .map((segment, position) => {
      if (position % 2 === 1) return segment
      return segment.replace(CITATION, (whole, digits) => {
        const index = Number(digits)
        if (validIndexes && !validIndexes.has(index)) return whole
        return `<sup class="cite" data-cite="${index}">${index}</sup>`
      })
    })
    .join('')
}

// 回答中实际引用到的资料编号（去重、按出现顺序）。
export function citedIndexes(markdown) {
  const found = []
  for (const match of String(markdown ?? '').matchAll(CITATION)) {
    const index = Number(match[1])
    if (!found.includes(index)) found.push(index)
  }
  return found
}
