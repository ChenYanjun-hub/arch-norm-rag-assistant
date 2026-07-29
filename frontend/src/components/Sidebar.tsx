// 左侧导航栏（cn-app 设计语言 · 深绿色文档感）
// 规范分类计数从 GET /api/stats 动态读取（接口未就绪时回退默认值）

import { useState } from 'react'
import type { Conversation, CorpusStats, SpecBrief } from '../types/chat'

interface Props {
  onNewChat?: () => void
  /** 语料统计（动态计数）；null 时用回退默认值 */
  stats?: CorpusStats | null
  /** V2-3：历史会话列表 */
  conversations?: Conversation[]
  /** 当前激活会话 id */
  activeId?: string | null
  /** 点击历史项 → 切换 */
  onSelectConversation?: (id: string) => void
  /** 删除历史项 */
  onDeleteConversation?: (id: string) => void
  /** 点击某部规范 → 切换该规范的限定（多选 toggle）*/
  onSelectSpec?: (spec: SpecBrief) => void
  /** 当前限定的规范号列表（高亮）*/
  activeSpecCodes?: string[]
}

// domain → 设计 token 分类色（展示层映射，留前端）
const DOMAIN_CAT: Record<string, string> = {
  规划: 'planning',
  建筑: 'arch',
  景观: 'landscape',
  消防: 'arch',
  结构: 'structure',
  市政: 'municipal',
}

// 规范状态 → 小圆点颜色（复用 status token）
const STATUS_COLOR: Record<string, string> = {
  现行: 'var(--status-active)',
  已废止: 'var(--status-deprecated)',
  局部废止: 'var(--status-partial)',
  即将实施: 'var(--indigo)',
}

// 接口未就绪时的回退（与入库实测一致），避免首屏闪空
/** 历史会话默认展示条数，超出折叠到「查看全部」*/
const HISTORY_PREVIEW_N = 6

/** 相对时间：刚刚 / 今天 HH:MM / 昨天 / 前天 / M月D日 */
function formatRelTime(ts: number): string {
  if (!ts) return ''
  const now = new Date()
  const d = new Date(ts)
  const diffMin = Math.floor((now.getTime() - ts) / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  // 按"自然日"差判断今天/昨天/前天（不能用 24h 整除，跨零点会算错）
  const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const dayDiff = Math.round((startOfDay(now) - startOfDay(d)) / 86400000)
  const hhmm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (dayDiff === 0) return hhmm
  if (dayDiff === 1) return '昨天'
  if (dayDiff === 2) return '前天'
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

const FALLBACK_DOMAINS = [
  { domain: '规划', spec_count: 18 },
  { domain: '建筑', spec_count: 11 },
  { domain: '景观', spec_count: 7 },
  { domain: '消防', spec_count: 3 },
]

export function Sidebar({
  onNewChat,
  stats,
  conversations = [],
  activeId = null,
  onSelectConversation,
  onDeleteConversation,
  onSelectSpec,
  activeSpecCodes = [],
}: Props) {
  const domains = stats?.domains ?? FALLBACK_DOMAINS
  const totalSpecs = stats?.total_specs ?? 39
  const [openDomains, setOpenDomains] = useState<Record<string, boolean>>({})
  const [showAllHistory, setShowAllHistory] = useState(false)

  return (
    <aside
      className="cn-layout-sidebar"
      style={{
        width: 264,
        background: 'var(--sidebar)',
        color: 'var(--sidebar-text)',
        display: 'flex',
        flexDirection: 'column',
        flex: '0 0 auto',
        borderRight: '1px solid var(--sidebar-line)',
        fontSize: 13,
      }}
    >
      <div className="cn-logo">
        <div className="cn-logo-mark" aria-label="品牌标识">同</div>
        <div className="cn-logo-text">
          <div className="cn-logo-name">建景规·助手</div>
          <div className="cn-logo-sub">REGULATION&nbsp;COPILOT</div>
        </div>
      </div>

      <button className="cn-new-chat" onClick={onNewChat}>
        <span>＋</span>
        <span>新建对话</span>
        <span className="cn-kbd">⌘N</span>
      </button>

      <div className="cn-scroll cn-scroll-dark" style={{ flex: 1, padding: '6px 0 16px' }}>
        <div className="cn-side-section">
          <div className="cn-side-section-title">
            <span>规范分类</span>
            <span style={{ fontSize: 10 }}>{totalSpecs} 部</span>
          </div>
          <div>
            {domains.map((t) => {
              const open = !!openDomains[t.domain]
              const specs: SpecBrief[] = (t as { specs?: SpecBrief[] }).specs ?? []
              const toggle = () =>
                setOpenDomains((s) => ({ ...s, [t.domain]: !s[t.domain] }))
              return (
                <div key={t.domain}>
                  <div
                    className="cn-side-item"
                    onClick={toggle}
                    role="button"
                    tabIndex={0}
                    aria-expanded={open}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        toggle()
                      }
                    }}
                  >
                    <span
                      className="cn-side-caret"
                      style={{ transform: open ? 'rotate(90deg)' : 'none' }}
                      aria-hidden
                    >
                      ▸
                    </span>
                    <span
                      className={`cn-tag-dot cn-cat-${DOMAIN_CAT[t.domain] ?? 'arch'}`}
                      style={{ width: 8, height: 8, borderRadius: 2 }}
                    />
                    <span style={{ fontWeight: 500 }}>{t.domain}</span>
                    <span className="cn-side-meta">{t.spec_count}</span>
                  </div>
                  {open && specs.length > 0 && (
                    <div className="cn-spec-list">
                      {specs.map((sp) => (
                        <div
                          key={sp.spec_code}
                          className={
                            'cn-spec-row' +
                            (activeSpecCodes.includes(sp.spec_code) ? ' is-active' : '')
                          }
                          onClick={() => onSelectSpec?.(sp)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              onSelectSpec?.(sp)
                            }
                          }}
                          title={`${sp.spec_name} ${sp.spec_code}（点击只查这部）`}
                        >
                          <span
                            className="cn-spec-dot"
                            style={{ background: STATUS_COLOR[sp.status] ?? STATUS_COLOR['现行'] }}
                          />
                          <span className="cn-spec-name">{sp.spec_name}</span>
                          <span className="cn-spec-code">{sp.spec_code}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        <div className="cn-side-section">
          <div className="cn-side-section-title">
            <span>历史会话</span>
            <span style={{ fontSize: 10 }}>{conversations.length}</span>
          </div>
          {conversations.length === 0 ? (
            <div className="cn-hist-empty">暂无历史 · 提问后自动保存到本地</div>
          ) : (
            <div>
              {(showAllHistory ? conversations : conversations.slice(0, HISTORY_PREVIEW_N)).map((c) => (
                <div
                  key={c.id}
                  className={'cn-hist-item' + (c.id === activeId ? ' is-active' : '')}
                  onClick={() => onSelectConversation?.(c.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onSelectConversation?.(c.id)
                    }
                  }}
                  title={c.title}
                >
                  <span className="cn-side-icon" aria-hidden>
                    💬
                  </span>
                  <span className="cn-hist-title">{c.title}</span>
                  <span className="cn-hist-time">{formatRelTime(c.updatedAt)}</span>
                  <button
                    className="cn-hist-del"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteConversation?.(c.id)
                    }}
                    aria-label={`删除会话：${c.title}`}
                  >
                    ×
                  </button>
                </div>
              ))}
              {conversations.length > HISTORY_PREVIEW_N && (
                <button
                  className="cn-hist-more"
                  onClick={() => setShowAllHistory((v) => !v)}
                >
                  {showAllHistory
                    ? '收起 ↑'
                    : `查看全部 (${conversations.length}) →`}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <div
        style={{
          borderTop: '1px solid var(--sidebar-line)',
          padding: '12px 14px',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #c89456, #8b6f47)',
            color: '#fff',
            fontSize: 12,
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          U
        </div>
        <div style={{ lineHeight: 1.3, fontSize: 12.5 }}>
          <div style={{ color: '#fff' }}>访客</div>
          <div style={{ color: 'var(--sidebar-text-mute)', fontSize: 11 }}>MVP 体验版</div>
        </div>
      </div>
    </aside>
  )
}
