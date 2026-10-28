import type { UIComponentSpec } from './uiPlan'

export type MessageRole = 'user' | 'assistant' | 'system'

export type MessageStatus = 'pending' | 'streaming' | 'complete' | 'error' | 'cancelled'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  components?: UIComponentSpec[]
  status?: MessageStatus
  statusMessage?: string
  error?: string
  timestamp: number
}

export interface SSEStartData {
  event?: 'start'
  message_id: string
  model?: string
}

export interface SSEStatusData {
  event?: 'status'
  status: string
}

export interface SSETokenData {
  event?: 'token'
  delta: string
}

export interface SSEUIComponentData {
  event?: 'ui_component'
  component: UIComponentSpec
  block_id: string
}

export interface SSEDoneData {
  event?: 'done'
  finish_reason: string
}

export interface SSEErrorData {
  event?: 'error'
  message: string
}

export type SSEPayload =
  | SSEStartData
  | SSEStatusData
  | SSETokenData
  | SSEUIComponentData
  | SSEDoneData
  | SSEErrorData
  | Record<string, unknown>

export interface SSEEvent {
  event: string
  data: SSEPayload
  raw?: string
}

export interface StreamChatOptions {
  messages: Array<{ role: MessageRole; content: string }>
  model?: string
  temperature?: number
  signal?: AbortSignal
  onStart?: (data: SSEStartData) => void
  onStatus?: (status: string) => void
  onToken?: (delta: string) => void
  onUIComponent?: (component: UIComponentSpec) => void
  onDone?: (data: SSEDoneData) => void
  onError?: (error: string) => void
}
