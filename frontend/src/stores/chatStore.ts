// 全局聊天状态（zustand）

import { create } from 'zustand'
import type { ChatMessage } from '../types/chat'
import { streamChat } from '../lib/apiClient'

interface ChatState {
  messages: ChatMessage[]
  isStreaming: boolean
  /** 用户提问，触发 SSE 流 */
  send: (query: string, opts?: { domain?: string; spec_code?: string }) => Promise<void>
  /** 清空对话 */
  clear: () => void
}

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,

  clear: () => set({ messages: [] }),

  async send(query, opts) {
    const trimmed = query.trim()
    if (!trimmed) return
    if (get().isStreaming) return

    const userMsg: ChatMessage = {
      id: newId(),
      role: 'user',
      content: trimmed,
    }
    const assistantMsg: ChatMessage = {
      id: newId(),
      role: 'assistant',
      content: '',
      streaming: true,
    }
    set({
      messages: [...get().messages, userMsg, assistantMsg],
      isStreaming: true,
    })

    /** 用闭包持续指向当前流式消息 */
    const patch = (fn: (m: ChatMessage) => ChatMessage) => {
      set((s) => ({
        messages: s.messages.map((m) => (m.id === assistantMsg.id ? fn(m) : m)),
      }))
    }

    try {
      for await (const evt of streamChat({ query: trimmed, ...opts })) {
        // W6 D4 临时调试：把事件流打到 console（验证 SSE 接收）
        // eslint-disable-next-line no-console
        console.log('[SSE]', evt.type, typeof evt.data === 'string' ? evt.data : evt.data)
        switch (evt.type) {
          case 'retrieval':
            patch((m) => ({ ...m, retrieval: evt.data }))
            break
          case 'token':
            patch((m) => ({ ...m, content: m.content + evt.data }))
            break
          case 'citations':
            patch((m) => ({ ...m, citations: evt.data }))
            break
          case 'metadata':
            // W6 D2：保存 dangling / post_filter 状态供 UI / debug
            patch((m) => ({ ...m, meta: evt.data }))
            break
          case 'revised_answer':
            // W6 D2：post_filter 剥离了"补充说明"节，用净化版覆盖 content
            // 原 content（streaming 中拼出的 LLM 原始回答）存到 rawContent，便于 debug
            patch((m) => ({ ...m, rawContent: m.content, content: evt.data }))
            break
          case 'fallback':
            patch((m) => ({ ...m, fallback: evt.data }))
            break
          case 'done':
            patch((m) => ({ ...m, done: evt.data, streaming: false }))
            break
          case 'error':
            patch((m) => ({ ...m, error: evt.data, streaming: false }))
            break
        }
      }
    } catch (e) {
      patch((m) => ({
        ...m,
        error: e instanceof Error ? e.message : String(e),
        streaming: false,
      }))
    } finally {
      set({ isStreaming: false })
      patch((m) => ({ ...m, streaming: false }))
    }
  },
}))
