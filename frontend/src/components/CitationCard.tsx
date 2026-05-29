// 引用卡片：展示单条规范引用（CLAUDE.md 红线 2 P0 要素）

import type { Citation } from '../types/chat'

interface Props {
  index: number
  citation: Citation
}

export function CitationCard({ index, citation }: Props) {
  const { spec_name, spec_code, clause, page, is_mandatory, original_text, domain } =
    citation

  const clauseDisp = clause.startsWith('表') || clause.startsWith('式')
    ? clause
    : `第 ${clause} 条`

  return (
    <div className="border border-gray-200 rounded-md bg-white p-3 text-sm">
      <div className="flex items-baseline gap-2 mb-1.5 flex-wrap">
        <span className="font-mono text-xs text-gray-500">[{index}]</span>
        <span className="font-semibold text-gray-900">《{spec_name}》</span>
        <span className="font-mono text-xs text-gray-600">{spec_code}</span>
        <span className="text-gray-700">{clauseDisp}</span>
        {page !== null && (
          <span className="text-xs text-gray-500">第 {page} 页</span>
        )}
        {is_mandatory && (
          <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-red-50 text-red-700 border border-red-200">
            强制性
          </span>
        )}
        {domain && (
          <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-blue-50 text-blue-700 border border-blue-200">
            {domain}
          </span>
        )}
      </div>
      <p className="text-gray-700 leading-relaxed whitespace-pre-wrap line-clamp-3">
        {original_text}
      </p>
    </div>
  )
}
