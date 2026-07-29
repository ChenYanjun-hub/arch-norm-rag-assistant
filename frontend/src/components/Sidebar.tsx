// 左侧导航栏（cn-app 设计语言 · 深绿色文档感）
// 规范分类计数从 GET /api/stats 动态读取（接口未就绪时回退默认值）

import { useState } from 'react'
import type { Conversation, CorpusStats, Project, SpecBrief } from '../types/chat'

interface Props {
  onNewChat?: () => void
  /** 语料统计（动态计数）；null 时用回退默认值 */
  stats?: CorpusStats | null
  /** W7：项目工作区 */
  projects?: Project[]
  activeProjectId?: string | null
  onSelectProject?: (id: string | null) => void
  onCreateProject?: (name: string) => void
  onDeleteProject?: (id: string) => void
  /** 把当前选中的规范限定存为该项目的默认范围 */
  onSetProjectSpecs?: (id: string, specCodes: string[]) => void
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
  projects = [],
  activeProjectId = null,
  onSelectProject,
  onCreateProject,
  onDeleteProject,
  onSetProjectSpecs,
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
  const [creatingProject, setCreatingProject] = useState(false)
  const [newProjName, setNewProjName] = useState('')

  const [search, setSearch] = useState('')

  // 选中项目时，历史列表只显示该项目下的会话
  const visibleConversations = activeProjectId
    ? conversations.filter((c) => c.projectId === activeProjectId)
    : conversations

  // ── 搜索：跨「对话正文 / 项目 / 规范」三类，纯前端即时过滤 ──
  const q = search.trim().toLowerCase()
  const searching = q.length > 0
  const searchHits = (() => {
    if (!searching) return null
    const hitProjects = projects.filter((p) => p.name.toLowerCase().includes(q))
    // 对话：标题命中，或任一条消息正文命中（后者才是"我上次问过这个"的真实用法）
    const hitConversations = conversations
      .map((c) => {
        const inTitle = c.title.toLowerCase().includes(q)
        const msg = c.messages.find((m) => (m.content || '').toLowerCase().includes(q))
        if (!inTitle && !msg) return null
        // 命中片段：截取匹配位置前后各 12 字，让用户看清命中在哪
        let snippet = ''
        if (msg) {
          const text = msg.content
          const i = text.toLowerCase().indexOf(q)
          snippet =
            (i > 12 ? '…' : '') +
            text.slice(Math.max(0, i - 12), i + q.length + 12).replace(/\n/g, ' ')
        }
        return { conv: c, snippet }
      })
      .filter((x): x is { conv: Conversation; snippet: string } => x !== null)
    // 规范：跨所有域的规范名 / 规范号
    const allSpecs: SpecBrief[] = domains.flatMap(
      (d) => (d as { specs?: SpecBrief[] }).specs ?? [],
    )
    const hitSpecs = allSpecs.filter(
      (s) =>
        s.spec_name.toLowerCase().includes(q) ||
        s.spec_code.toLowerCase().replace(/\s/g, '').includes(q.replace(/\s/g, '')),
    )
    return { hitProjects, hitConversations, hitSpecs }
  })()

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

      <div className="cn-search">
        <span className="cn-search-icon" aria-hidden>⌕</span>
        <input
          className="cn-search-input"
          placeholder="搜索条文 / 对话 / 项目"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setSearch('')
          }}
          aria-label="搜索条文、对话或项目"
        />
        {searching && (
          <button className="cn-search-clear" onClick={() => setSearch('')} aria-label="清空搜索">
            ×
          </button>
        )}
      </div>

      <div className="cn-scroll cn-scroll-dark" style={{ flex: 1, padding: '6px 0 16px' }}>
        {/* 搜索态：结果替换常规分区，避免上下并列造成混淆 */}
        {searching && searchHits && (
          <div className="cn-side-section">
            <div className="cn-side-section-title">
              <span>搜索结果</span>
              <span style={{ fontSize: 10 }}>
                {searchHits.hitProjects.length +
                  searchHits.hitConversations.length +
                  searchHits.hitSpecs.length}
              </span>
            </div>

            {searchHits.hitProjects.length === 0 &&
            searchHits.hitConversations.length === 0 &&
            searchHits.hitSpecs.length === 0 ? (
              <div className="cn-hist-empty">无匹配 · 试试规范号、关键词或项目名</div>
            ) : (
              <>
                {searchHits.hitProjects.length > 0 && (
                  <div className="cn-search-group">
                    <div className="cn-search-group-title">项目</div>
                    {searchHits.hitProjects.map((p) => (
                      <div
                        key={p.id}
                        className="cn-proj-item"
                        onClick={() => {
                          onSelectProject?.(p.id)
                          setSearch('')
                        }}
                        role="button"
                        tabIndex={0}
                      >
                        <span className="cn-side-icon" aria-hidden>📁</span>
                        <span className="cn-hist-title">{p.name}</span>
                      </div>
                    ))}
                  </div>
                )}

                {searchHits.hitConversations.length > 0 && (
                  <div className="cn-search-group">
                    <div className="cn-search-group-title">对话</div>
                    {searchHits.hitConversations.map(({ conv, snippet }) => (
                      <div
                        key={conv.id}
                        className="cn-search-conv"
                        onClick={() => {
                          onSelectConversation?.(conv.id)
                          setSearch('')
                        }}
                        role="button"
                        tabIndex={0}
                        title={conv.title}
                      >
                        <div className="cn-search-conv-title">{conv.title}</div>
                        {snippet && <div className="cn-search-conv-snip">{snippet}</div>}
                      </div>
                    ))}
                  </div>
                )}

                {searchHits.hitSpecs.length > 0 && (
                  <div className="cn-search-group">
                    <div className="cn-search-group-title">规范（点击限定检索范围）</div>
                    {searchHits.hitSpecs.slice(0, 8).map((sp) => (
                      <div
                        key={sp.spec_code}
                        className={
                          'cn-spec-row' +
                          (activeSpecCodes.includes(sp.spec_code) ? ' is-active' : '')
                        }
                        onClick={() => onSelectSpec?.(sp)}
                        role="button"
                        tabIndex={0}
                        title={`${sp.spec_name} ${sp.spec_code}`}
                      >
                        <span
                          className="cn-spec-dot"
                          style={{ background: STATUS_COLOR[sp.status] ?? STATUS_COLOR['现行'] }}
                        />
                        <span className="cn-spec-name">{sp.spec_name}</span>
                        <span className="cn-spec-code">{sp.spec_code}</span>
                      </div>
                    ))}
                    {searchHits.hitSpecs.length > 8 && (
                      <div className="cn-search-more">
                        还有 {searchHits.hitSpecs.length - 8} 部…请补充关键词
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* 非搜索态：常规三分区 */}
        {!searching && (
          <>
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

        {/* W7 项目工作区：项目 = 会话分组 + 预设规范限定 */}
        <div className="cn-side-section">
          <div className="cn-side-section-title">
            <span>项目工作区</span>
            <button
              className="cn-proj-add"
              onClick={() => setCreatingProject((v) => !v)}
              title="新建项目"
              aria-label="新建项目"
            >
              ＋
            </button>
          </div>

          {creatingProject && (
            <div className="cn-proj-new">
              <input
                className="cn-proj-input"
                autoFocus
                placeholder="项目名称，回车创建"
                value={newProjName}
                onChange={(e) => setNewProjName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newProjName.trim()) {
                    onCreateProject?.(newProjName)
                    setNewProjName('')
                    setCreatingProject(false)
                  } else if (e.key === 'Escape') {
                    setNewProjName('')
                    setCreatingProject(false)
                  }
                }}
                maxLength={30}
              />
            </div>
          )}

          {projects.length === 0 ? (
            !creatingProject && (
              <div className="cn-hist-empty">
                暂无项目 · 建项目可按工程分组问答、预设规范范围
              </div>
            )
          ) : (
            <div>
              {projects.map((p) => {
                const n = conversations.filter((c) => c.projectId === p.id).length
                const isActive = p.id === activeProjectId
                return (
                  <div
                    key={p.id}
                    className={'cn-proj-item' + (isActive ? ' is-active' : '')}
                    // 再次点击已选中的项目 = 取消选中（回到"全部"）
                    onClick={() => onSelectProject?.(isActive ? null : p.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onSelectProject?.(isActive ? null : p.id)
                      }
                    }}
                    title={
                      p.specCodes.length
                        ? `${p.name} · 已预设 ${p.specCodes.length} 部规范限定`
                        : p.name
                    }
                  >
                    <span className="cn-side-icon" aria-hidden>
                      {isActive ? '📂' : '📁'}
                    </span>
                    <span className="cn-hist-title">{p.name}</span>
                    {p.specCodes.length > 0 && (
                      <span className="cn-proj-specs" title={`预设 ${p.specCodes.length} 部规范`}>
                        ⛬{p.specCodes.length}
                      </span>
                    )}
                    <span className="cn-proj-count">{n}</span>
                    {isActive && activeSpecCodes.length > 0 && (
                      <button
                        className="cn-proj-save"
                        onClick={(e) => {
                          e.stopPropagation()
                          onSetProjectSpecs?.(p.id, activeSpecCodes)
                        }}
                        title={`把当前限定的 ${activeSpecCodes.length} 部规范存为本项目默认范围`}
                        aria-label="存为本项目规范范围"
                      >
                        ⛬存
                      </button>
                    )}
                    <button
                      className="cn-hist-del"
                      onClick={(e) => {
                        e.stopPropagation()
                        onDeleteProject?.(p.id)
                      }}
                      aria-label={`删除项目：${p.name}（其下会话保留）`}
                    >
                      ×
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="cn-side-section">
          <div className="cn-side-section-title">
            <span>{activeProjectId ? '本项目会话' : '历史会话'}</span>
            <span style={{ fontSize: 10 }}>{visibleConversations.length}</span>
          </div>
          {visibleConversations.length === 0 ? (
            <div className="cn-hist-empty">
              {activeProjectId ? '本项目暂无会话 · 在此提问自动归入该项目' : '暂无历史 · 提问后自动保存到本地'}
            </div>
          ) : (
            <div>
              {(showAllHistory ? visibleConversations : visibleConversations.slice(0, HISTORY_PREVIEW_N)).map((c) => (
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
              {visibleConversations.length > HISTORY_PREVIEW_N && (
                <button
                  className="cn-hist-more"
                  onClick={() => setShowAllHistory((v) => !v)}
                >
                  {showAllHistory
                    ? '收起 ↑'
                    : `查看全部 (${visibleConversations.length}) →`}
                </button>
              )}
            </div>
          )}
        </div>
          </>
        )}
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
