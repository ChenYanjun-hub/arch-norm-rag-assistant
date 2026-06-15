// 单条聊天消息（cn-msg-user / cn-msg-card 设计语言）
// 设计参考：claude design/pc-mock.jsx · UserMsg + AIMsg

import type { ChatMessage as ChatMessageType, Citation } from '../types/chat'
import { CitationCard } from './CitationCard'

interface Props {
  message: ChatMessageType
  /** 当前激活的引用编号（与右栏 CiteCard 联动）*/
  activeCite?: number | null
  /** 点击正文 [N] chip 时回调 */
  onCiteClick?: (n: number) => void
  /** 窄屏内联引用（<1024px 右栏隐藏时在消息内展示，保证溯源可见）*/
  inlineCitations?: Citation[]
  /** V2-1：点击追问 chip → 作为新 query 发送 */
  onFollowUp?: (q: string) => void
}

/** 把 token 文本里的 [N] 转换成 cn-cite chip */
function renderWithCitations(
  text: string,
  activeCite?: number | null,
  onCiteClick?: (n: number) => void,
): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  const re = /\[(\d+)\]/g
  let m: RegExpExecArray | null
  let key = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > lastIndex) {
      parts.push(text.slice(lastIndex, m.index))
    }
    const n = parseInt(m[1], 10)
    const isActive = activeCite === n
    parts.push(
      <span
        className={'cn-cite' + (isActive ? ' is-active' : '')}
        key={`cite-${key++}-${m.index}`}
        onClick={(e) => {
          e.stopPropagation()
          onCiteClick?.(n)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            e.stopPropagation()
            onCiteClick?.(n)
          }
        }}
        role="button"
        tabIndex={0}
        aria-label={`查看第 ${n} 条规范引用`}
      >
        <span>[{n}]</span>
      </span>,
    )
    lastIndex = m.index + m[0].length
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

export function ChatMessage({
  message,
  activeCite,
  onCiteClick,
  inlineCitations,
  onFollowUp,
}: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="cn-msg-row" style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 18 }}>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 4,
            maxWidth: '82%',
          }}
        >
          <div style={{ fontSize: 11, color: 'var(--ink-faint)' }}>你</div>
          <div className="cn-msg-user">{message.content}</div>
        </div>
      </div>
    )
  }

  // assistant
  return (
    <div className="cn-msg-row" style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 18 }}>
      <div
        style={{
          width: 32,
          height: 32,
          flex: '0 0 auto',
          borderRadius: '50%',
          background: 'var(--primary)',
          color: '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'var(--font-serif)',
          fontSize: 14,
          fontWeight: 600,
        }}
      >
        规
      </div>

      <div className="cn-msg-ai">
        <div
          style={{
            fontSize: 11,
            color: 'var(--ink-faint)',
            marginBottom: 4,
            display: 'flex',
            gap: 6,
            alignItems: 'center',
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontWeight: 600, color: 'var(--primary)' }}>规·助手</span>
          {message.retrieval && (
            <>
              <span>·</span>
              <span>
                已检索{' '}
                <span style={{ fontFamily: 'var(--font-mono)' }}>
                  {message.retrieval.n_kept}/{message.retrieval.n_candidates}
                </span>{' '}
                条相关条文
              </span>
            </>
          )}
          {message.fallback && (
            <span style={{ color: 'var(--amber)' }}>● 兜底场景 · {message.fallback}</span>
          )}
          {!message.fallback && message.done && (
            <span style={{ color: 'var(--status-active)' }}>● 现行有效</span>
          )}
        </div>

        <div className="cn-msg-card">
          {message.error ? (
            <div style={{ color: 'var(--terracotta)', fontSize: 13 }}>
              ❌ 出错：{message.error}
            </div>
          ) : (
            <div style={{ whiteSpace: 'pre-wrap' }}>
              {renderWithCitations(message.content, activeCite, onCiteClick)}
              {message.streaming && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 6,
                    height: 14,
                    background: 'var(--ink-mute)',
                    marginLeft: 2,
                    verticalAlign: 'middle',
                    animation: 'cn-blink 1s steps(2, end) infinite',
                  }}
                />
              )}
            </div>
          )}

          {message.done && !message.streaming && (
            <div
              className="cn-msg-tools"
              style={{ fontSize: 11, color: 'var(--ink-faint)', fontFamily: 'var(--font-mono)' }}
            >
              TTFT {message.done.ttft_ms}ms · 总 {message.done.total_ms}ms ·{' '}
              {message.done.tokens_out} tokens
            </div>
          )}
        </div>

        {/* 窄屏（<1024px 右栏隐藏）内联引用 — 保证「可溯源」核心价值不丢 */}
        {inlineCitations && inlineCitations.length > 0 && (
          <details className="cn-cites-inline">
            <summary>规范出处 · {inlineCitations.length} 条引用</summary>
            <div className="cn-cites-inline-list">
              {inlineCitations.map((c, i) => (
                <CitationCard key={i} index={i + 1} citation={c} />
              ))}
            </div>
          </details>
        )}

        {/* V2-1：智能追问 chip（点击作为新 query 发送）*/}
        {message.followUps && message.followUps.length > 0 && onFollowUp && (
          <div className="cn-followup-row">
            {message.followUps.map((q, i) => (
              <button
                key={i}
                className="cn-followup"
                onClick={() => onFollowUp(q)}
                aria-label={`追问：${q}`}
              >
                {q}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
