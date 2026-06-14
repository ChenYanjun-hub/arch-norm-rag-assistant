// 左侧导航栏（cn-app 设计语言 · 深绿色文档感）
// 规范分类计数从 GET /api/stats 动态读取（接口未就绪时回退默认值）

import type { CorpusStats } from '../types/chat'

interface Props {
  onNewChat?: () => void
  /** 语料统计（动态计数）；null 时用回退默认值 */
  stats?: CorpusStats | null
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

// 接口未就绪时的回退（与入库实测一致），避免首屏闪空
const FALLBACK_DOMAINS = [
  { domain: '规划', spec_count: 18 },
  { domain: '建筑', spec_count: 11 },
  { domain: '景观', spec_count: 7 },
  { domain: '消防', spec_count: 3 },
]

export function Sidebar({ onNewChat, stats }: Props) {
  const domains = stats?.domains ?? FALLBACK_DOMAINS
  const totalSpecs = stats?.total_specs ?? 39

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
            {domains.map((t) => (
              <div key={t.domain} className="cn-side-item">
                <span
                  className={`cn-tag-dot cn-cat-${DOMAIN_CAT[t.domain] ?? 'arch'}`}
                  style={{ width: 8, height: 8, borderRadius: 2 }}
                />
                <span style={{ fontWeight: 500 }}>{t.domain}</span>
                <span className="cn-side-meta">{t.spec_count}</span>
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
