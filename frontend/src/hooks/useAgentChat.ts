import { useRef, useState } from 'react'

import { sendChatMessage } from '@/api'
import { createClientId } from '@/lib/id'
import type { Language } from '@/lib/i18n'
import type { ChatMessage, ChatOutgoingAttachment, ChatPanelState } from '@/types'

const INITIAL_STATE: ChatPanelState = {
  messages: [],
  status: 'idle',
  errorMessage: null,
}

export function useAgentChat() {
  const [state, setState] = useState<ChatPanelState>(INITIAL_STATE)
  const isSendingRef = useRef(false)

  async function sendMessage(
    rawContent: string,
    attachments: ChatOutgoingAttachment[] = [],
    language: Language = 'en',
  ): Promise<void> {
    const content = rawContent.trim()
    if ((!content && attachments.length === 0) || isSendingRef.current || state.status === 'sending') {
      return
    }

    isSendingRef.current = true

    try {
      const userMessage: ChatMessage = {
        id: createClientId('msg'),
        role: 'user',
        content,
        createdAt: new Date().toISOString(),
        attachments: attachments.map((attachment) => ({
          id: attachment.id,
          name: attachment.name,
          type: attachment.type,
          size: attachment.size,
          previewUrl: attachment.previewUrl,
        })),
      }

      const history = [...state.messages, userMessage]

      setState({
        messages: history,
        status: 'sending',
        errorMessage: null,
      })

      const { reply } = await sendChatMessage({
        message: content,
        history,
        attachments,
        language,
      })

      const assistantMessage: ChatMessage = {
        id: createClientId('msg'),
        role: 'assistant',
        content: reply,
        createdAt: new Date().toISOString(),
      }

      setState({
        messages: [...history, assistantMessage],
        status: 'idle',
        errorMessage: null,
      })
    } catch (error) {
      const message = language === 'zh' ? '无法连接到智能体。' : 'Failed to reach the agent.'
      setState((previous) => ({
        ...previous,
        status: 'error',
        errorMessage: message,
      }))
    } finally {
      isSendingRef.current = false
    }
  }

  return {
    state,
    sendMessage,
  }
}
