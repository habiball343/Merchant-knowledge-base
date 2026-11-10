// 解析 text/event-stream。fetch 的流按任意边界切块，所以需要自己缓冲并按空行切分事件。

export function createSseParser(onEvent) {
  let buffer = ''
  const flush = (block) => {
    const data = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!data) return
    try {
      onEvent(JSON.parse(data))
    } catch {
      // 忽略无法解析的事件，不中断后续事件
    }
  }
  return {
    push(text) {
      buffer += text.replace(/\r\n/g, '\n')
      let boundary
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        flush(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
      }
    },
    end() {
      if (buffer.trim()) flush(buffer)
      buffer = ''
    },
  }
}
