// 底部输入栏（cn-input-shell 设计语言）
// 设计参考：claude design/pc-mock.jsx · InputBar

import { useState } from 'react'

interface Props {
  disabled?: boolean
  onSubmit: (query: string) => void
  /** NAV：当前限定的规范列表（多选，只查这些）；空 = 不限定 */
  specFilters?: { spec_code: string; spec_name: string }[]
  /** 移除单个限定 */
  onRemoveFilter?: (specCode: string) => void
  /** 清空全部限定 */
  onClearFilter?: () => void
}

export function InputBar({
  disabled,
  onSubmit,
  specFilters,
  onRemoveFilter,
  onClearFilter,
}: Props) {
  const [value, setValue] = useState('')

  const send = () => {
    if (!value.trim() || disabled) return
    onSubmit(value)
    setValue('')
  }

  return (
    <div style={{ padding: '14px 28px 22px', background: 'linear-gradient(180deg, transparent, var(--bg) 30%)' }}>
      <div className="cn-input-shell">
        {specFilters && specFilters.length > 0 && (
          <div className="cn-filter-chip">
            <span style={{ opacity: 0.7, flex: '0 0 auto' }}>只查</span>
            <div className="cn-filter-pills">
              {specFilters.map((s) => (
                <span
                  key={s.spec_code}
                  className="cn-filter-pill"
                  title={`${s.spec_name} ${s.spec_code}`}
                >
                  <span className="cn-filter-pill-name">《{s.spec_name}》</span>
                  <button
                    className="cn-filter-pill-x"
                    onClick={() => onRemoveFilter?.(s.spec_code)}
                    aria-label={`移除限定：${s.spec_name}`}
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
            {specFilters.length > 1 && (
              <button
                className="cn-filter-chip-clear"
                onClick={onClearFilter}
                title="清空全部限定，恢复全库检索"
                aria-label="清空全部规范限定"
              >
                清空
              </button>
            )}
          </div>
        )}
        <textarea
          className="cn-input-field"
          rows={2}
          value={value}
          maxLength={500}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          placeholder={
            disabled
              ? '回答中…'
              : specFilters && specFilters.length > 0
                ? `在选定的 ${specFilters.length} 部规范内提问（Enter 发送）`
                : '提出你的规范查询问题（Enter 发送，Shift+Enter 换行）'
          }
        />
        <div className="cn-input-row">
          {/* 路线图占位（功能未上线，禁用态）— 不含范围外的「上传图纸」(见 CLAUDE.md A.2) */}
          <button
            className="cn-input-chip"
            disabled
            aria-disabled="true"
            title="按条文号精准引用 · 规划中"
            style={{ opacity: 0.5, cursor: 'not-allowed' }}
          >
            @ 引用条文
          </button>
          <div style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-faint)' }}>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{value.length}</span> / 500
          </div>
          <button
            className="cn-input-send"
            disabled={!value.trim() || disabled}
            onClick={send}
            title={disabled ? '回答中…' : '发送'}
            aria-label={disabled ? '回答中' : '发送问题'}
          >
            <span style={{ fontSize: 14, lineHeight: 1 }} aria-hidden="true">↑</span>
          </button>
        </div>
      </div>
      <div
        style={{
          fontSize: 11,
          color: 'var(--ink-faint)',
          textAlign: 'center',
          marginTop: 8,
        }}
      >
        引用条文以官方现行版本为准。AI 生成内容仅作参考，最终请以官方文件为准。
      </div>
    </div>
  )
}
