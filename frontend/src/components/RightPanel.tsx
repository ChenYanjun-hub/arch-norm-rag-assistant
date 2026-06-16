// 右侧引用面板（cn-app 设计语言）
// 显示当前最新一条 assistant 消息的引用列表

import { useEffect, useRef, useState } from 'react'
import type { Citation, PipelineMeta } from '../types/chat'
import { CitationCard } from './CitationCard'

interface Props {
  citations: Citation[]
  /** 当前 inline 角标选中（W3 接 highlight） */
  activeIndex?: number | null
  onActiveChange?: (i: number) => void
  /** W6 D4：pipeline 治理透明度（dangling / post_filter / modal align） */
  meta?: PipelineMeta
}

export function RightPanel({ citations, activeIndex, onActiveChange, meta }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const cardRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const [tab, setTab] = useState<'clause' | 'pdf'>('clause')

  // PDF 标签页显示的引用：跟随 activeIndex（被正文 [N]/卡片选中），缺省第 1 条
  const pdfIndex = Math.min(Math.max(activeIndex ?? 1, 1), Math.max(citations.length, 1))
  const shown = citations[pdfIndex - 1]

  // 当 activeIndex 改变 → 滚动到对应卡片
  useEffect(() => {
    if (activeIndex == null) return
    const el = cardRefs.current[activeIndex]
    if (el && scrollRef.current) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [activeIndex])

  // 无引用（如兜底场景）时回退到「条文」tab，避免停在禁用的 PDF tab
  useEffect(() => {
    if (citations.length === 0) setTab('clause')
  }, [citations.length])

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
          <button
            className={'cn-right-tab' + (tab === 'clause' ? ' is-active' : '')}
            onClick={() => setTab('clause')}
          >
            条文 ({citations.length})
          </button>
          <button
            className={'cn-right-tab' + (tab === 'pdf' ? ' is-active' : '')}
            onClick={() => setTab('pdf')}
            disabled={citations.length === 0}
            style={citations.length === 0 ? { cursor: 'not-allowed', opacity: 0.4 } : undefined}
            title="内嵌查看规范原文 PDF（定位到被引页）"
          >
            PDF 原文
          </button>
        </div>

        {/* W6 D4：pipeline 治理透明度 — 三个角标 + tooltip */}
        {meta && (
          <div
            style={{
              display: 'flex',
              gap: 8,
              padding: '8px 0 4px',
              fontSize: 10.5,
              color: 'var(--ink-mute)',
              fontFamily: 'var(--font-mono)',
              borderTop: '1px dashed var(--border)',
              marginTop: 2,
            }}
            title="后处理治理透明度（W5 D4 / W6 D2 / W6 D4 集成）"
          >
            <span
              style={{
                color: (meta.dangling_count ?? 0) > 0 ? '#c25450' : 'var(--ink-faint)',
              }}
              title={`dangling [N] 引用: ${meta.dangling_count ?? 0} 个越界（W5 D4 监控）`}
            >
              ⚑ {meta.dangling_count ?? 0}
            </span>
            <span
              style={{
                color:
                  (meta.post_filter_stripped_chars ?? 0) > 0
                    ? '#2e7d32'
                    : 'var(--ink-faint)',
              }}
              title={`post_filter 剥离 "补充说明" 节: ${meta.post_filter_stripped_chars ?? 0} 字（W6 D2 治理 dim7 编造）`}
            >
              ✂ {meta.post_filter_stripped_chars ?? 0}
            </span>
            <span
              style={{
                color:
                  (meta.modal_verb_corrections ?? 0) > 0 ? '#1565c0' : 'var(--ink-faint)',
              }}
              title={`align_modal_verbs 量词校正: ${meta.modal_verb_corrections ?? 0} 处（W6 D4 治理 dim4 用词错）`}
            >
              ✎ {meta.modal_verb_corrections ?? 0}
            </span>
            <span
              style={{
                color:
                  (meta.number_corrections ?? 0) > 0 ? '#8e24aa' : 'var(--ink-faint)',
              }}
              title={`align_numbers 数字校正: ${meta.number_corrections ?? 0} 处（W7 D1 治理 dim5 数字精确）`}
            >
              ⌗ {meta.number_corrections ?? 0}
            </span>
          </div>
        )}
      </div>

      {tab === 'clause' ? (
        <div
          ref={scrollRef}
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
            citations.map((c, i) => {
              const n = i + 1
              return (
                <div
                  key={i}
                  ref={(el) => {
                    cardRefs.current[n] = el
                  }}
                >
                  <CitationCard
                    index={n}
                    citation={c}
                    active={activeIndex === n}
                    onClick={() => onActiveChange?.(n)}
                  />
                </div>
              )
            })
          )}
        </div>
      ) : (
        // PDF 原文内嵌（iframe + 浏览器 PDF 阅读器，#page 锚点定位被引页）
        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
            padding: '10px 14px 14px',
            gap: 8,
          }}
        >
          {!shown ? (
            <div style={{ fontSize: 12.5, color: 'var(--ink-faint)', padding: '40px 8px', textAlign: 'center' }}>
              还没有引用
            </div>
          ) : (
            <>
              {citations.length > 1 && (
                <div className="cn-pdf-switch">
                  {citations.map((c, i) => (
                    <button
                      key={i}
                      className={'cn-pdf-chip' + (pdfIndex === i + 1 ? ' is-active' : '')}
                      onClick={() => onActiveChange?.(i + 1)}
                      title={`${c.spec_code} · 第 ${c.page ?? '?'} 页`}
                    >
                      {i + 1}
                    </button>
                  ))}
                </div>
              )}
              <div className="cn-pdf-meta" title={shown.spec_name}>
                《{shown.spec_name}》·{' '}
                <span style={{ fontFamily: 'var(--font-mono)' }}>{shown.spec_code}</span>
                {shown.page ? ` · 第 ${shown.page} 页` : ''}
              </div>
              <iframe
                key={`${shown.spec_code}:${shown.page ?? 1}`}
                title="规范原文 PDF"
                src={`/api/spec/${encodeURIComponent(shown.spec_code)}#page=${shown.page ?? 1}`}
                style={{
                  width: '100%',
                  flex: 1,
                  minHeight: 0,
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  background: '#fff',
                }}
              />
              <a
                href={`/api/spec/${encodeURIComponent(shown.spec_code)}#page=${shown.page ?? 1}`}
                target="_blank"
                rel="noopener noreferrer"
                className="cn-pdf-open"
              >
                在新标签页打开 ↗
              </a>
            </>
          )}
        </div>
      )}
    </aside>
  )
}
