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

export interface ChatPanelState {
  messages: ChatMessage[]
  status: ChatRequestStatus
  errorMessage: string | null
}
