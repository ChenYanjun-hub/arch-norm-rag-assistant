// 引用卡片（cn-cite-card 设计语言）
// 设计参考：claude design/pc-mock.jsx · CiteCard
//
// 后端 Citation 字段：spec_name / spec_code / clause / page / is_mandatory / original_text / domain
// 设计稿额外字段（暂无后端数据，先省略）：状态徽章 / 释义 / PDF 缩略图 / 关联条文

import type { Citation } from '../types/chat'

interface Props {
  index: number
  citation: Citation
  /** 当前激活态（被正文 [n] 角标点中时高亮） */
  active?: boolean
  onClick?: () => void
}

/** 根据 domain 映射设计 token 中的分类色 */
function domainKey(domain: string): 'arch' | 'landscape' | 'planning' {
  if (domain.includes('景观')) return 'landscape'
  if (domain.includes('规划')) return 'planning'
  return 'arch' // 建筑 / 消防 默认归入建筑深绿系
}

export function CitationCard({ index, citation, active, onClick }: Props) {
  const { spec_name, spec_code, clause, page, is_mandatory, original_text, domain } =
    citation

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
          {is_mandatory && (
            <span className="cn-badge is-partial" style={{ marginLeft: 'auto' }}>
              强制性
            </span>
          )}
          {!is_mandatory && (
            <span className="cn-badge is-active" style={{ marginLeft: 'auto' }}>
              现行有效
            </span>
          )}
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
      </div>

      <div className="cn-cite-body">
        <div className="cn-cite-section">
          <div className="cn-cite-section-label">原文条文</div>
          <div className="cn-cite-quote">{original_text || '（原文片段为空）'}</div>
        </div>
      </div>
    </div>
  )
}
