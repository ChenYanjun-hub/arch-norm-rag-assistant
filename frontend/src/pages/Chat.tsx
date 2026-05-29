// 问答主页面（三栏布局 · 设计参考 claude design/pc-mock.jsx）

import { useEffect, useRef, useState } from 'react'
import { useChatStore } from '../stores/chatStore'
import { ChatMessage } from '../components/ChatMessage'
import { Sidebar } from '../components/Sidebar'
import { RightPanel } from '../components/RightPanel'
import { InputBar } from '../components/InputBar'
import type { Citation } from '../types/chat'

const SAMPLE_QUERIES = [
  '居住区配套幼儿园的服务半径不应大于多少米？',
  '防火墙的耐火极限要求是多少？',
  '城市道路绿化的种植设计标准？',
  '幼儿园建筑的活动单元应如何布置？',
]

export function ChatPage() {
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const send = useChatStore((s) => s.send)
  const clear = useChatStore((s) => s.clear)

  const [activeCite, setActiveCite] = useState<number | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages])

  function handleSubmit(q: string) {
    if (!q.trim() || isStreaming) return
    void send(q)
  }

  // 最新一条 assistant 消息的引用 → 右栏
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const citations: Citation[] = lastAssistant?.citations ?? []

  const userQueryTitle =
    [...messages].reverse().find((m) => m.role === 'user')?.content?.slice(0, 50) ??
    '建景规·助手 — 设计规范智能查询'

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
      <Sidebar onNewChat={clear} />

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
              覆盖规划 / 建筑 / 景观 / 消防 4 类 · 39 部规范 · 4773 条条文
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
                onClick={clear}
                disabled={isStreaming}
              >
                清空对话
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
              <EmptyState onPick={handleSubmit} />
            ) : (
              messages.map((m) => <ChatMessage key={m.id} message={m} />)
            )}
          </div>
        </div>

        {/* 输入栏 */}
        <div style={{ maxWidth: 880, width: '100%', margin: '0 auto', alignSelf: 'center' }}>
          <InputBar disabled={isStreaming} onSubmit={handleSubmit} />
        </div>
      </main>

      <RightPanel
        citations={citations}
        activeIndex={activeCite}
        onActiveChange={setActiveCite}
      />
    </div>
  )
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
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
        覆盖规划 / 建筑 / 景观 / 消防 4 类设计规范<br />
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
