// 引用卡片（cn-cite-card 设计语言）
// 设计参考：claude design/pc-mock.jsx · CiteCard
//
// 后端 Citation 字段：spec_name / spec_code / clause / page / is_mandatory / original_text / domain
// 设计稿额外字段（暂无后端数据，先省略）：状态徽章 / 释义 / PDF 缩略图 / 关联条文

import type { Citation, SpecStatus } from '../types/chat'

interface Props {
  index: number
  citation: Citation
  /** 当前激活态（被正文 [n] 角标点中时高亮） */
  active?: boolean
  onClick?: () => void
}

/** 根据 domain 映射设计 token 中的分类色 */
function domainKey(
  domain: string,
): 'arch' | 'landscape' | 'planning' | 'structure' | 'municipal' {
  if (domain.includes('景观')) return 'landscape'
  if (domain.includes('规划')) return 'planning'
  if (domain.includes('结构')) return 'structure'
  if (domain.includes('市政')) return 'municipal'
  return 'arch' // 建筑 / 消防 默认归入建筑深蓝系
}

/** 规范状态 → 徽章 class + 文案 + 提示色（4 态，对应 CSS .cn-badge.is-*）*/
const STATUS_META: Record<SpecStatus, { cls: string; label: string; color: string }> = {
  现行: { cls: 'is-active', label: '现行有效', color: 'var(--status-active)' },
  已废止: { cls: 'is-deprecated', label: '已废止', color: 'var(--status-deprecated)' },
  局部废止: { cls: 'is-partial', label: '局部废止', color: 'var(--status-partial)' },
  即将实施: { cls: 'is-upcoming', label: '即将实施', color: 'var(--indigo)' },
}

export function CitationCard({ index, citation, active, onClick }: Props) {
  const {
    spec_name, spec_code, clause, page, is_mandatory, original_text, domain, has_formula,
    status, replaced_by, status_note,
  } = citation
  const stMeta = STATUS_META[status ?? '现行'] ?? STATUS_META['现行']

  const clauseDisp =
    clause.startsWith('表') || clause.startsWith('式')
      ? clause
      : `§ ${clause}`

  const cat = domainKey(domain)

  return (
    <div
      onClick={onClick}
      className="cn-cite-card"
      style={
        active
          ? { boxShadow: '0 0 0 2px var(--amber)', borderColor: 'var(--amber)' }
          : undefined
      }
    >
      <div className="cn-cite-head">
        <div className="cn-cite-eyebrow">
          <span className="cn-cite-num">{index}</span>
          <span>条文出处</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
            {is_mandatory && <span className="cn-badge is-partial">强制性</span>}
            {has_formula && (
              <span
                className="cn-badge cn-badge-formula"
                title="本条含计算公式。公式在 PDF 提取中易损坏，摘引可能不完整，请以原文 PDF 为准"
              >
                含公式·查原文
              </span>
            )}
            <span className={`cn-badge ${stMeta.cls}`}>{stMeta.label}</span>
          </span>
        </div>
        <div className="cn-cite-title">《{spec_name}》</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span className="cn-cite-id">{spec_code}</span>
          <span style={{ fontSize: 11, color: 'var(--ink-faint)' }}>·</span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              color: 'var(--primary)',
              fontWeight: 600,
            }}
          >
            {clauseDisp}
          </span>
          {page !== null && (
            <span style={{ fontSize: 11, color: 'var(--ink-faint)' }}>
              · 第 {page} 页
            </span>
          )}
          <span
            className={`cn-tag-dot cn-cat-${cat}`}
            style={{ width: 8, height: 8, borderRadius: 50 }}
            title={domain}
          />
        </div>

        {/* 非现行状态：突出现行替代版本 / 废止说明（红线：状态来自权威例外表，不臆断）*/}
        {status && status !== '现行' && (replaced_by || status_note) && (
          <div style={{ marginTop: 6, fontSize: 11.5, fontWeight: 500, color: stMeta.color }}>
            {replaced_by ? `现行版本：${replaced_by}` : ''}
            {replaced_by && status_note ? ' · ' : ''}
            {status_note ?? ''}
          </div>
        )}
      </div>

      <div className="cn-cite-body">
        <div className="cn-cite-section">
          <div className="cn-cite-section-label">原文条文</div>
          <div className="cn-cite-quote">{original_text || '（原文片段为空）'}</div>
        </div>

        {spec_code && (
          <div className="cn-cite-section">
            <a
              href={`/api/spec/${encodeURIComponent(spec_code)}${page ? `#page=${page}` : ''}`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '7px 12px',
                fontSize: 12,
                color: 'var(--primary)',
                background: 'var(--primary-soft)',
                border: '1px solid var(--primary-line)',
                borderRadius: 6,
                textDecoration: 'none',
                fontFamily: 'inherit',
                transition: 'all .14s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'var(--primary)'
                e.currentTarget.style.color = '#fff'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'var(--primary-soft)'
                e.currentTarget.style.color = 'var(--primary)'
              }}
            >
              <span>📄</span>
              <span>查看原文 PDF</span>
              {page && (
                <span style={{ fontFamily: 'var(--font-mono)', opacity: 0.7 }}>
                  · 第 {page} 页
                </span>
              )}
              <span>↗</span>
            </a>
          </div>
        )}
      </div>
    </div>
  )
}
