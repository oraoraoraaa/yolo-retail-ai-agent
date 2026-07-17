import type { ChatMessage, ChatOutgoingAttachment } from '@/types'

import type { Language } from '@/lib/i18n'

import { apiFetch, getApiBaseUrl } from './client'

const CHAT_PATH = '/api/v1/agent/chat'

export interface SendChatPayload {
  message: string
  history: ChatMessage[]
  attachments?: ChatOutgoingAttachment[]
  language: Language
}

export interface SendChatResponse {
  reply: string
}

/**
 * Send a user message to the retail agent.
 *
 * Backend contract:
 * - Method: POST application/json, or multipart/form-data when images are attached
 * - JSON body: { message: string, history: ChatMessage[], language: string }
 * - Multipart fields: message, history, language, images[]
 * - Response JSON: { reply: string }
 *
 * When VITE_API_BASE_URL is empty this returns a Markdown stub so the UI
 * remains usable offline. Multipart image attachments are forwarded as real
 * multimodal content by the backend.
 */
/** Demo Markdown used when the backend is not configured, so the UI can be verified. */
const STUB_REPLIES: Record<Language, string> = {
  zh: `## 巡检摘要

当前为 **本地 stub** 回复（未配置 \`VITE_API_BASE_URL\`）。接入后端后会显示真实 Agent 输出。

### 建议动作
1. 优先补货 **Brand Y Soda**
2. 核对货架坐标 \`(X:12, Y:45)\` 与 planogram
3. 通知门店员工回库取货

### 观察
- 检测到 **空位（gap）**
- 相邻 SKU 陈列正常
- 暂无明显错放
`,
  en: `## Audit Summary

This is a **local stub** reply because \`VITE_API_BASE_URL\` is not configured. Once the backend is connected, real agent output will appear here.

### Suggested Actions
1. Prioritize replenishment for **Brand Y Soda**
2. Check shelf coordinate \`(X:12, Y:45)\` against the planogram
3. Ask store staff to pick stock from the backroom

### Observations
- A shelf **gap** was detected
- Adjacent SKUs look normal
- No obvious misplaced item is shown
`,
}

export async function sendChatMessage(payload: SendChatPayload): Promise<SendChatResponse> {
  if (!getApiBaseUrl()) {
    return { reply: STUB_REPLIES[payload.language] }
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
          language: payload.language,
        }),
      })

  return (await response.json()) as SendChatResponse
}

function buildMultipartPayload(payload: SendChatPayload): FormData {
  const body = new FormData()
  body.append('message', payload.message)
  body.append('history', JSON.stringify(payload.history))
  body.append('language', payload.language)

  for (const attachment of payload.attachments ?? []) {
    body.append('images', attachment.file, attachment.name)
  }

  return body
}
