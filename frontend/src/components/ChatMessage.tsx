// 单条聊天消息（user 或 assistant）

import type { ChatMessage as ChatMessageType } from '../types/chat'
import { CitationCard } from './CitationCard'

interface Props {
  message: ChatMessageType
}

export function ChatMessage({ message }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-tr-sm">
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
      </div>
    )
  }

  // assistant
  return (
    <div className="flex flex-col gap-3">
      <div className="max-w-full bg-white border border-gray-200 px-4 py-3 rounded-2xl rounded-tl-sm">
        {message.fallback && (
          <div className="mb-2 inline-block px-2 py-0.5 text-[10px] font-medium rounded bg-amber-50 text-amber-700 border border-amber-200">
            兜底场景：{message.fallback}
          </div>
        )}
        {message.error ? (
          <div className="text-red-600 text-sm">
            ❌ 出错：{message.error}
          </div>
        ) : (
          <div className="prose-sm text-gray-800 whitespace-pre-wrap break-words leading-relaxed">
            {message.content}
            {message.streaming && (
              <span className="inline-block w-1.5 h-4 bg-gray-400 align-middle ml-0.5 animate-pulse" />
            )}
          </div>
        )}
        {message.done && !message.streaming && (
          <div className="mt-2 pt-2 border-t border-gray-100 text-[11px] text-gray-400 font-mono">
            TTFT {message.done.ttft_ms}ms · 总 {message.done.total_ms}ms ·{' '}
            {message.done.tokens_out} tokens
            {message.retrieval &&
              ` · 检索 ${message.retrieval.n_kept}/${message.retrieval.n_candidates}`}
          </div>
        )}
      </div>
      {message.citations && message.citations.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="text-xs text-gray-500 font-medium">
            📚 引用（{message.citations.length} 条）
          </div>
          {message.citations.map((c, i) => (
            <CitationCard key={i} index={i + 1} citation={c} />
          ))}
        </div>
      )}
    </div>
  )
}
