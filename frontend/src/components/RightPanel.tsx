// 右侧引用面板（cn-app 设计语言）
// 显示当前最新一条 assistant 消息的引用列表

import type { Citation } from '../types/chat'
import { CitationCard } from './CitationCard'

interface Props {
  citations: Citation[]
  /** 当前 inline 角标选中（W3 接 highlight） */
  activeIndex?: number | null
  onActiveChange?: (i: number) => void
}

export function RightPanel({ citations, activeIndex, onActiveChange }: Props) {
  return (
    <aside
      className="cn-layout-rightpanel"
      style={{
        width: 380,
        flex: '0 0 auto',
        background: 'var(--paper-soft)',
        borderLeft: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ padding: '0 18px', background: 'var(--paper-soft)' }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '13px 0 11px' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>规范出处</div>
          <div style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-mute)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
              {citations.length}
            </span>{' '}
            条引用
          </div>
        </div>
        <div className="cn-right-tabs">
          <button className="cn-right-tab is-active">条文 ({citations.length})</button>
          <button
            className="cn-right-tab"
            disabled
            style={{ cursor: 'not-allowed', opacity: 0.4 }}
            title="PDF 原文跳转 · W3 上线"
          >
            PDF 原文
          </button>
          <button
            className="cn-right-tab"
            disabled
            style={{ cursor: 'not-allowed', opacity: 0.4 }}
            title="关联条文 · V2 上线"
          >
            关联
          </button>
        </div>
      </div>

      <div
        className="cn-scroll"
        style={{
          flex: 1,
          padding: '14px 18px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        {citations.length === 0 ? (
          <div
            style={{
              fontSize: 12.5,
              color: 'var(--ink-faint)',
              padding: '40px 8px',
              textAlign: 'center',
              lineHeight: 1.7,
            }}
          >
            还没有引用
            <br />
            <span style={{ fontSize: 11 }}>提问后会在这里显示规范条文出处</span>
          </div>
        ) : (
          citations.map((c, i) => (
            <CitationCard
              key={i}
              index={i + 1}
              citation={c}
              active={activeIndex === i + 1}
              onClick={() => onActiveChange?.(i + 1)}
            />
          ))
        )}
      </div>
    </aside>
  )
}
