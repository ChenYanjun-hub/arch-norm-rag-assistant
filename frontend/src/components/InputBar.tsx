// 底部输入栏（cn-input-shell 设计语言）
// 设计参考：claude design/pc-mock.jsx · InputBar

import { useState } from 'react'

interface Props {
  disabled?: boolean
  onSubmit: (query: string) => void
}

export function InputBar({ disabled, onSubmit }: Props) {
  const [value, setValue] = useState('')

  const send = () => {
    if (!value.trim() || disabled) return
    onSubmit(value)
    setValue('')
  }

  return (
    <div style={{ padding: '14px 28px 22px', background: 'linear-gradient(180deg, transparent, var(--bg) 30%)' }}>
      <div className="cn-input-shell">
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
