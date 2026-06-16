// 问答主页面（三栏布局 · 设计参考 claude design/pc-mock.jsx）

import { useEffect, useRef, useState } from 'react'
import { useChatStore, useActiveMessages } from '../stores/chatStore'
import { ChatMessage } from '../components/ChatMessage'
import { Sidebar } from '../components/Sidebar'
import { RightPanel } from '../components/RightPanel'
import { InputBar } from '../components/InputBar'
import { getStats } from '../lib/apiClient'
import type { Citation, CorpusStats, SpecBrief } from '../types/chat'

const SAMPLE_QUERIES = [
  '居住区配套幼儿园的服务半径不应大于多少米？',
  '防火墙的耐火极限要求是多少？',
  '城市道路绿化的种植设计标准？',
  '幼儿园建筑的活动单元应如何布置？',
]

export function ChatPage() {
  const messages = useActiveMessages()
  const conversations = useChatStore((s) => s.conversations)
  const activeId = useChatStore((s) => s.activeId)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const send = useChatStore((s) => s.send)
  const newConversation = useChatStore((s) => s.newConversation)
  const switchConversation = useChatStore((s) => s.switchConversation)
  const deleteConversation = useChatStore((s) => s.deleteConversation)

  const [activeCite, setActiveCite] = useState<number | null>(null)
  const [stats, setStats] = useState<CorpusStats | null>(null)
  // 点侧栏规范 → 多选限定只查这些规范（接通已有 spec_code 检索能力）
  const [specFilters, setSpecFilters] = useState<SpecBrief[]>([])
  const toggleSpec = (sp: SpecBrief) =>
    setSpecFilters((prev) =>
      prev.some((s) => s.spec_code === sp.spec_code)
        ? prev.filter((s) => s.spec_code !== sp.spec_code)
        : [...prev, sp],
    )
  const scrollRef = useRef<HTMLDivElement>(null)

  // 拉规范库语料统计（动态计数）；失败则各组件回退默认值
  useEffect(() => {
    getStats()
      .then(setStats)
      .catch(() => {
        /* 接口未就绪：Sidebar/顶栏用回退默认值，不阻塞 UI */
      })
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages])

  // 新一轮对话开始 / 切换会话时清空 activeCite
  useEffect(() => {
    setActiveCite(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, activeId])

  // ⌘N / Ctrl+N 新建对话（侧栏已标注该快捷键）
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'n' || e.key === 'N')) {
        e.preventDefault()
        newConversation()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [newConversation])

  function handleSubmit(q: string) {
    if (!q.trim() || isStreaming) return
    void send(
      q,
      specFilters.length ? { spec_codes: specFilters.map((s) => s.spec_code) } : undefined,
    )
  }

  // 最新一条 assistant 消息的引用 → 右栏
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const citations: Citation[] = lastAssistant?.citations ?? []
  const lastAssistantId = lastAssistant?.id ?? null

  const userQueryTitle =
    [...messages].reverse().find((m) => m.role === 'user')?.content?.slice(0, 50) ??
    '建景规·助手 — 设计规范智能查询'

  // 规范库覆盖（动态计数，接口未就绪时回退）
  const coverageDomains =
    stats?.domains.map((d) => d.domain).join(' / ') ?? '规划 / 建筑 / 景观 / 消防'
  const domainCount = stats?.domain_count ?? 4
  const totalSpecs = stats?.total_specs ?? 39
  const totalChunks = stats?.total_chunks ?? 4773

  return (
    <div
      className="cn-app"
      style={{
        display: 'flex',
        height: '100%',
        width: '100%',
        overflow: 'hidden',
      }}
    >
      <Sidebar
        onNewChat={newConversation}
        stats={stats}
        conversations={conversations}
        activeId={activeId}
        onSelectConversation={switchConversation}
        onDeleteConversation={deleteConversation}
        onSelectSpec={toggleSpec}
        activeSpecCodes={specFilters.map((s) => s.spec_code)}
      />

      <main
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
          background: 'var(--bg)',
        }}
      >
        {/* 顶栏 */}
        <div className="cn-topbar">
          <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.3, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <span
                className="cn-topbar-title"
                style={{
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  maxWidth: 600,
                }}
              >
                {userQueryTitle}
              </span>
              <span className="cn-topbar-pill">
                <span
                  style={{
                    width: 5,
                    height: 5,
                    borderRadius: 50,
                    background: 'currentColor',
                  }}
                />
                MVP 体验
              </span>
            </div>
            <div className="cn-topbar-sub">
              覆盖{coverageDomains} {domainCount} 类 · {totalSpecs} 部规范 ·{' '}
              {totalChunks} 条条文
              {citations.length > 0 && (
                <>
                  {' · '}
                  <span style={{ fontFamily: 'var(--font-mono)' }}>{citations.length}</span>{' '}
                  条引用
                </>
              )}
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
            {messages.length > 0 && (
              <button
                className="cn-msg-tool"
                style={{ padding: '6px 10px' }}
                onClick={newConversation}
                disabled={isStreaming}
              >
                新建对话
              </button>
            )}
          </div>
        </div>

        {/* 消息列表 */}
        <div
          ref={scrollRef}
          className="cn-scroll"
          style={{
            flex: 1,
            padding: '24px 28px 0',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div style={{ maxWidth: 760, width: '100%', margin: '0 auto', minHeight: '100%' }}>
            {messages.length === 0 ? (
              <EmptyState onPick={handleSubmit} coverage={`${coverageDomains} ${domainCount} 类`} />
            ) : (
              messages.map((m) => (
                <ChatMessage
                  key={m.id}
                  message={m}
                  activeCite={m.id === lastAssistantId ? activeCite : null}
                  onCiteClick={
                    m.id === lastAssistantId ? (n) => setActiveCite(n) : undefined
                  }
                  inlineCitations={m.id === lastAssistantId ? citations : undefined}
                  onFollowUp={m.id === lastAssistantId ? handleSubmit : undefined}
                />
              ))
            )}
          </div>
        </div>

        {/* 输入栏 */}
        <div style={{ maxWidth: 880, width: '100%', margin: '0 auto', alignSelf: 'center' }}>
          <InputBar
            disabled={isStreaming}
            onSubmit={handleSubmit}
            specFilters={specFilters}
            onRemoveFilter={(code) =>
              setSpecFilters((prev) => prev.filter((s) => s.spec_code !== code))
            }
            onClearFilter={() => setSpecFilters([])}
          />
        </div>
      </main>

      <RightPanel
        citations={citations}
        activeIndex={activeCite}
        onActiveChange={setActiveCite}
        meta={lastAssistant?.meta}
      />
    </div>
  )
}

function EmptyState({
  onPick,
  coverage,
}: {
  onPick: (q: string) => void
  coverage: string
}) {
  return (
    <div style={{ textAlign: 'center', padding: '60px 8px' }}>
      <div className="cn-brand-mark-lg" style={{ marginBottom: 18 }} aria-label="品牌标识">
        同
      </div>
      <h2
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 22,
          color: 'var(--ink)',
          margin: '0 0 6px',
          letterSpacing: '0.02em',
        }}
      >
        像查法条一样查规范
      </h2>
      <p
        style={{
          fontSize: 13.5,
          color: 'var(--ink-mute)',
          margin: '0 auto 26px',
          maxWidth: 460,
          lineHeight: 1.7,
        }}
      >
        覆盖{coverage}设计规范<br />
        所有答案附规范号 + 条文号 + 原文引用，可追溯、不编造
      </p>

      <div
        style={{
          maxWidth: 560,
          margin: '0 auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <div
          style={{
            fontSize: 11,
            color: 'var(--ink-faint)',
            textAlign: 'left',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            marginBottom: 2,
          }}
        >
          试试这些示例
        </div>
        {SAMPLE_QUERIES.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            style={{
              textAlign: 'left',
              fontSize: 13.5,
              color: 'var(--ink-soft)',
              background: 'var(--paper)',
              border: '1px solid var(--border)',
              borderRadius: 10,
              padding: '11px 14px',
              cursor: 'pointer',
              transition: 'all .14s',
              fontFamily: 'inherit',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--primary-soft)'
              e.currentTarget.style.borderColor = 'var(--primary-line)'
              e.currentTarget.style.color = 'var(--primary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'var(--paper)'
              e.currentTarget.style.borderColor = 'var(--border)'
              e.currentTarget.style.color = 'var(--ink-soft)'
            }}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
