// 单条聊天消息（cn-msg-user / cn-msg-card 设计语言）
// 设计参考：claude design/pc-mock.jsx · UserMsg + AIMsg

import { Children } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

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

/**
 * 强制性用语分级（红线 3 的可视化）——与后端 `post_filter.MODAL_VERBS` 同一套定义，
 * 长度从长到短匹配，避免"不应"被切成"不"+"应"。
 *   强制 must   ：必须 / 严禁 / 不应 / 不得 / 应
 *   推荐 should ：宜 / 不宜
 *   允许 may    ：不可（单字"可"不高亮——可以/可能/认可 误报率太高，且法律效力最弱）
 */
const MODAL_TIERS: Record<string, 'must' | 'should' | 'may'> = {
  必须: 'must',
  严禁: 'must',
  不应: 'must',
  不得: 'must',
  应: 'must',
  不宜: 'should',
  宜: 'should',
  不可: 'may',
}
const MODAL_WORDS = Object.keys(MODAL_TIERS).sort((a, b) => b.length - a.length)

// 单字"应/宜"是常用字，需上下文守卫，否则会把 应用/响应/宜居/适宜 误标成强条用语
const GUARD_PREV: Record<string, string> = {
  应: '响供适反顺答呼相感效理',
  宜: '适便事',
}
const GUARD_NEXT: Record<string, string> = {
  应: '用该当对答付急届变邀有力',
  宜: '人居',
}

function isFalseModal(word: string, text: string, at: number): boolean {
  if (word.length > 1) return false // 多字量词（不应/必须…）无歧义
  const prev = at > 0 ? text[at - 1] : ''
  const next = at + word.length < text.length ? text[at + word.length] : ''
  return (
    (!!prev && (GUARD_PREV[word] ?? '').includes(prev)) ||
    (!!next && (GUARD_NEXT[word] ?? '').includes(next))
  )
}

/** 把文本里的 [N] 转成引用 chip、强制性用语转成分级标记 */
function renderWithCitations(
  text: string,
  activeCite?: number | null,
  onCiteClick?: (n: number) => void,
): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  // 一趟扫描同时处理：引用角标 + 强制性用语
  // 角标仅匹配 1-2 位（与后端 dangling 口径一致，W5 D5）：
  // 避免把「建标[2015]273号」这类年号/文号误渲染成可点引用角标。
  const re = new RegExp(`\\[(\\d{1,2})\\]|(${MODAL_WORDS.join('|')})`, 'g')
  let m: RegExpExecArray | null
  let key = 0
  while ((m = re.exec(text)) !== null) {
    // 命中强制性用语分支
    if (m[2] !== undefined) {
      const word = m[2]
      if (isFalseModal(word, text, m.index)) continue // 误报守卫：应用/宜居…跳过
      if (m.index > lastIndex) parts.push(text.slice(lastIndex, m.index))
      parts.push(
        <mark
          className={`cn-modal cn-modal-${MODAL_TIERS[word]}`}
          key={`modal-${key++}-${m.index}`}
          title={
            MODAL_TIERS[word] === 'must'
              ? '强制性用语：必须执行'
              : MODAL_TIERS[word] === 'should'
                ? '推荐性用语：宜执行，允许有条件偏离'
                : '允许性用语'
          }
        >
          {word}
        </mark>,
      )
      lastIndex = m.index + word.length
      continue
    }
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

/** Markdown 子节点里的纯文本仍要转成 [N] 引用 chip（守"可溯源"红线，不能被 md 渲染吃掉）*/
function withCitations(
  children: React.ReactNode,
  activeCite?: number | null,
  onCiteClick?: (n: number) => void,
): React.ReactNode {
  return Children.map(children, (child) =>
    typeof child === 'string' ? renderWithCitations(child, activeCite, onCiteClick) : child,
  )
}

/**
 * react-markdown 组件映射：所有含文本的元素都过一遍 withCitations，
 * 其余只挂 class 交给 design.css（保持内联样式最少、样式集中）。
 */
function mdComponents(
  activeCite?: number | null,
  onCiteClick?: (n: number) => void,
): Components {
  const t = (children: React.ReactNode) => withCitations(children, activeCite, onCiteClick)
  return {
    p: ({ children }) => <p className="cn-md-p">{t(children)}</p>,
    li: ({ children }) => <li>{t(children)}</li>,
    strong: ({ children }) => <strong>{t(children)}</strong>,
    em: ({ children }) => <em>{t(children)}</em>,
    h1: ({ children }) => <h3 className="cn-md-h">{t(children)}</h3>,
    h2: ({ children }) => <h3 className="cn-md-h">{t(children)}</h3>,
    h3: ({ children }) => <h3 className="cn-md-h">{t(children)}</h3>,
    h4: ({ children }) => <h4 className="cn-md-h">{t(children)}</h4>,
    blockquote: ({ children }) => <blockquote className="cn-md-quote">{children}</blockquote>,
    td: ({ children }) => <td>{t(children)}</td>,
    th: ({ children }) => <th>{t(children)}</th>,
    // 表格可能超出消息宽度 → 独立横向滚动，不撑破布局
    table: ({ children }) => (
      <div className="cn-md-table-wrap">
        <table className="cn-md-table">{children}</table>
      </div>
    ),
    code: ({ children }) => <code className="cn-md-code">{children}</code>,
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
  }
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
          {/* W7 agent①：查询分解 */}
          {message.retrieval?.decomposed && (
            <>
              <span>·</span>
              <span className="cn-agent-tag" title="复合/发散问题已拆成子问题，各自检索后合并，保证答得全">
                ⑂ 已拆解{' '}
                <span style={{ fontFamily: 'var(--font-mono)' }}>
                  {message.retrieval.sub_queries?.length ?? 0}
                </span>{' '}
                问
              </span>
            </>
          )}
          {/* W7 agent③：工具调用 */}
          {message.meta?.tool_agent_used && (
            <>
              <span>·</span>
              <span className="cn-agent-tag" title="查表/元信息类问题由工具直接查询作答，不走向量检索">
                ⚒ 工具 {message.meta.tool_calls?.join(' / ')}
              </span>
            </>
          )}
          {/* W7 agent②：引用核验 */}
          {message.meta?.grounding_verified && (
            <>
              <span>·</span>
              {message.meta.grounding_ok ? (
                <span
                  style={{ color: 'var(--status-active)' }}
                  title="已逐项核对答案中的规范号/条文号/数字是否有据"
                >
                  ✓ 引用已核验
                </span>
              ) : (
                <span
                  style={{ color: 'var(--amber)' }}
                  title={message.meta.grounding_issues?.join('；')}
                >
                  ⚑ {message.meta.grounding_issues?.length ?? 0} 处待核
                </span>
              )}
            </>
          )}
          {message.fallback && (
            <span style={{ color: 'var(--amber)' }}>● 兜底场景 · {message.fallback}</span>
          )}
          {!message.fallback &&
            message.done &&
            (() => {
              // 消息级状态：引用里有已废止/局部废止规范则告警（守"像查法条"的现行性）
              const cites = message.citations ?? []
              if (cites.some((c) => c.status === '已废止'))
                return (
                  <span style={{ color: 'var(--status-deprecated)' }}>● 含已废止规范</span>
                )
              if (cites.some((c) => c.status === '局部废止'))
                return <span style={{ color: 'var(--status-partial)' }}>● 含局部废止规范</span>
              return <span style={{ color: 'var(--status-active)' }}>● 现行有效</span>
            })()}
        </div>

        <div className="cn-msg-card">
          {/* W7 agent①：展示拆出的子问题（让"答得全"这件事可见）*/}
          {message.retrieval?.decomposed &&
            (message.retrieval.sub_queries?.length ?? 0) > 0 && (
              <div className="cn-agent-trace">
                <div className="cn-agent-trace-head">已拆解为子问题，分别检索后合并</div>
                <div className="cn-agent-trace-chips">
                  {message.retrieval.sub_queries!.map((sq, i) => (
                    <span key={i} className="cn-agent-subq">
                      <span style={{ fontFamily: 'var(--font-mono)', opacity: 0.6 }}>
                        {i + 1}
                      </span>{' '}
                      {sq}
                    </span>
                  ))}
                </div>
              </div>
            )}

          {/* W7 agent②：核验发现无据项 → 显式告警（守"不编造"红线的可见性）*/}
          {message.meta?.grounding_verified &&
            !message.meta.grounding_ok &&
            (message.meta.grounding_issues?.length ?? 0) > 0 && (
              <div className="cn-agent-warn">
                <div className="cn-agent-warn-head">⚑ 引用核验发现待核项</div>
                <ul className="cn-agent-warn-list">
                  {message.meta.grounding_issues!.map((iss, i) => (
                    <li key={i}>{iss}</li>
                  ))}
                </ul>
              </div>
            )}

          {message.error ? (
            <div style={{ color: 'var(--terracotta)', fontSize: 13 }}>
              ❌ 出错：{message.error}
            </div>
          ) : message.streaming && !message.content ? (
            // 首字到达前：分阶段"思考中"动画，避免被当成卡住
            <div className="cn-thinking" aria-live="polite">
              <span className="cn-thinking-dots" aria-hidden>
                <i />
                <i />
                <i />
              </span>
              <span className="cn-thinking-text">
                {message.retrieval ? '已检索规范库，正在生成回答…' : '正在检索规范库…'}
              </span>
            </div>
          ) : (
            <div className="cn-md">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={mdComponents(activeCite, onCiteClick)}
              >
                {message.content}
              </ReactMarkdown>
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
