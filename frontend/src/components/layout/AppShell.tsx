import type { ReactNode } from 'react'

import { LANGUAGE_LABELS, type Language } from '@/lib/i18n'

import styles from './AppShell.module.css'

export type AppPageId = 'audit' | 'planogram' | 'tickets' | 'chat' | 'database' | 'accounts'

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
  userLabel?: string | null
  logoutLabel?: string
  onLogout?: () => void
}

const PAGE_ICONS: Record<AppPageId, string> = {
  audit: '◎',
  planogram: '▦',
  tickets: '⚑',
  chat: '◉',
  database: '▤',
  accounts: '☺',
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
  userLabel,
  logoutLabel,
  onLogout,
}: AppShellProps) {
  const activePage = pages.find((page) => page.id === activePageId) ?? pages[0]
  const userName = userLabel?.replace(/^.*\s/, '') || 'Staff'

  return (
    <div className={styles.shell}>
      <div className={styles.stageGlow} aria-hidden="true" />

      <aside className={styles.sidebar}>
        <div className={styles.profileRow}>
          <div className={styles.avatar} aria-hidden="true">
            {userName.slice(0, 1).toUpperCase()}
          </div>
          <div className={styles.profileCopy}>
            <p className={styles.profileName}>{userName}</p>
            <p className={styles.profileMeta}>{tagline}</p>
          </div>
        </div>

        <nav className={styles.nav} aria-label={navigationLabel}>
          {pages.map((page) => {
            const isActive = page.id === activePageId

            return (
              <button
                key={page.id}
                type="button"
                className={`${styles.navItem} glass-lens ${isActive ? styles.navItemActive : ''}`}
                aria-current={isActive ? 'page' : undefined}
                onClick={() => onPageChange(page.id)}
                title={page.description}
              >
                <span className={styles.navIcon} aria-hidden="true">
                  {PAGE_ICONS[page.id]}
                </span>
                <span className={styles.navText}>
                  <span className={styles.navLabel}>{page.label}</span>
                  <span className={styles.navDescription}>{page.description}</span>
                </span>
              </button>
            )
          })}
        </nav>

        <div className={styles.sidebarFooter}>
          <label className={styles.languageControl}>
            <span>{languageLabel}</span>
            <select
              className={`${styles.languageSelect} glass-lens`}
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

          {userLabel || onLogout ? (
            <div className={styles.userBlock}>
              {userLabel ? <p className={styles.userLabel}>{userLabel}</p> : null}
              {onLogout && logoutLabel ? (
                <button className={`${styles.logoutButton} glass-lens`} type="button" onClick={onLogout}>
                  {logoutLabel}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </aside>

      <div className={styles.workspace}>
        <header className={styles.hero}>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>YOLO Retail</p>
            <h1 className={styles.pageTitle}>{activePage?.label}</h1>
            <p className={styles.pageDescription}>{activePage?.description}</p>
          </div>
          <div className={styles.heroBadge} aria-hidden="true">
            <span className={styles.heroBadgeDot} />
            Live workspace
          </div>
        </header>

        <main key={activePageId} className={`${styles.main} liquid-flow`}>
          {children}
        </main>
      </div>
    </div>
  )
}
