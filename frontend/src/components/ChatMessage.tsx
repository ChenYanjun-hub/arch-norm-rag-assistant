// 单条聊天消息（cn-msg-user / cn-msg-card 设计语言）
// 设计参考：claude design/pc-mock.jsx · UserMsg + AIMsg

import type { ChatMessage as ChatMessageType } from '../types/chat'

interface Props {
  message: ChatMessageType
}

/** 把 token 文本里的 [N] 转换成 cn-cite chip */
function renderWithCitations(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  const re = /\[(\d+)\]/g
  let m: RegExpExecArray | null
  let key = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > lastIndex) {
      parts.push(text.slice(lastIndex, m.index))
    }
    parts.push(
      <span className="cn-cite" key={`cite-${key++}-${m.index}`}>
        <span>[{m[1]}]</span>
      </span>,
    )
    lastIndex = m.index + m[0].length
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

export function ChatMessage({ message }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 18 }}>
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
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 18 }}>
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
              {renderWithCitations(message.content)}
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
      </div>
    </div>
  )
}
