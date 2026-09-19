export type User = {
  id: string
  email: string
  display_name: string
  tenant_id: string
}

export type TokenPair = {
  access_token: string
  refresh_token: string
  expires_in: number
  user: User
}

export type Run = {
  id: string
  conversation_id?: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | string
  error?: string | null
}

export type Conversation = {
  id: string
  title: string
  active_run: Run | null
  updated_at: string
  created_at: string
}

export type Message = {
  id: string
  conversation_id: string
  run_id?: string | null
  role: 'user' | 'assistant' | 'system' | string
  content: string
  created_at: string
}

export type List<T> = {
  items: T[]
  next_before: string | null
}

export type AgentEvent = {
  v?: number
  run_id?: string
  conversation_id?: string
  seq: number
  type: string
  payload?: Record<string, unknown>
  ts?: string
}
