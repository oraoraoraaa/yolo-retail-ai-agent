import { useState } from 'react'

import { sendChatMessage } from '@/api'
import { createClientId } from '@/lib/id'
import type { ChatMessage, ChatOutgoingAttachment, ChatPanelState } from '@/types'

const INITIAL_STATE: ChatPanelState = {
  messages: [],
  status: 'idle',
  errorMessage: null,
}

export function useAgentChat() {
  const [state, setState] = useState<ChatPanelState>(INITIAL_STATE)

  async function sendMessage(rawContent: string, attachments: ChatOutgoingAttachment[] = []): Promise<void> {
    const content = rawContent.trim()
    if ((!content && attachments.length === 0) || state.status === 'sending') {
      return
    }

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

    try {
      const { reply } = await sendChatMessage({
        message: content,
        history,
        attachments,
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
      const message = error instanceof Error ? error.message : 'Failed to reach the agent.'
      setState((previous) => ({
        ...previous,
        status: 'error',
        errorMessage: message,
      }))
    }
  }

  return {
    state,
    sendMessage,
  }
}
