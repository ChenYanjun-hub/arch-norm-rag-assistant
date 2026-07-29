// 问答主页面（三栏布局 · 设计参考 claude design/pc-mock.jsx）

import { useEffect, useRef, useState } from 'react'
import { useChatStore, useActiveMessages } from '../stores/chatStore'
import { ChatMessage } from '../components/ChatMessage'
import { Sidebar } from '../components/Sidebar'
import { RightPanel } from '../components/RightPanel'
import { InputBar } from '../components/InputBar'
import { getStats } from '../lib/apiClient'
import { downloadReport } from '../lib/exportReport'
import type { Citation, CorpusStats, SpecBrief } from '../types/chat'

// 示例池（覆盖 6 域）；空态每次随机抽 N 条展示
const SAMPLE_QUERIES = [
  // 规划
  '居住区配套幼儿园的服务半径不应大于多少米？',
  '居住区人均公共绿地面积的最低要求？',
  '居住区配套设施的设置规定有哪些？',
  // 建筑
  '幼儿园建筑的活动单元应如何布置？',
  '住宅卧室的最小使用面积是多少？',
  '养老设施居室的使用面积要求？',
  // 景观
  '城市道路绿化的种植设计标准？',
  '城市公园绿地的服务半径要求？',
  // 消防
  '防火墙的耐火极限要求是多少？',
  '高层建筑消防车道的宽度要求？',
  '安全出口的疏散距离规定？',
  // 市政
  '城市综合管廊内天然气管道如何敷设？',
  '城市道路照明的评价指标有哪些？',
  // 结构
  '建筑抗震设防烈度如何确定？',
]

/**
 * 按标准层级归类本次回答引用了哪些规范（国标 / 行标 / 地标）。
 * 层级来自 spec_code 前缀：GB=国标，JGJ/CJJ/WW/建标=行标，DB=地标。
 * 同一部规范被引多条只计 1 部。
 */
function summarizeCitationTiers(cites: Citation[]): { label: string; count: number }[] {
  const tierOf = (code: string): string => {
    const c = (code || '').replace(/\s/g, '').toUpperCase()
    if (c.startsWith('DB')) return '地标'
    if (c.startsWith('GB')) return '国标'
    return '行标'
  }
  const seen = new Map<string, Set<string>>()
  for (const c of cites) {
    const t = tierOf(c.spec_code)
    if (!seen.has(t)) seen.set(t, new Set())
    seen.get(t)!.add((c.spec_code || '').replace(/\s/g, '').toUpperCase())
  }
  // 固定顺序：国标 → 行标 → 地标（效力从高到低）
  return ['国标', '行标', '地标']
    .filter((t) => seen.has(t))
    .map((t) => ({ label: t, count: seen.get(t)!.size }))
}

/** 相对时间：刚刚 / N 分钟前 / HH:MM / 昨天 */
function formatRelTime(ts: number): string {
  if (!ts) return ''
  const diffMin = Math.floor((Date.now() - ts) / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const d = new Date(ts)
  const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const dayDiff = Math.round((startOfDay(new Date()) - startOfDay(d)) / 86400000)
  const hhmm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return dayDiff === 0 ? hhmm : dayDiff === 1 ? '昨天' : `${d.getMonth() + 1}月${d.getDate()}日`
}

/** 从示例池随机抽 n 条（空态每次进入 / 点"换一批"重抽）*/
function pickSamples(n = 4): string[] {
  return [...SAMPLE_QUERIES].sort(() => Math.random() - 0.5).slice(0, n)
}

export function ChatPage() {
  const messages = useActiveMessages()
  const conversations = useChatStore((s) => s.conversations)
  const activeId = useChatStore((s) => s.activeId)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const send = useChatStore((s) => s.send)
  const newConversation = useChatStore((s) => s.newConversation)
  const switchConversation = useChatStore((s) => s.switchConversation)
  const deleteConversation = useChatStore((s) => s.deleteConversation)
  // W7 项目工作区
  const projects = useChatStore((s) => s.projects)
  const activeProjectId = useChatStore((s) => s.activeProjectId)
  const selectProject = useChatStore((s) => s.selectProject)
  const createProject = useChatStore((s) => s.createProject)
  const deleteProject = useChatStore((s) => s.deleteProject)
  const setProjectSpecs = useChatStore((s) => s.setProjectSpecs)

  const [activeCite, setActiveCite] = useState<number | null>(null)
  const [stats, setStats] = useState<CorpusStats | null>(null)
  // 点侧栏规范 → 多选限定只查这些规范（接通已有 spec_code 检索能力）
  const [specFilters, setSpecFilters] = useState<SpecBrief[]>([])
  const toggleSpec = (sp: SpecBrief) =>
    setSpecFilters((prev) =>
      prev.some((s) => s.spec_code === sp.spec_code)
        ? prev.filter((s) => s.spec_code !== sp.spec_code)
        : [...prev, sp],
    )
  const scrollRef = useRef<HTMLDivElement>(null)

  // 拉规范库语料统计（动态计数）；失败则各组件回退默认值
  useEffect(() => {
    getStats()
      .then(setStats)
      .catch(() => {
        /* 接口未就绪：Sidebar/顶栏用回退默认值，不阻塞 UI */
      })
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages])

  // 新一轮对话开始 / 切换会话时清空 activeCite
  useEffect(() => {
    setActiveCite(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, activeId])

  // ⌘N / Ctrl+N 新建对话（侧栏已标注该快捷键）
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'n' || e.key === 'N')) {
        e.preventDefault()
        newConversation()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [newConversation])

  function handleSubmit(q: string) {
    if (!q.trim() || isStreaming) return
    void send(
      q,
      specFilters.length ? { spec_codes: specFilters.map((s) => s.spec_code) } : undefined,
    )
  }

  // 最新一条 assistant 消息的引用 → 右栏
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const citations: Citation[] = lastAssistant?.citations ?? []
  const lastAssistantId = lastAssistant?.id ?? null

  // 本次回答时间：消息无时间戳，用当前会话 updatedAt（每次消息更新都会刷新，口径准确）
  const activeConv = conversations.find((c) => c.id === activeId)
  const lastAnswerAt = activeConv?.updatedAt ?? 0

  // 顶栏项目标签：已有会话看它归属哪个项目；空态看当前选中的项目
  const currentProject = projects.find(
    (p) => p.id === (activeConv ? activeConv.projectId : activeProjectId),
  )

  const userQueryTitle =
    [...messages].reverse().find((m) => m.role === 'user')?.content?.slice(0, 50) ??
    '建景规·助手 — 设计规范智能查询'

  // 规范库覆盖（动态计数，接口未就绪时回退）
  const coverageDomains =
    stats?.domains.map((d) => d.domain).join(' / ') ?? '规划 / 建筑 / 景观 / 消防'
  const domainCount = stats?.domain_count ?? 4
  const totalSpecs = stats?.total_specs ?? 39
  const totalChunks = stats?.total_chunks ?? 4773

  return (
    <div
      className="cn-app"
      style={{
        display: 'flex',
        height: '100%',
        width: '100%',
        overflow: 'hidden',
      }}
    >
      <Sidebar
        onNewChat={newConversation}
        stats={stats}
        projects={projects}
        activeProjectId={activeProjectId}
        onSelectProject={selectProject}
        onCreateProject={createProject}
        onDeleteProject={deleteProject}
        onSetProjectSpecs={setProjectSpecs}
        conversations={conversations}
        activeId={activeId}
        onSelectConversation={switchConversation}
        onDeleteConversation={deleteConversation}
        onSelectSpec={toggleSpec}
        activeSpecCodes={specFilters.map((s) => s.spec_code)}
      />

      <main
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
          background: 'var(--bg)',
        }}
      >
        {/* 顶栏 */}
        <div className="cn-topbar">
          <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.3, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <span
                className="cn-topbar-title"
                style={{
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  maxWidth: 600,
                }}
              >
                {userQueryTitle}
              </span>
              <span className="cn-topbar-pill">
                <span
                  style={{
                    width: 5,
                    height: 5,
                    borderRadius: 50,
                    background: 'currentColor',
                  }}
                />
                MVP 体验
              </span>
              {/* W7：当前会话所属项目（会话已归档时看会话的，空态看当前选中的）*/}
              {currentProject && (
                <span
                  className="cn-topbar-pill cn-proj-pill"
                  title={
                    currentProject.specCodes.length
                      ? `项目「${currentProject.name}」· 已预设 ${currentProject.specCodes.length} 部规范限定`
                      : `项目「${currentProject.name}」`
                  }
                >
                  <span
                    style={{ width: 5, height: 5, borderRadius: 50, background: 'currentColor' }}
                  />
                  {currentProject.name}
                </span>
              )}
            </div>
            <div className="cn-topbar-sub">
              {citations.length > 0 ? (
                // 有答案时：显示「本次回答」的引用构成（比全局语料统计更有信息量）
                <>
                  <span style={{ fontFamily: 'var(--font-mono)' }}>{citations.length}</span>{' '}
                  条引用
                  {summarizeCitationTiers(citations).map((t, i) => (
                    <span key={t.label}>
                      {i === 0 ? ' · 涉及' : ' · '}
                      {t.label}{' '}
                      <span style={{ fontFamily: 'var(--font-mono)' }}>{t.count}</span> 部
                    </span>
                  ))}
                  {lastAnswerAt ? ` · ${formatRelTime(lastAnswerAt)}` : ''}
                </>
              ) : (
                // 空态：显示全局语料覆盖（让用户知道能查什么）
                <>
                  覆盖{coverageDomains} {domainCount} 类 · {totalSpecs} 部规范 ·{' '}
                  {totalChunks} 条条文
                </>
              )}
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
            {/* W7 导出报告：把可追溯引用变成可交付物（Markdown，可粘进设计说明）*/}
            {activeConv && messages.length > 0 && (
              <button
                className="cn-msg-tool"
                style={{ padding: '6px 10px' }}
                onClick={() => downloadReport(activeConv, currentProject ?? null)}
                disabled={isStreaming}
                title="导出为 Markdown 报告（含规范号、条文号、页码、原文摘引，可粘进设计说明）"
              >
                ↓ 导出报告
              </button>
            )}
            {messages.length > 0 && (
              <button
                className="cn-msg-tool"
                style={{ padding: '6px 10px' }}
                onClick={newConversation}
                disabled={isStreaming}
              >
                新建对话
              </button>
            )}
          </div>
        </div>

        {/* 消息列表 */}
        <div
          ref={scrollRef}
          className="cn-scroll"
          style={{
            flex: 1,
            padding: '24px 28px 0',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div style={{ maxWidth: 760, width: '100%', margin: '0 auto', minHeight: '100%' }}>
            {messages.length === 0 ? (
              <EmptyState onPick={handleSubmit} coverage={`${coverageDomains} ${domainCount} 类`} />
            ) : (
              messages.map((m) => (
                <ChatMessage
                  key={m.id}
                  message={m}
                  activeCite={m.id === lastAssistantId ? activeCite : null}
                  onCiteClick={
                    m.id === lastAssistantId ? (n) => setActiveCite(n) : undefined
                  }
                  inlineCitations={m.id === lastAssistantId ? citations : undefined}
                  onFollowUp={m.id === lastAssistantId ? handleSubmit : undefined}
                />
              ))
            )}
          </div>
        </div>

        {/* 输入栏 */}
        <div style={{ maxWidth: 880, width: '100%', margin: '0 auto', alignSelf: 'center' }}>
          <InputBar
            disabled={isStreaming}
            onSubmit={handleSubmit}
            specFilters={specFilters}
            onRemoveFilter={(code) =>
              setSpecFilters((prev) => prev.filter((s) => s.spec_code !== code))
            }
            onClearFilter={() => setSpecFilters([])}
          />
        </div>
      </main>

      <RightPanel
        citations={citations}
        activeIndex={activeCite}
        onActiveChange={setActiveCite}
        meta={lastAssistant?.meta}
      />
    </div>
  )
}

function EmptyState({
  onPick,
  coverage,
}: {
  onPick: (q: string) => void
  coverage: string
}) {
  // 每次挂载（进空态/新建对话）随机抽一批；"换一批"可手动重抽
  const [picks, setPicks] = useState<string[]>(pickSamples)
  return (
    <div style={{ textAlign: 'center', padding: '60px 8px' }}>
      <div className="cn-brand-mark-lg" style={{ marginBottom: 18 }} aria-label="品牌标识">
        同
      </div>
      <h2
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 22,
          color: 'var(--ink)',
          margin: '0 0 6px',
          letterSpacing: '0.02em',
        }}
      >
        像查法条一样查规范
      </h2>
      <p
        style={{
          fontSize: 13.5,
          color: 'var(--ink-mute)',
          margin: '0 auto 26px',
          maxWidth: 460,
          lineHeight: 1.7,
        }}
      >
        覆盖{coverage}设计规范<br />
        所有答案附规范号 + 条文号 + 原文引用，可追溯、不编造
      </p>

      <div
        style={{
          maxWidth: 560,
          margin: '0 auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 2,
          }}
        >
          <span
            style={{
              fontSize: 11,
              color: 'var(--ink-faint)',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
            }}
          >
            试试这些示例
          </span>
          <button
            onClick={() => setPicks(pickSamples())}
            title="换一批示例"
            style={{
              fontSize: 11,
              color: 'var(--ink-faint)',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              fontFamily: 'inherit',
              padding: '2px 4px',
              transition: 'color .14s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--primary)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--ink-faint)')}
          >
            换一批 ↻
          </button>
        </div>
        {picks.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            style={{
              textAlign: 'left',
              fontSize: 13.5,
              color: 'var(--ink-soft)',
              background: 'var(--paper)',
              border: '1px solid var(--border)',
              borderRadius: 10,
              padding: '11px 14px',
              cursor: 'pointer',
              transition: 'all .14s',
              fontFamily: 'inherit',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--primary-soft)'
              e.currentTarget.style.borderColor = 'var(--primary-line)'
              e.currentTarget.style.color = 'var(--primary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'var(--paper)'
              e.currentTarget.style.borderColor = 'var(--border)'
              e.currentTarget.style.color = 'var(--ink-soft)'
            }}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
