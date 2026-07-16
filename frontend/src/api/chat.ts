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
/** Demo Markdown used when the backend is not configured, so the UI can be verified. */
const STUB_MARKDOWN_REPLY = `## 巡检摘要

当前为 **本地 stub** 回复（未配置 \`VITE_API_BASE_URL\`）。接入后端后会显示真实 Agent 输出。

### 建议动作
1. 优先补货 **Brand Y Soda**
2. 核对货架坐标 \`(X:12, Y:45)\` 与 planogram
3. 通知门店员工回库取货

### 观察
- 检测到 **空位（gap）**
- 相邻 SKU 陈列正常
- 暂无明显错放
`

export async function sendChatMessage(payload: SendChatPayload): Promise<SendChatResponse> {
  if (!getApiBaseUrl()) {
    return { reply: STUB_MARKDOWN_REPLY }
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
