// 类型定义：与后端 schemas.py 保持一致

/** 引用元数据（对应后端 Citation） */
export interface Citation {
  spec_name: string
  spec_code: string
  clause: string
  page: number | null
  is_mandatory: boolean
  original_text: string
  domain: string
}

/** 检索元信息（pipeline 第一个事件） */
export interface RetrievalMeta {
  n_candidates: number
  n_kept: number
  min_relevance: number
}

/** 性能元信息（done 事件载荷） */
export interface DoneMeta {
  ttft_ms: number
  total_ms: number
  tokens_out: number
}

/** SSE 事件类型 */
export type SSEEventType =
  | 'retrieval'
  | 'token'
  | 'citations'
  | 'fallback'
  | 'done'
  | 'error'

export type SSEEvent =
  | { type: 'retrieval'; data: RetrievalMeta }
  | { type: 'token'; data: string }
  | { type: 'citations'; data: Citation[] }
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
  /** assistant 消息流式中 */
  streaming?: boolean
}

/** chat 请求体 */
export interface ChatRequest {
  query: string
  session_id?: string
  domain?: string
  spec_code?: string
}
