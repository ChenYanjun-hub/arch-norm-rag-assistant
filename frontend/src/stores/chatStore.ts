// 全局聊天状态（zustand）
// V2-3：多会话 + localStorage 持久化。
//   - 真源是 conversations[]（每段会话含完整 messages），activeId 指向当前会话。
//   - messages 不再单独存，组件用 useActiveMessages 派生选择器读取当前会话消息。
//   - 持久化只在「回合边界」落盘（done/error/切换/删除/新建），避免逐 token 写 localStorage。

import { create } from 'zustand'
import type { ChatMessage, Conversation, Project } from '../types/chat'
import { streamChat } from '../lib/apiClient'

const STORAGE_KEY = 'jjg-conversations-v1'

/** 持久化形态（只存数据，不存 isStreaming 等运行时态）*/
interface PersistShape {
  conversations: Conversation[]
  activeId: string | null
  /** W7：项目工作区 */
  projects: Project[]
  activeProjectId: string | null
}

interface ChatState {
  conversations: Conversation[]
  activeId: string | null
  isStreaming: boolean
  /** W7：项目列表（localStorage 持久化，MVP 不做账号故不入后端）*/
  projects: Project[]
  /** 当前选中的项目：过滤历史列表 + 新会话继承 + 提供预设规范限定 */
  activeProjectId: string | null
  /** 用户提问，触发 SSE 流（无 activeId 时惰性新建会话）*/
  send: (query: string, opts?: { domain?: string; spec_codes?: string[] }) => Promise<void>
  /** 新建对话：回到空态，首次发送时才真正建会话（避免空会话堆积）*/
  newConversation: () => void
  /** 切换到指定历史会话 */
  switchConversation: (id: string) => void
  /** 删除指定会话 */
  deleteConversation: (id: string) => void
  /** W7：新建项目 */
  createProject: (name: string, city?: string) => void
  /** W7：选中/取消选中项目（传 null 取消）*/
  selectProject: (id: string | null) => void
  /** W7：删除项目（其下会话不删，仅解除归属，避免误删用户历史）*/
  deleteProject: (id: string) => void
  /** W7：设置项目的预设规范限定 */
  setProjectSpecs: (id: string, specCodes: string[]) => void
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
    if (!raw) return { conversations: [], activeId: null, projects: [], activeProjectId: null }
    const parsed = JSON.parse(raw) as Partial<PersistShape>
    const conversations = (parsed.conversations ?? []).map(sanitizeConversation)
    const activeId = parsed.activeId ?? null
    // W7：老版本 localStorage 没有 projects 字段 → 缺省空数组（向后兼容，不清历史）
    const projects = parsed.projects ?? []
    const activeProjectId = parsed.activeProjectId ?? null
    // activeId / activeProjectId 必须指向仍存在的对象，否则置空
    return {
      conversations,
      activeId: conversations.some((c) => c.id === activeId) ? activeId : null,
      projects,
      activeProjectId: projects.some((p) => p.id === activeProjectId) ? activeProjectId : null,
    }
  } catch {
    return { conversations: [], activeId: null, projects: [], activeProjectId: null }
  }
}

/** 落盘（隐私模式/配额异常时静默失败，仅退化为内存态）*/
function savePersisted(state: PersistShape): void {
  try {
    const payload: PersistShape = {
      conversations: state.conversations,
      activeId: state.activeId,
      projects: state.projects,
      activeProjectId: state.activeProjectId,
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
  projects: initial.projects,
  activeProjectId: initial.activeProjectId,

  createProject: (name, city) => {
    const n = name.trim()
    if (!n) return
    const project: Project = {
      id: newId(),
      name: n,
      city: city?.trim() || undefined,
      specCodes: [],
      createdAt: Date.now(),
    }
    const projects = [project, ...get().projects]
    // 新建后自动选中 + 退出当前会话：否则会"在新项目里提问却续到了项目外的旧会话上"
    // （实测发现的 bug：只切 activeProjectId 不清 activeId，新问答不会归入该项目）
    set({ projects, activeProjectId: project.id, activeId: null })
    savePersisted(get())
  },

  selectProject: (id) => {
    if (get().isStreaming) return
    if (id !== null && !get().projects.some((p) => p.id === id)) return
    // 切项目时退出当前会话，回到该项目的空态（避免"选了项目却还停在别的项目会话里"）
    set({ activeProjectId: id, activeId: null })
    savePersisted(get())
  },

  deleteProject: (id) => {
    if (get().isStreaming) return
    const projects = get().projects.filter((p) => p.id !== id)
    // 只解除归属，不删会话——用户的问答历史比项目分组更宝贵
    const conversations = get().conversations.map((c) =>
      c.projectId === id ? { ...c, projectId: null } : c,
    )
    const activeProjectId = get().activeProjectId === id ? null : get().activeProjectId
    set({ projects, conversations, activeProjectId })
    savePersisted(get())
  },

  setProjectSpecs: (id, specCodes) => {
    const projects = get().projects.map((p) =>
      p.id === id ? { ...p, specCodes: [...specCodes] } : p,
    )
    set({ projects })
    savePersisted(get())
  },

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
    // 必须落盘完整 state：早期这里传的是 {conversations, activeId} 局部对象，
    // 加入 projects 后会把项目整个抹掉（TS 类型检查抓到）
    savePersisted(get())
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
        // W7：新会话归属当前选中项目
        projectId: get().activeProjectId,
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

    // W7：项目预设规范限定。
    // 规则：**手动选了规范就用手动的，没手动选才用项目预设**——
    // 避免用户在侧栏取消了限定却因项目预设而"取消不掉"，控制权始终在用户手上。
    const proj = get().projects.find(
      (p) => p.id === (existing?.projectId ?? get().activeProjectId),
    )
    const effectiveOpts =
      opts?.spec_codes?.length || !proj?.specCodes.length
        ? opts
        : { ...opts, spec_codes: proj.specCodes }

    try {
      for await (const evt of streamChat({
        query: trimmed,
        history: history.length ? history : undefined,
        ...effectiveOpts,
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
