// 全局聊天状态（zustand）
// V2-3：多会话 + localStorage 持久化。
//   - 真源是 conversations[]（每段会话含完整 messages），activeId 指向当前会话。
//   - messages 不再单独存，组件用 useActiveMessages 派生选择器读取当前会话消息。
//   - 持久化只在「回合边界」落盘（done/error/切换/删除/新建），避免逐 token 写 localStorage。

import { create } from 'zustand'
import type { ChatMessage, Conversation } from '../types/chat'
import { streamChat } from '../lib/apiClient'

const STORAGE_KEY = 'jjg-conversations-v1'

/** 持久化形态（只存数据，不存 isStreaming 等运行时态）*/
interface PersistShape {
  conversations: Conversation[]
  activeId: string | null
}

interface ChatState {
  conversations: Conversation[]
  activeId: string | null
  isStreaming: boolean
  /** 用户提问，触发 SSE 流（无 activeId 时惰性新建会话）*/
  send: (query: string, opts?: { domain?: string; spec_codes?: string[] }) => Promise<void>
  /** 新建对话：回到空态，首次发送时才真正建会话（避免空会话堆积）*/
  newConversation: () => void
  /** 切换到指定历史会话 */
  switchConversation: (id: string) => void
  /** 删除指定会话 */
  deleteConversation: (id: string) => void
}

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

/** 标题取首条用户问题前 24 字 */
function titleFromQuery(q: string): string {
  const t = q.trim().replace(/\s+/g, ' ')
  return t.length > 24 ? t.slice(0, 24) + '…' : t
}

/** 刷新卫生：清掉上次未完成的流式残留（streaming 态、空 assistant 气泡）*/
function sanitizeConversation(c: Conversation): Conversation {
  const messages = (c.messages ?? [])
    .filter((m) => !(m.role === 'assistant' && !m.content && !m.error))
    .map((m) => ({ ...m, streaming: false }))
  return { ...c, messages }
}

/** 从 localStorage 载入（失败/不可用 → 空态，不阻塞 UI）*/
function loadPersisted(): PersistShape {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { conversations: [], activeId: null }
    const parsed = JSON.parse(raw) as Partial<PersistShape>
    const conversations = (parsed.conversations ?? []).map(sanitizeConversation)
    const activeId = parsed.activeId ?? null
    // activeId 必须指向仍存在的会话，否则置空
    return {
      conversations,
      activeId: conversations.some((c) => c.id === activeId) ? activeId : null,
    }
  } catch {
    return { conversations: [], activeId: null }
  }
}

/** 落盘（隐私模式/配额异常时静默失败，仅退化为内存态）*/
function savePersisted(state: PersistShape): void {
  try {
    const payload: PersistShape = {
      conversations: state.conversations,
      activeId: state.activeId,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  } catch {
    /* localStorage 不可用：仅内存态，不影响主流程 */
  }
}

const initial = loadPersisted()

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: initial.conversations,
  activeId: initial.activeId,
  isStreaming: false,

  newConversation: () => {
    if (get().isStreaming) return
    set({ activeId: null })
    savePersisted(get())
  },

  switchConversation: (id) => {
    if (get().isStreaming) return
    if (!get().conversations.some((c) => c.id === id)) return
    set({ activeId: id })
    savePersisted(get())
  },

  deleteConversation: (id) => {
    if (get().isStreaming) return // 流式中不允许删（避免删到正在写的会话）
    const conversations = get().conversations.filter((c) => c.id !== id)
    const activeId = get().activeId === id ? null : get().activeId
    set({ conversations, activeId })
    savePersisted({ conversations, activeId })
  },

  async send(query, opts) {
    const trimmed = query.trim()
    if (!trimmed) return
    if (get().isStreaming) return

    const active = get().activeId
    const existing = active ? get().conversations.find((c) => c.id === active) : undefined

    // V2-2：当前会话最近 N 轮已完成消息 → 供后端指代消解
    const history = (existing?.messages ?? [])
      .filter(
        (m) =>
          (m.role === 'user' || m.role === 'assistant') &&
          !!m.content &&
          !m.streaming &&
          !m.error,
      )
      .slice(-6)
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))

    const userMsg: ChatMessage = { id: newId(), role: 'user', content: trimmed }
    const assistantMsg: ChatMessage = {
      id: newId(),
      role: 'assistant',
      content: '',
      streaming: true,
    }

    // 定位/惰性新建当前会话
    const convId = existing?.id ?? newId()
    if (existing) {
      set({
        conversations: get().conversations.map((c) =>
          c.id === convId
            ? { ...c, messages: [...c.messages, userMsg, assistantMsg], updatedAt: Date.now() }
            : c,
        ),
        isStreaming: true,
      })
    } else {
      const conv: Conversation = {
        id: convId,
        title: titleFromQuery(trimmed),
        messages: [userMsg, assistantMsg],
        createdAt: Date.now(),
        updatedAt: Date.now(),
      }
      // 新会话置顶
      set({ conversations: [conv, ...get().conversations], activeId: convId, isStreaming: true })
    }

    /** 更新当前会话内正在流式的 assistant 消息 */
    const patch = (fn: (m: ChatMessage) => ChatMessage) => {
      set((s) => ({
        conversations: s.conversations.map((c) =>
          c.id === convId
            ? {
                ...c,
                messages: c.messages.map((m) => (m.id === assistantMsg.id ? fn(m) : m)),
                updatedAt: Date.now(),
              }
            : c,
        ),
      }))
    }

    try {
      for await (const evt of streamChat({
        query: trimmed,
        history: history.length ? history : undefined,
        ...opts,
      })) {
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
          case 'follow_ups':
            // V2-1：智能追问推荐
            patch((m) => ({ ...m, followUps: evt.data }))
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
      savePersisted(get()) // 仅回合边界落盘
    }
  },
}))

/** 稳定空数组引用：无 activeId 时返回它，避免触发组件无谓重渲染 */
const EMPTY_MESSAGES: ChatMessage[] = []

/** 派生选择器：当前激活会话的消息列表（组件用它替代旧 s.messages）*/
export function useActiveMessages(): ChatMessage[] {
  return useChatStore((s) => {
    const c = s.conversations.find((x) => x.id === s.activeId)
    return c ? c.messages : EMPTY_MESSAGES
  })
}
