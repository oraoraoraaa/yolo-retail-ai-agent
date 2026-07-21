import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from 'react'

import { createClientId } from '@/lib/id'
import type { Language, UI_TEXT } from '@/lib/i18n'
import type {
  ChatMessage,
  ChatOutgoingAttachment,
  ChatRequestStatus,
  ChatSession,
} from '@/types'

import { MarkdownContent } from './MarkdownContent'
import styles from './ChatPanel.module.css'

const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const AGENT_AVATAR_SRC = '/icons/agent-avatar.jpeg'

interface ChatPanelProps {
  text: (typeof UI_TEXT)[Language]['chat']
  messages: ChatMessage[]
  sessions: ChatSession[]
  activeSessionId: string | null
  status: ChatRequestStatus
  errorMessage: string | null
  onSendMessage: (content: string, attachments?: ChatOutgoingAttachment[]) => Promise<void>
  onSelectSession: (sessionId: string) => void
  onCreateSession: () => void
  onDeleteSession: (sessionId: string) => void
}

function isAcceptedImage(file: File): boolean {
  return ACCEPTED_IMAGE_TYPES.includes(file.type) || /\.(jpe?g|png|webp|gif)$/i.test(file.name)
}

function formatFileSize(size: number): string {
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`
  }

  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatSessionTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ''
  }
  return date.toLocaleString()
}

export function ChatPanel({
  text,
  messages,
  sessions,
  activeSessionId,
  status,
  errorMessage,
  onSendMessage,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
}: ChatPanelProps) {
  const [draft, setDraft] = useState('')
  const [attachments, setAttachments] = useState<ChatOutgoingAttachment[]>([])
  const [localError, setLocalError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const isSending = status === 'sending'
  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? null

  useEffect(() => {
    const node = listRef.current
    if (!node) {
      return
    }

    node.scrollTop = node.scrollHeight
  }, [messages, isSending, activeSessionId])

  async function handleSubmit(event?: FormEvent): Promise<void> {
    event?.preventDefault()
    const content = draft.trim()

    if ((!content && attachments.length === 0) || isSending) {
      return
    }

    const outgoingAttachments = attachments
    setDraft('')
    setAttachments([])
    await onSendMessage(content, outgoingAttachments)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void handleSubmit()
    }
  }

  function onAttachmentChange(event: ChangeEvent<HTMLInputElement>): void {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''

    if (files.length === 0) {
      return
    }

    const nextAttachments: ChatOutgoingAttachment[] = []

    for (const file of files) {
      if (!isAcceptedImage(file)) {
        setLocalError(text.invalidAttachment)
        continue
      }

      nextAttachments.push({
        id: createClientId('img'),
        name: file.name,
        type: file.type,
        size: file.size,
        previewUrl: URL.createObjectURL(file),
        file,
      })
    }

    if (nextAttachments.length > 0) {
      setLocalError(null)
      setAttachments((previous) => {
        const combined = [...previous, ...nextAttachments]
        const kept = combined.slice(0, 4)

        for (const dropped of combined.slice(4)) {
          if (dropped.previewUrl) {
            URL.revokeObjectURL(dropped.previewUrl)
          }
        }

        return kept
      })
    }
  }

  function removeAttachment(attachmentId: string): void {
    setAttachments((previous) => {
      const removed = previous.find((attachment) => attachment.id === attachmentId)
      if (removed?.previewUrl) {
        URL.revokeObjectURL(removed.previewUrl)
      }

      return previous.filter((attachment) => attachment.id !== attachmentId)
    })
  }

  function applyPrompt(prompt: string): void {
    setDraft(prompt)
  }

  function handleNewSession(): void {
    setDraft('')
    setAttachments((previous) => {
      for (const attachment of previous) {
        if (attachment.previewUrl) {
          URL.revokeObjectURL(attachment.previewUrl)
        }
      }
      return []
    })
    setLocalError(null)
    onCreateSession()
    setHistoryOpen(false)
  }

  function handleDeleteSession(sessionId: string): void {
    if (!window.confirm(text.confirmDeleteSession)) {
      return
    }
    onDeleteSession(sessionId)
  }

  return (
    <section className={styles.panel} aria-labelledby="chat-panel-title">
      <header className={styles.header}>
        <div className={styles.headerIdentity}>
          <img
            className={styles.headerAvatar}
            src={AGENT_AVATAR_SRC}
            alt=""
            width={40}
            height={40}
            decoding="async"
          />
          <div className={styles.headerCopy}>
            <h2 id="chat-panel-title" className={styles.title}>
              {text.title}
            </h2>
            <p className={styles.subtitle}>{text.subtitle}</p>
            {activeSession ? (
              <p className={styles.activeSessionLabel}>
                {text.activeSession}: {activeSession.title}
              </p>
            ) : null}
          </div>
        </div>

        <div className={styles.headerActions}>
          <button
            type="button"
            className={`${styles.headerButton} glass-lens`}
            onClick={handleNewSession}
            disabled={isSending}
          >
            {text.newSession}
          </button>
          <button
            type="button"
            className={`${styles.headerButton} ${historyOpen ? styles.headerButtonActive : ''} glass-lens`}
            aria-expanded={historyOpen}
            aria-controls="chat-history-panel"
            onClick={() => setHistoryOpen((open) => !open)}
          >
            {text.history}
          </button>
        </div>
      </header>

      <div className={styles.body}>
        {historyOpen ? (
          <aside id="chat-history-panel" className={styles.historyPanel} aria-label={text.historyLabel}>
            <div className={styles.historyHeader}>
              <h3 className={styles.historyTitle}>{text.historyLabel}</h3>
              <button type="button" className={`${styles.historyNewButton} glass-lens`} onClick={handleNewSession}>
                {text.newSession}
              </button>
            </div>
            {sessions.length === 0 ? (
              <p className={styles.historyEmpty}>{text.emptyHistory}</p>
            ) : (
              <ul className={styles.historyList}>
                {sessions.map((session) => {
                  const isActive = session.id === activeSessionId
                  return (
                    <li key={session.id}>
                      <div className={`${styles.historyItem} ${isActive ? styles.historyItemActive : ''}`}>
                        <button
                          type="button"
                          className={styles.historySelect}
                          onClick={() => {
                            onSelectSession(session.id)
                            setHistoryOpen(false)
                          }}
                        >
                          <span className={styles.historyItemTitle}>{session.title}</span>
                          <span className={styles.historyItemMeta}>
                            {formatSessionTime(session.updatedAt)} · {session.messages.length}
                          </span>
                        </button>
                        <button
                          type="button"
                          className={styles.historyDelete}
                          aria-label={`${text.deleteSessionAriaPrefix} ${session.title}`}
                          onClick={() => handleDeleteSession(session.id)}
                        >
                          {text.deleteSession}
                        </button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </aside>
        ) : null}

        <div className={styles.conversation}>
          <div ref={listRef} className={styles.messages} role="log" aria-live="polite">
            {messages.length === 0 ? (
              <div className={styles.emptyState}>
                <img
                  className={styles.emptyAvatar}
                  src={AGENT_AVATAR_SRC}
                  alt=""
                  width={72}
                  height={72}
                  decoding="async"
                />
                <p className={styles.emptyTitle}>{text.emptyTitle}</p>
                <div className={styles.promptGrid} aria-label={text.recommendedQuestions}>
                  {text.prompts.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      className={`${styles.promptChip} glass-lens`}
                      onClick={() => applyPrompt(prompt)}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((message) => {
                const isUser = message.role === 'user'
                const isEmptyAssistant = !isUser && message.content.trim().length === 0

                return (
                  <div
                    key={message.id}
                    className={`${styles.bubbleRow} ${isUser ? styles.bubbleRowUser : styles.bubbleRowAssistant}`}
                  >
                    {!isUser ? (
                      <img
                        className={styles.avatar}
                        src={AGENT_AVATAR_SRC}
                        alt=""
                        width={36}
                        height={36}
                        decoding="async"
                      />
                    ) : null}
                    <div
                      className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleAssistant} ${
                        isEmptyAssistant ? styles.bubbleEmpty : ''
                      } ${!isUser && !isEmptyAssistant ? styles.bubbleMarkdown : ''}`}
                    >
                      {isEmptyAssistant ? (
                        text.waiting
                      ) : isUser ? (
                        message.content
                      ) : (
                        <MarkdownContent content={message.content} />
                      )}
                      {message.attachments && message.attachments.length > 0 ? (
                        <div className={styles.messageAttachments}>
                          {message.attachments.map((attachment) => (
                            <figure key={attachment.id} className={styles.messageAttachment}>
                              {attachment.previewUrl ? (
                                <img
                                  src={attachment.previewUrl}
                                  alt={attachment.name}
                                  className={styles.messageImage}
                                />
                              ) : null}
                              <figcaption>{attachment.name}</figcaption>
                            </figure>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>
                )
              })
            )}

            {isSending ? (
              <div className={`${styles.bubbleRow} ${styles.bubbleRowAssistant}`}>
                <img
                  className={styles.avatar}
                  src={AGENT_AVATAR_SRC}
                  alt=""
                  width={36}
                  height={36}
                  decoding="async"
                />
                <div className={`${styles.bubble} ${styles.bubbleAssistant} ${styles.bubbleEmpty}`}>
                  {text.thinking}
                </div>
              </div>
            ) : null}
          </div>

          {errorMessage ? <p className={styles.errorLine}>{errorMessage}</p> : null}
          {localError ? <p className={styles.errorLine}>{localError}</p> : null}

          <form className={styles.composer} onSubmit={(event) => void handleSubmit(event)}>
            {attachments.length > 0 ? (
              <div className={styles.attachmentTray}>
                {attachments.map((attachment) => (
                  <div key={attachment.id} className={styles.pendingAttachment}>
                    {attachment.previewUrl ? (
                      <img src={attachment.previewUrl} alt={attachment.name} className={styles.pendingImage} />
                    ) : null}
                    <div className={styles.pendingMeta}>
                      <span>{attachment.name}</span>
                      <span>{formatFileSize(attachment.size)}</span>
                    </div>
                    <button
                      type="button"
                      className={styles.removeAttachmentButton}
                      aria-label={`${text.removeAttachmentAriaPrefix} ${attachment.name}`}
                      onClick={() => removeAttachment(attachment.id)}
                    >
                      X
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
            <input
              ref={fileInputRef}
              className={styles.fileInput}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              multiple
              onChange={onAttachmentChange}
            />
            <button
              type="button"
              className={styles.attachButton}
              disabled={isSending}
              aria-label={text.attachImagesAria}
              title={text.attachImages}
              onClick={() => fileInputRef.current?.click()}
            >
              +
            </button>
            <textarea
              className={styles.input}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder={text.placeholder}
              aria-label={text.placeholder}
              disabled={isSending}
              rows={2}
            />
            <button
              className={styles.sendButton}
              type="submit"
              disabled={isSending || (draft.trim().length === 0 && attachments.length === 0)}
            >
              {isSending ? text.sending : text.send}
            </button>
          </form>
        </div>
      </div>
    </section>
  )
}
