import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { sendChatMessage } from '@/api'
import { createClientId } from '@/lib/id'
import type { Language } from '@/lib/i18n'
import type { ChatMessage, ChatOutgoingAttachment, ChatPanelState, ChatSession } from '@/types'

const STORAGE_KEY = 'yolo-retail-chat-sessions-v1'

function stripFileHandles(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    ...message,
    attachments: message.attachments?.map((attachment) => ({
      id: attachment.id,
      name: attachment.name,
      type: attachment.type,
      size: attachment.size,
      // Object URLs are tab-scoped; keep only metadata in storage.
      previewUrl: undefined,
    })),
  }))
}

function createEmptySession(title = 'New chat'): ChatSession {
  const now = new Date().toISOString()
  return {
    id: createClientId('chat'),
    title,
    createdAt: now,
    updatedAt: now,
    messages: [],
  }
}

function titleFromMessages(messages: ChatMessage[], fallback: string): string {
  const firstUser = messages.find((message) => message.role === 'user' && message.content.trim())
  if (!firstUser) {
    return fallback
  }
  const text = firstUser.content.trim().replace(/\s+/g, ' ')
  return text.length > 42 ? `${text.slice(0, 42)}…` : text
}

function loadStoredState(): Pick<ChatPanelState, 'sessions' | 'activeSessionId' | 'messages'> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      const session = createEmptySession()
      return { sessions: [session], activeSessionId: session.id, messages: [] }
    }
    const parsed = JSON.parse(raw) as {
      sessions?: ChatSession[]
      activeSessionId?: string | null
    }
    const sessions = Array.isArray(parsed.sessions)
      ? parsed.sessions
          .filter((session) => session && typeof session.id === 'string')
          .map((session) => ({
            id: session.id,
            title: session.title || 'New chat',
            createdAt: session.createdAt || new Date().toISOString(),
            updatedAt: session.updatedAt || session.createdAt || new Date().toISOString(),
            messages: Array.isArray(session.messages) ? stripFileHandles(session.messages) : [],
          }))
      : []
    if (sessions.length === 0) {
      const session = createEmptySession()
      return { sessions: [session], activeSessionId: session.id, messages: [] }
    }
    const activeSessionId =
      (parsed.activeSessionId && sessions.some((session) => session.id === parsed.activeSessionId)
        ? parsed.activeSessionId
        : sessions[0]?.id) ?? null
    const active = sessions.find((session) => session.id === activeSessionId) ?? sessions[0]
    return {
      sessions,
      activeSessionId: active.id,
      messages: active.messages,
    }
  } catch {
    const session = createEmptySession()
    return { sessions: [session], activeSessionId: session.id, messages: [] }
  }
}

function persistState(sessions: ChatSession[], activeSessionId: string | null): void {
  try {
    const payload = {
      activeSessionId,
      sessions: sessions.map((session) => ({
        ...session,
        messages: stripFileHandles(session.messages),
      })),
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  } catch {
    // Ignore quota / private-mode failures; chat still works for the tab.
  }
}

export function useAgentChat() {
  const [state, setState] = useState<ChatPanelState>(() => ({
    ...loadStoredState(),
    status: 'idle',
    errorMessage: null,
  }))
  const isSendingRef = useRef(false)

  useEffect(() => {
    persistState(state.sessions, state.activeSessionId)
  }, [state.sessions, state.activeSessionId])

  const activeSession = useMemo(
    () => state.sessions.find((session) => session.id === state.activeSessionId) ?? null,
    [state.sessions, state.activeSessionId],
  )

  const selectSession = useCallback((sessionId: string) => {
    setState((previous) => {
      const next = previous.sessions.find((session) => session.id === sessionId)
      if (!next) {
        return previous
      }
      return {
        ...previous,
        activeSessionId: next.id,
        messages: next.messages,
        status: 'idle',
        errorMessage: null,
      }
    })
  }, [])

  const createSession = useCallback((title = 'New chat') => {
    const session = createEmptySession(title)
    setState((previous) => ({
      ...previous,
      sessions: [session, ...previous.sessions],
      activeSessionId: session.id,
      messages: [],
      status: 'idle',
      errorMessage: null,
    }))
    return session.id
  }, [])

  const deleteSession = useCallback((sessionId: string) => {
    setState((previous) => {
      const remaining = previous.sessions.filter((session) => session.id !== sessionId)
      if (remaining.length === 0) {
        const session = createEmptySession()
        return {
          ...previous,
          sessions: [session],
          activeSessionId: session.id,
          messages: [],
          status: 'idle',
          errorMessage: null,
        }
      }
      const deletingActive = previous.activeSessionId === sessionId
      const nextActive = deletingActive ? remaining[0] : remaining.find((s) => s.id === previous.activeSessionId) ?? remaining[0]
      return {
        ...previous,
        sessions: remaining,
        activeSessionId: nextActive.id,
        messages: deletingActive ? nextActive.messages : previous.messages,
        status: 'idle',
        errorMessage: null,
      }
    })
  }, [])

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

      // Ensure there is an active session before writing.
      let sessions = state.sessions
      let activeSessionId = state.activeSessionId
      if (!activeSessionId || !sessions.some((session) => session.id === activeSessionId)) {
        const session = createEmptySession()
        sessions = [session, ...sessions]
        activeSessionId = session.id
      }

      const current = sessions.find((session) => session.id === activeSessionId)
      const history = [...(current?.messages ?? state.messages), userMessage]
      const now = new Date().toISOString()
      const fallbackTitle = language === 'zh' ? '新对话' : 'New chat'
      const nextSessions = sessions.map((session) =>
        session.id === activeSessionId
          ? {
              ...session,
              title: titleFromMessages(history, fallbackTitle),
              updatedAt: now,
              messages: history,
            }
          : session,
      )

      setState({
        sessions: nextSessions,
        activeSessionId,
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
      const complete = [...history, assistantMessage]
      const completeAt = new Date().toISOString()

      setState((previous) => ({
        ...previous,
        sessions: previous.sessions.map((session) =>
          session.id === activeSessionId
            ? {
                ...session,
                title: titleFromMessages(complete, fallbackTitle),
                updatedAt: completeAt,
                messages: complete,
              }
            : session,
        ),
        activeSessionId,
        messages: complete,
        status: 'idle',
        errorMessage: null,
      }))
    } catch {
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
    activeSession,
    sendMessage,
    selectSession,
    createSession,
    deleteSession,
  }
}
