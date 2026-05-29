// 问答主页面（P2 · MVP 阶段）

import { useEffect, useRef, useState } from 'react'
import { useChatStore } from '../stores/chatStore'
import { ChatMessage } from '../components/ChatMessage'

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

  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages])

  function handleSubmit(e?: React.FormEvent) {
    e?.preventDefault()
    if (!input.trim() || isStreaming) return
    const q = input
    setInput('')
    void send(q)
  }

  function handleSampleClick(q: string) {
    if (isStreaming) return
    setInput(q)
    void send(q)
  }

  return (
    <div className="h-full flex flex-col">
      {/* 顶栏 */}
      <header className="border-b border-gray-200 bg-white px-6 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">
            建景规规范知识问答助手
          </h1>
          <p className="text-xs text-gray-500">
            覆盖规划 / 建筑 / 景观 / 消防 4 类设计规范（39 部 / 4773 条）
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clear}
            disabled={isStreaming}
            className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-30"
          >
            清空对话
          </button>
        )}
      </header>

      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto flex flex-col gap-5">
          {messages.length === 0 ? (
            <EmptyState onPick={handleSampleClick} />
          ) : (
            messages.map((m) => <ChatMessage key={m.id} message={m} />)
          )}
        </div>
      </div>

      {/* 输入框 */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-gray-200 bg-white px-6 py-4"
      >
        <div className="max-w-3xl mx-auto flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSubmit()
              }
            }}
            placeholder="输入规范查询问题（Enter 发送，Shift+Enter 换行）"
            rows={2}
            maxLength={500}
            disabled={isStreaming}
            className="flex-1 resize-none border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-50"
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {isStreaming ? '回答中…' : '发送'}
          </button>
        </div>
        <div className="max-w-3xl mx-auto mt-1.5 text-[11px] text-gray-400 text-right">
          {input.length} / 500
        </div>
      </form>
    </div>
  )
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="text-center py-10">
      <div className="text-5xl mb-3">📐</div>
      <h2 className="text-xl font-medium text-gray-900 mb-1">
        从这里开始查询设计规范
      </h2>
      <p className="text-sm text-gray-500 mb-6">
        像查法条一样严谨，所有答案带规范号 + 条文号 + 原文引用
      </p>
      <div className="max-w-md mx-auto flex flex-col gap-2">
        <div className="text-xs text-gray-400 mb-1">试试这些示例：</div>
        {SAMPLE_QUERIES.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="text-left text-sm text-gray-700 bg-white hover:bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
