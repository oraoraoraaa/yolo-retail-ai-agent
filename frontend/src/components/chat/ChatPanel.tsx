import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from 'react'

import { createClientId } from '@/lib/id'
import type { ChatMessage, ChatOutgoingAttachment, ChatRequestStatus } from '@/types'

import { MarkdownContent } from './MarkdownContent'
import styles from './ChatPanel.module.css'

const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const RECOMMENDED_PROMPTS = [
  '这张货架图里有哪些商品可能缺货？',
  '请帮我总结这次货架巡检的异常点',
  '哪些 SKU 需要优先补货？',
  '如果检测到空位，应该给门店什么操作建议？',
  '请根据图片判断陈列是否符合计划图',
  '把检测结果整理成门店员工可执行的清单',
  '这张图里有哪些价格牌或陈列问题？',
  '请解释模型判断缺货的原因',
]

interface ChatPanelProps {
  messages: ChatMessage[]
  status: ChatRequestStatus
  errorMessage: string | null
  onSendMessage: (content: string, attachments?: ChatOutgoingAttachment[]) => Promise<void>
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

export function ChatPanel({ messages, status, errorMessage, onSendMessage }: ChatPanelProps) {
  const [draft, setDraft] = useState('')
  const [attachments, setAttachments] = useState<ChatOutgoingAttachment[]>([])
  const [localError, setLocalError] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const sentPreviewUrlsRef = useRef<string[]>([])
  const isSending = status === 'sending'

  useEffect(() => {
    const node = listRef.current
    if (!node) {
      return
    }
    node.scrollTop = node.scrollHeight
  }, [messages, isSending])

  async function handleSubmit(event?: FormEvent): Promise<void> {
    event?.preventDefault()
    const content = draft.trim()
    if ((!content && attachments.length === 0) || isSending) {
      return
    }

    const outgoingAttachments = attachments
    setDraft('')
    setAttachments([])
    sentPreviewUrlsRef.current.push(
      ...outgoingAttachments
        .map((attachment) => attachment.previewUrl)
        .filter((previewUrl): previewUrl is string => Boolean(previewUrl)),
    )
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
        setLocalError('Please attach JPEG, PNG, WebP, or GIF images only.')
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

  return (
    <section className={styles.panel} aria-labelledby="chat-panel-title">
      <header className={styles.header}>
        <h2 id="chat-panel-title" className={styles.title}>
          Agent chat
        </h2>
        <p className={styles.subtitle}>
          Ask about shelf gaps, planogram mismatch, or replenishment. Replies are produced by the backend.
        </p>
      </header>

      <div ref={listRef} className={styles.messages} role="log" aria-live="polite">
        {messages.length === 0 ? (
          <div className={styles.emptyState}>
            <p className={styles.emptyTitle}>有什么我能帮你的吗？</p>
            <div className={styles.promptGrid} aria-label="Recommended questions">
              {RECOMMENDED_PROMPTS.map((prompt) => (
                <button key={prompt} type="button" className={styles.promptChip} onClick={() => applyPrompt(prompt)}>
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
                <div
                  className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleAssistant} ${
                    isEmptyAssistant ? styles.bubbleEmpty : ''
                  } ${!isUser && !isEmptyAssistant ? styles.bubbleMarkdown : ''}`}
                >
                  {isEmptyAssistant ? (
                    'Waiting for backend response...'
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
                            <img src={attachment.previewUrl} alt={attachment.name} className={styles.messageImage} />
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
            <div className={`${styles.bubble} ${styles.bubbleAssistant} ${styles.bubbleEmpty}`}>
              Agent is thinking...
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
                  aria-label={`Remove ${attachment.name}`}
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
          aria-label="Attach shelf images"
          title="Attach shelf images"
          onClick={() => fileInputRef.current?.click()}
        >
          +
        </button>
        <textarea
          className={styles.input}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Message the retail agent..."
          aria-label="Message the retail agent"
          disabled={isSending}
          rows={2}
        />
        <button
          className={styles.sendButton}
          type="submit"
          disabled={isSending || (draft.trim().length === 0 && attachments.length === 0)}
        >
          {isSending ? 'Sending' : 'Send'}
        </button>
      </form>
    </section>
  )
}
