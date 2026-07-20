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
      <div className={styles.topBar}>
        <label className={styles.languageControl}>
          <span className={styles.srOnly}>{languageLabel}</span>
          <select
            className={styles.languageSelect}
            value={language}
            aria-label={languageLabel}
            onChange={(event) => onLanguageChange(event.target.value as Language)}
          >
            <option value="en">English</option>
            <option value="zh">中文</option>
          </select>
        </label>
      </div>

      <div className={styles.stage}>
        <section className={styles.intro} aria-labelledby="login-title">
          <div className={styles.mark} aria-hidden="true">
            <span className={styles.markGlyph}>Y</span>
          </div>
          <h1 id="login-title" className={styles.title}>
            {text.signInTitle}
          </h1>
          <p className={styles.subtitle}>{text.signInSubtitle}</p>
        </section>

        <form className={styles.form} onSubmit={(event) => void handleSubmit(event)}>
          <div className={styles.fields}>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>{text.username}</span>
              <input
                className={styles.input}
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder={text.usernamePlaceholder}
                required
              />
            </label>

            <label className={styles.field}>
              <span className={styles.fieldLabel}>{text.password}</span>
              <input
                className={styles.input}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={text.passwordPlaceholder}
                required
              />
            </label>
          </div>

          {displayError ? <p className={styles.error}>{displayError}</p> : null}

          <p className={styles.privacyNote}>
            {text.privacyNote}{' '}
            <span className={styles.linkish}>{text.learnMore}</span>
          </p>

          <div className={styles.actions}>
            <p className={styles.hint}>{text.hintShort}</p>
            <button className={`${styles.next} glass-lens`} type="submit" disabled={submitting}>
              {submitting ? text.signingIn : text.next}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
