import { useState, type FormEvent } from 'react'

import type { Language, UI_TEXT } from '@/lib/i18n'

import styles from './LoginPanel.module.css'

interface LoginPanelProps {
  text: (typeof UI_TEXT)[Language]['auth']
  language: Language
  languageLabel: string
  onLanguageChange: (language: Language) => void
  errorMessage: string | null
  onSubmit: (username: string, password: string) => Promise<boolean>
}

export function LoginPanel({
  text,
  language,
  languageLabel,
  onLanguageChange,
  errorMessage,
  onSubmit,
}: LoginPanelProps) {
  // Match the bootstrap owner seeded by AUTH_ADMIN_USERNAME (default: owner).
  // Older DBs may still use an "admin" username — the hint below covers that.
  const [username, setUsername] = useState('owner')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault()
    setSubmitting(true)
    try {
      await onSubmit(username.trim(), password)
    } finally {
      setSubmitting(false)
    }
  }

  const displayError =
    errorMessage === 'invalid'
      ? text.errors.invalid
      : errorMessage === 'failed'
        ? text.errors.failed
        : errorMessage

  return (
    <div className={styles.page}>
      <form className={styles.card} onSubmit={(event) => void handleSubmit(event)}>
        <div className={styles.brandBlock}>
          <p className={styles.brand}>YOLO Retail Agent</p>
          <p className={styles.tagline}>{text.tagline}</p>
        </div>

        <label className={styles.field}>
          <span>{text.username}</span>
          <input
            className={styles.input}
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>

        <label className={styles.field}>
          <span>{text.password}</span>
          <input
            className={styles.input}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>

        {displayError ? <p className={styles.error}>{displayError}</p> : null}

        <button className={styles.submit} type="submit" disabled={submitting}>
          {submitting ? text.signingIn : text.signIn}
        </button>

        <p className={styles.hint}>{text.hint}</p>

        <label className={styles.languageControl}>
          <span>{languageLabel}</span>
          <select
            className={styles.languageSelect}
            value={language}
            onChange={(event) => onLanguageChange(event.target.value as Language)}
          >
            <option value="en">English</option>
            <option value="zh">中文</option>
          </select>
        </label>
      </form>
    </div>
  )
}
