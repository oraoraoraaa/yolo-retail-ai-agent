export type ChatRole = 'user' | 'assistant' | 'system'

export interface ChatAttachment {
  id: string
  name: string
  type: string
  size: number
  previewUrl?: string
}

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  createdAt: string
  attachments?: ChatAttachment[]
}

export interface ChatOutgoingAttachment extends ChatAttachment {
  file: File
}

export type ChatRequestStatus = 'idle' | 'sending' | 'error'

/** One persisted agent conversation (local browser history). */
export interface ChatSession {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  messages: ChatMessage[]
}

export interface ChatPanelState {
  sessions: ChatSession[]
  activeSessionId: string | null
  messages: ChatMessage[]
  status: ChatRequestStatus
  errorMessage: string | null
}
