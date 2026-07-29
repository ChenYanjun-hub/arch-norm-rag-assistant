// 类型定义：与后端 schemas.py 保持一致

/** 引用元数据（对应后端 Citation） */
/** 规范现行状态（4 态，对应后端 spec_status + 前端徽章）*/
export type SpecStatus = '现行' | '已废止' | '局部废止' | '即将实施'

export interface Citation {
  spec_name: string
  spec_code: string
  clause: string
  page: number | null
  is_mandatory: boolean
  /** W7：本条含计算公式 —— 公式 OCR 普遍损坏，不渲染，提示看原文 PDF */
  has_formula?: boolean
  original_text: string
  domain: string
  /** 规范现行状态（缺省视为"现行"）*/
  status?: SpecStatus
  /** 若已废止/被替代：现行替代标准号 */
  replaced_by?: string | null
  /** 状态补充说明（废止/施行日期等）*/
  status_note?: string | null
}

/** 检索元信息（pipeline 第一个事件） */
export interface RetrievalMeta {
  n_candidates: number
  n_kept: number
  min_relevance: number
  /** W7 agent①：本轮是否走了查询分解（复合/发散题拆子问题各自检索）*/
  decomposed?: boolean
  /** W7 agent①：拆出的子问题（供 UI 展示"拆成了哪几问"）*/
  sub_queries?: string[]
}

/** 性能元信息（done 事件载荷） */
export interface DoneMeta {
  ttft_ms: number
  total_ms: number
  tokens_out: number
}

/** W5 D4 + W6 D2 + W6 D4 + W7 D1：pipeline 元数据（dangling + post_filter 矩阵 3 层） */
export interface PipelineMeta {
  /** 下列三项仅常规 RAG 路径下发；工具 Agent 路径不检索，故为可选 */
  dangling_count?: number
  n_citations_in_answer?: number
  n_chunks_available?: number
  post_filter_stripped_chars?: number
  post_filter_applied?: boolean
  /** W6 D4：量词对齐校正次数（"宜/应/不应"被改回 chunks 原词的次数）*/
  modal_verb_corrections?: number
  /** W7 D1：数字对齐校正次数（"300m/35%"被改回 chunks 原值的次数）*/
  number_corrections?: number
  /** W7 agent②：引用核验 verifier 是否成功跑了（失败/超时为 false）*/
  grounding_verified?: boolean
  /** W7 agent②：核验结论 —— 答案里规范号/条文号/数字是否全部有据 */
  grounding_ok?: boolean
  /** W7 agent②：无据（疑似编造）项摘录 */
  grounding_issues?: string[]
  /** W7 agent③：本轮是否由工具调用 Agent 作答（查表/元信息类查询）*/
  tool_agent_used?: boolean
  /** W7 agent③：实际调用的工具名 */
  tool_calls?: string[]
}

/** SSE 事件类型 */
export type SSEEventType =
  | 'retrieval'
  | 'token'
  | 'citations'
  | 'metadata'
  | 'revised_answer'
  | 'follow_ups'
  | 'fallback'
  | 'done'
  | 'error'

export type SSEEvent =
  | { type: 'retrieval'; data: RetrievalMeta }
  | { type: 'token'; data: string }
  | { type: 'citations'; data: Citation[] }
  | { type: 'metadata'; data: PipelineMeta }
  | { type: 'revised_answer'; data: string }
  | { type: 'follow_ups'; data: string[] }
  | { type: 'fallback'; data: string }
  | { type: 'done'; data: DoneMeta }
  | { type: 'error'; data: string }

/** 单条消息（UI 展示用） */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  retrieval?: RetrievalMeta
  done?: DoneMeta
  fallback?: string
  error?: string
  /** W6 D2：pipeline 元数据（dangling / post_filter 状态） */
  meta?: PipelineMeta
  /** W6 D2：post_filter 触发时 LLM 原始回答（剥离前），保留供 debug */
  rawContent?: string
  /** V2-1：智能追问推荐（点击即作为新 query 发送）*/
  followUps?: string[]
  /** assistant 消息流式中 */
  streaming?: boolean
}

/** V2 多轮：单轮历史 */
export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

/**
 * W7：项目工作区 —— 规划师按项目组织查询。
 * 项目不只是分组标签，更是**预设的规范过滤集**：
 * 同一个问题在深圳和在哈尔滨，适用的地标与气候区参数不同。
 */
export interface Project {
  id: string
  name: string
  /** 城市 / 地区（备注用，决定该带哪些地标）*/
  city?: string
  /** 预设规范限定：该项目下提问默认只查这些规范（复用已有 spec_code 多选检索）*/
  specCodes: string[]
  createdAt: number
}

/** V2-3：一段完整会话（localStorage 持久化单元）*/
export interface Conversation {
  id: string
  /** 标题（取首条用户问题前若干字）*/
  title: string
  messages: ChatMessage[]
  createdAt: number
  updatedAt: number
  /** W7：所属项目（新建会话时继承当前选中项目）；null/缺省 = 未归档到任何项目 */
  projectId?: string | null
}

/** chat 请求体 */
export interface ChatRequest {
  query: string
  session_id?: string
  domain?: string
  /** 多选条文限定：命中任一即可 */
  spec_codes?: string[]
  /** V2-2 多轮：最近 N 轮历史（前端传，后端做指代消解）*/
  history?: ChatTurn[]
}

/** 规范清单项（对应后端 SpecBrief）— 侧栏展开/点选导航 */
export interface SpecBrief {
  spec_code: string
  spec_name: string
  status: SpecStatus
}

/** 单域统计（对应后端 DomainStat） */
export interface DomainStat {
  domain: string
  spec_count: number
  chunk_count: number
  /** 该域规范清单（按标准号排序）*/
  specs?: SpecBrief[]
}

/** 语料统计（对应后端 CorpusStats，GET /api/stats）— 前端动态计数 */
export interface CorpusStats {
  total_specs: number
  total_chunks: number
  domain_count: number
  domains: DomainStat[]
}
