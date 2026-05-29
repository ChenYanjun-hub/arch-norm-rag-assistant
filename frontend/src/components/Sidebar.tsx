// 左侧导航栏（cn-app 设计语言 · 深绿色文档感）
// MVP 阶段：logo + 新建对话 + 静态规范分类占位
// 历史会话 / 项目工作区 / 收藏 / 用户都留占位

interface Props {
  onNewChat?: () => void
}

const TAXONOMY = [
  { id: 'planning', cat: 'planning', label: '规划', count: 18 },
  { id: 'arch', cat: 'arch', label: '建筑', count: 11 },
  { id: 'landscape', cat: 'landscape', label: '景观', count: 7 },
  { id: 'fire', cat: 'arch', label: '消防', count: 3 },
] as const

export function Sidebar({ onNewChat }: Props) {
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
        <div className="cn-logo-mark">建</div>
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
            <span style={{ fontSize: 10 }}>39 部</span>
          </div>
          <div>
            {TAXONOMY.map((t) => (
              <div key={t.id} className="cn-side-item">
                <span
                  className={`cn-tag-dot cn-cat-${t.cat}`}
                  style={{ width: 8, height: 8, borderRadius: 2 }}
                />
                <span style={{ fontWeight: 500 }}>{t.label}</span>
                <span className="cn-side-meta">{t.count}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="cn-side-section">
          <div className="cn-side-section-title">
            <span>历史会话</span>
            <span style={{ fontSize: 10 }}>0</span>
          </div>
          <div style={{ color: 'var(--sidebar-text-mute)', fontSize: 12, padding: '6px 10px' }}>
            暂无历史 · 会话持久化 V2 上线
          </div>
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
