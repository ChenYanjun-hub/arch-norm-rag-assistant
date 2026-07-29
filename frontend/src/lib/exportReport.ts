// 导出查询报告（W7）
//
// 产品判断：报告的核心价值是**可追溯**——规划师要把结论放进设计说明/方案文本，
// 审图时必须能指回"这条依据是哪部规范第几条第几页、现在还有没有效"。
// 所以引用清单里规范全称 / 标准号 / 条文号 / 页码 / 强制性 / 现行状态一个都不能少。
//
// 格式选 Markdown：零新增依赖、可直接粘进 Word/飞书/Notion。
// （Word/PDF 需引入第三方库，按 CLAUDE.md G.1 需先请示，暂不做。）

import type { ChatMessage, Citation, Conversation, Project } from '../types/chat'

/** 文件名安全化：去掉路径分隔符与特殊字符 */
function safeFileName(s: string): string {
  return s.replace(/[\\/:*?"<>|\n\r]/g, '').slice(0, 40) || '规范查询报告'
}

function fmtDateTime(ts: number): string {
  const d = new Date(ts || Date.now())
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 单条引用 → Markdown 条目（可追溯所需字段全带上）*/
function citationToMd(c: Citation, i: number): string {
  const tags: string[] = []
  if (c.is_mandatory) tags.push('**强制性条文**')
  // 公式 OCR 易损：报告里也要标，否则交付物丢了这条风险提示
  if (c.has_formula) tags.push('含计算公式（摘引可能不完整，请核对原文 PDF）')
  const status = c.status ?? '现行'
  if (status !== '现行') {
    tags.push(`⚠️ **${status}**${c.replaced_by ? `，现行替代：${c.replaced_by}` : ''}`)
  }
  const head = `${i}. 《${c.spec_name}》${c.spec_code} ${c.clause}`
  const meta = [
    c.page ? `第 ${c.page} 页` : '',
    c.domain ? `${c.domain}域` : '',
    ...tags,
  ]
    .filter(Boolean)
    .join(' · ')
  const quote = (c.original_text || '').trim().replace(/\n+/g, ' ')
  return [
    head,
    meta ? `   - ${meta}` : '',
    quote ? `   - 原文摘引：“${quote}”` : '',
    c.status_note ? `   - 状态说明：${c.status_note}` : '',
  ]
    .filter(Boolean)
    .join('\n')
}

/** 把一段会话渲染成 Markdown 报告 */
export function buildReportMarkdown(
  conv: Conversation,
  opts: { project?: Project | null } = {},
): string {
  const lines: string[] = []
  const { project } = opts

  lines.push(`# 规范查询报告 · ${conv.title}`)
  lines.push('')
  lines.push(`- 生成时间：${fmtDateTime(Date.now())}`)
  lines.push(`- 会话时间：${fmtDateTime(conv.createdAt)}`)
  if (project) {
    lines.push(`- 所属项目：${project.name}${project.city ? `（${project.city}）` : ''}`)
    if (project.specCodes.length) {
      lines.push(`- 项目规范范围：${project.specCodes.join('、')}`)
    }
  }
  lines.push('- 生成工具：建景规·助手（AI 检索生成，非官方发布物）')
  lines.push('')
  lines.push('---')
  lines.push('')

  // 逐轮问答
  const pairs: { q: ChatMessage; a?: ChatMessage }[] = []
  for (let i = 0; i < conv.messages.length; i++) {
    const m = conv.messages[i]
    if (m.role !== 'user') continue
    const next = conv.messages[i + 1]
    pairs.push({ q: m, a: next?.role === 'assistant' ? next : undefined })
  }

  pairs.forEach(({ q, a }, idx) => {
    lines.push(`## ${idx + 1}. ${q.content.trim()}`)
    lines.push('')
    if (!a || a.error) {
      lines.push(a?.error ? `> 该轮生成失败：${a.error}` : '> 该轮无回答')
      lines.push('')
      return
    }
    lines.push(a.content.trim())
    lines.push('')

    const cites = a.citations ?? []
    if (cites.length) {
      lines.push(`### 依据条文（${cites.length} 条）`)
      lines.push('')
      cites.forEach((c, i) => lines.push(citationToMd(c, i + 1)))
      lines.push('')
      // 含已废止规范时显式提示——审图会看这个
      const deprecated = cites.filter((c) => c.status && c.status !== '现行')
      if (deprecated.length) {
        lines.push(
          `> ⚠️ 本轮引用中含 ${deprecated.length} 条非现行规范，引用前请核对现行版本。`,
        )
        lines.push('')
      }
    }

    // 引用核验发现的待核项：属于"必须随报告一起交付"的风险信息
    const issues = a.meta?.grounding_issues ?? []
    if (a.meta?.grounding_verified && !a.meta.grounding_ok && issues.length) {
      lines.push(`> ⚑ 自动核验提示（${issues.length} 项待人工确认）：`)
      issues.forEach((s) => lines.push(`> - ${s}`))
      lines.push('')
    }
  })

  lines.push('---')
  lines.push('')
  lines.push(
    '**免责声明**：本报告由 AI 检索规范库生成，引用条文以官方现行版本为准。' +
      '内容仅供设计参考，不构成合规结论；具体合规判定请咨询规划主管部门或专业审图机构。',
  )
  lines.push('')
  return lines.join('\n')
}

/** 触发浏览器下载（纯前端，无需后端）*/
export function downloadReport(conv: Conversation, project?: Project | null): void {
  const md = buildReportMarkdown(conv, { project })
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${safeFileName(conv.title)}_规范查询报告.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // 立即 revoke 在部分浏览器会打断下载，延后释放
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
