import type { ChatMessage, ChatOutgoingAttachment } from '@/types'

import { apiFetch, getApiBaseUrl } from './client'

const CHAT_PATH = '/api/v1/agent/chat'

export interface SendChatPayload {
  message: string
  history: ChatMessage[]
  attachments?: ChatOutgoingAttachment[]
}

export interface SendChatResponse {
  reply: string
}

/**
 * Send a user message to the retail agent.
 *
 * Backend contract (planned):
 * - Method: POST application/json, or multipart/form-data when images are attached
 * - JSON body: { message: string, history: ChatMessage[] }
 * - Multipart fields: message, history, images[]
 * - Response JSON: { reply: string }
 *
 * Until the backend exists this returns an empty reply.
 */
export async function sendChatMessage(payload: SendChatPayload): Promise<SendChatResponse> {
  if (!getApiBaseUrl()) {
    return { reply: 'Backend is not configured. Set VITE_API_BASE_URL to enable agent replies.' }
  }

  const hasAttachments = (payload.attachments?.length ?? 0) > 0
  const response = hasAttachments
    ? await apiFetch(CHAT_PATH, {
        method: 'POST',
        body: buildMultipartPayload(payload),
      })
    : await apiFetch(CHAT_PATH, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: payload.message,
          history: payload.history,
        }),
      })

  return (await response.json()) as SendChatResponse
}

function buildMultipartPayload(payload: SendChatPayload): FormData {
  const body = new FormData()
  body.append('message', payload.message)
  body.append('history', JSON.stringify(payload.history))

  for (const attachment of payload.attachments ?? []) {
    body.append('images', attachment.file, attachment.name)
  }

  return body
}
