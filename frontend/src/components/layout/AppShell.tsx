import type { ReactNode } from 'react'

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
}

export function AppShell({ children, pages, activePageId, onPageChange }: AppShellProps) {
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brandBlock}>
          <p className={styles.brand}>YOLO Retail Agent</p>
          <p className={styles.tagline}>Shelf audit workspace</p>
        </div>
        <nav className={styles.nav} aria-label="Feature pages">
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
