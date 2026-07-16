import type { ReactNode } from 'react'

import { LANGUAGE_LABELS, type Language } from '@/lib/i18n'

import styles from './AppShell.module.css'

export type AppPageId = 'stream' | 'audit' | 'chat' | 'database'

export interface AppPage {
  id: AppPageId
  label: string
  description: string
}

interface AppShellProps {
  children: ReactNode
  pages: AppPage[]
  activePageId: AppPageId
  onPageChange: (pageId: AppPageId) => void
  language: Language
  languageLabel: string
  navigationLabel: string
  tagline: string
  onLanguageChange: (language: Language) => void
}

export function AppShell({
  children,
  pages,
  activePageId,
  onPageChange,
  language,
  languageLabel,
  navigationLabel,
  tagline,
  onLanguageChange,
}: AppShellProps) {
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brandBlock}>
          <p className={styles.brand}>YOLO Retail Agent</p>
          <p className={styles.tagline}>{tagline}</p>
        </div>
        <label className={styles.languageControl}>
          <span>{languageLabel}</span>
          <select
            className={styles.languageSelect}
            value={language}
            onChange={(event) => onLanguageChange(event.target.value as Language)}
          >
            {(Object.keys(LANGUAGE_LABELS) as Language[]).map((option) => (
              <option key={option} value={option}>
                {LANGUAGE_LABELS[option]}
              </option>
            ))}
          </select>
        </label>
        <nav className={styles.nav} aria-label={navigationLabel}>
          {pages.map((page) => {
            const isActive = page.id === activePageId

            return (
              <button
                key={page.id}
                type="button"
                className={`${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
                aria-current={isActive ? 'page' : undefined}
                onClick={() => onPageChange(page.id)}
              >
                <span className={styles.navLabel}>{page.label}</span>
                <span className={styles.navDescription}>{page.description}</span>
              </button>
            )
          })}
        </nav>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  )
}
