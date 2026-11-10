export type User = {
  id: string
  email: string
  created_at: string
}

export type TokenPair = {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export type Run = {
  id: string
  conversation_id: string
  status: 'queued' | 'running' | 'cancelling' | 'succeeded' | 'failed' | 'cancelled'
  attempt_count: number
  created_at: string
}

export type Conversation = {
  id: string
  title: string
  active_run?: Run | null
  updated_at: string
  created_at: string
}

export type Message = {
  id: string
  conversation_id: string
  run_id: string
  role: 'user' | 'assistant'
  content: string
  attachments: Attachment[]
  created_at: string
}

export type Attachment = {
  id: string
  filename: string
  content_type: string
  size_bytes: number
}

export type List<T> = {
  items: T[]
  next_cursor: string | null
}

export type MessageAccepted = {
  run_id: string
  message_id: string
  status: Run['status']
}

export type AgentEvent = {
  seq: number
  type: string
  payload: Record<string, unknown>
}
