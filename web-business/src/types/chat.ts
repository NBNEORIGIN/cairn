export interface SessionSummary {
  session_id: string
  title: string
  preview: string
  last_message_at: string
  started_at: string
  message_count: number
  archived: boolean
  subproject_id: string | null
}

export interface SessionMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  model_used?: string
  tokens_used?: number
  cost_usd?: number
  timestamp: string
}

export interface SessionDetail {
  session_id: string
  subproject_id: string | null
  estimated_tokens: number
  skill_ids: string[]
  archived: boolean
  messages: SessionMessage[]
}
