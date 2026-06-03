// 后端 API 客户端：封装 fetch + SSE 解析
//
// SSE 帧格式（sse-starlette）：
//   event: token
//   data: "你"
//   <空行>
//
// 多帧之间用 \n\n 分隔；每帧 event/data 字段用 \n 分隔。

import type { ChatRequest, SSEEvent } from '../types/chat'

const API_BASE = '' // 走 Vite proxy，前端只用相对路径

/** 解析单个 SSE 帧（多行）为 SSEEvent */
function parseFrame(frame: string): SSEEvent | null {
  let eventType = 'message'
  let dataLine = ''
  // sse-starlette 行尾用 CRLF；用 /\r?\n/ 兼容 LF/CRLF
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      // 多行 data 合并
      dataLine += (dataLine ? '\n' : '') + line.slice(5).trim()
    }
  }
  if (!dataLine) return null
  let data: unknown
  try {
    data = JSON.parse(dataLine)
  } catch {
    data = dataLine
  }
  return { type: eventType as SSEEvent['type'], data } as SSEEvent
}

/**
 * 向 /api/chat 发送 query，返回 SSE 事件异步迭代器。
 * 用法：
 *   for await (const evt of streamChat({ query: '...' })) { ... }
 */
export async function* streamChat(
  req: ChatRequest,
  signal?: AbortSignal,
): AsyncIterableIterator<SSEEvent> {
  const resp = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(req),
    signal,
  })
  if (!resp.ok) {
    const errText = await resp.text().catch(() => '')
    throw new Error(`HTTP ${resp.status}: ${errText || resp.statusText}`)
  }
  if (!resp.body) {
    throw new Error('响应没有 body 流')
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE 用空行分隔帧；sse-starlette 实际发 CRLF (\r\n\r\n)，
      // 需要同时兼容 LF (\n\n)。否则 indexOf('\n\n') 永远找不到，
      // 整个流的 token 帧都会被丢弃（W6 D5 修）。
      while (true) {
        const crlfIdx = buffer.indexOf('\r\n\r\n')
        const lfIdx = buffer.indexOf('\n\n')
        let sepIdx: number
        let sepLen: number
        if (crlfIdx >= 0 && (lfIdx < 0 || crlfIdx <= lfIdx)) {
          sepIdx = crlfIdx
          sepLen = 4
        } else if (lfIdx >= 0) {
          sepIdx = lfIdx
          sepLen = 2
        } else {
          break
        }
        const frame = buffer.slice(0, sepIdx)
        buffer = buffer.slice(sepIdx + sepLen)
        const evt = parseFrame(frame)
        if (evt) yield evt
      }
    }
    // 末尾残留
    if (buffer.trim()) {
      const evt = parseFrame(buffer)
      if (evt) yield evt
    }
  } finally {
    reader.releaseLock()
  }
}

/** 健康检查 */
export async function healthCheck(): Promise<{ status: string; version: string }> {
  const resp = await fetch(`${API_BASE}/api/health`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}
