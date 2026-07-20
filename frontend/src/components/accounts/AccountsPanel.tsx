import { useEffect, useState, type FormEvent } from 'react'

import {
  createStaffAccount,
  deleteStaffAccount,
  listStaffAccounts,
  updateStaffAccount,
} from '@/api/auth'
import { ApiError } from '@/api/client'
import type { Language, UI_TEXT } from '@/lib/i18n'
import type { StaffAccount } from '@/types/auth'

import styles from './AccountsPanel.module.css'

type AccountsText = (typeof UI_TEXT)[Language]['accounts']

const ROLE_OPTIONS = ['owner', 'admin', 'staff'] as const

interface AccountsPanelProps {
  text: AccountsText
  language: Language
  /** Owner can add/edit/delete; admin can only view. */
  canManage: boolean
  /** Current user's id, so we can flag "You" and block self-delete. */
  currentUserId: number | null
}

interface EditorState {
  mode: 'create' | 'edit'
  id: number | null
  username: string
  password: string
  role: string
  isActive: boolean
}

function formatDate(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function roleLabel(text: AccountsText, role: string): string {
  const labels = text.roleLabels as Record<string, string>
  return labels[role] ?? role
}

export function AccountsPanel({ text, canManage, currentUserId }: AccountsPanelProps) {
  const [accounts, setAccounts] = useState<StaffAccount[]>([])
  const [status, setStatus] = useState<'idle' | 'loading' | 'saving' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [statusLine, setStatusLine] = useState<string | null>(null)
  const [editor, setEditor] = useState<EditorState | null>(null)

  async function loadAccounts(): Promise<void> {
    setStatus('loading')
    setErrorMessage(null)
    try {
      const result = await listStaffAccounts()
      setAccounts(result.accounts)
      setStatus('idle')
    } catch {
      setErrorMessage(text.errors.loadFailed)
      setStatus('error')
    }
  }

  useEffect(() => {
    void loadAccounts()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openCreate(): void {
    setStatusLine(null)
    setErrorMessage(null)
    setEditor({
      mode: 'create',
      id: null,
      username: '',
      password: '',
      role: 'staff',
      isActive: true,
    })
  }

  function openEdit(account: StaffAccount): void {
    setStatusLine(null)
    setErrorMessage(null)
    setEditor({
      mode: 'edit',
      id: account.id,
      username: account.username,
      password: '',
      role: account.role,
      isActive: account.isActive,
    })
  }

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (!editor) return

    const username = editor.username.trim()
    if (!username) {
      setErrorMessage(text.errors.usernameRequired)
      return
    }
    if (editor.mode === 'create' && !editor.password) {
      setErrorMessage(text.errors.passwordRequired)
      return
    }

    setStatus('saving')
    setErrorMessage(null)
    try {
      if (editor.mode === 'create') {
        await createStaffAccount({
          username,
          password: editor.password,
          role: editor.role,
          isActive: editor.isActive,
        })
        setStatusLine(text.createdMsg)
      } else if (editor.id != null) {
        await updateStaffAccount(editor.id, {
          username,
          // Only send password when the owner typed a new one.
          password: editor.password ? editor.password : undefined,
          role: editor.role,
          isActive: editor.isActive,
        })
        setStatusLine(text.updatedMsg)
      }
      setEditor(null)
      await loadAccounts()
      setStatus('idle')
    } catch (error) {
      const detail =
        error instanceof ApiError && error.message ? error.message : text.errors.saveFailed
      setErrorMessage(detail)
      setStatus('error')
    }
  }

  async function onDelete(account: StaffAccount): Promise<void> {
    if (!window.confirm(text.confirmDelete)) return
    setStatus('saving')
    setErrorMessage(null)
    setStatusLine(null)
    try {
      await deleteStaffAccount(account.id)
      setStatusLine(text.deletedMsg)
      await loadAccounts()
      setStatus('idle')
    } catch (error) {
      const detail =
        error instanceof ApiError && error.message ? error.message : text.errors.deleteFailed
      setErrorMessage(detail)
      setStatus('error')
    }
  }

  const isBusy = status === 'loading' || status === 'saving'

  return (
    <section className={styles.panel} aria-labelledby="accounts-panel-title">
      <header className={styles.header}>
        <div>
          <h2 id="accounts-panel-title" className={styles.title}>
            {text.title}
          </h2>
          <p className={styles.subtitle}>{text.subtitle}</p>
        </div>
        <div className={styles.headerActions}>
          {canManage ? (
            <button
              className={`${styles.button} ${styles.primaryButton} glass-lens`}
              type="button"
              disabled={isBusy}
              onClick={openCreate}
            >
              {text.addUser}
            </button>
          ) : null}
          <button
            className={`${styles.button} glass-lens`}
            type="button"
            disabled={isBusy}
            onClick={() => void loadAccounts()}
          >
            {status === 'loading' ? text.loading : text.refresh}
          </button>
        </div>
      </header>

      {!canManage ? <p className={styles.notice}>{text.viewerNotice}</p> : null}
      {statusLine ? <p className={styles.statusLine}>{statusLine}</p> : null}
      {errorMessage ? <p className={styles.errorLine}>{errorMessage}</p> : null}

      <div className={styles.tableWrap}>
        {accounts.length > 0 ? (
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">{text.username}</th>
                <th scope="col">{text.role}</th>
                <th scope="col">{text.status}</th>
                <th scope="col">{text.created}</th>
                {canManage ? <th scope="col">{text.actions}</th> : null}
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => {
                const isSelf = currentUserId != null && account.id === currentUserId
                return (
                  <tr key={account.id}>
                    <td>
                      {account.username}
                      {isSelf ? <span className={styles.selfBadge}>({text.selfBadge})</span> : null}
                    </td>
                    <td>
                      <span
                        className={`${styles.roleBadge} ${
                          account.role === 'owner' ? styles.roleOwner : ''
                        }`}
                      >
                        {roleLabel(text, account.role)}
                      </span>
                    </td>
                    <td>
                      <span
                        className={account.isActive ? styles.statusActive : styles.statusInactive}
                      >
                        {account.isActive ? text.active : text.inactive}
                      </span>
                    </td>
                    <td>{formatDate(account.createdAt)}</td>
                    {canManage ? (
                      <td>
                        <div className={styles.rowActions}>
                          <button
                            className={styles.linkButton}
                            type="button"
                            disabled={isBusy}
                            onClick={() => openEdit(account)}
                          >
                            {text.edit}
                          </button>
                          <button
                            className={`${styles.linkButton} ${styles.linkDanger}`}
                            type="button"
                            disabled={isBusy || isSelf}
                            title={isSelf ? text.selfBadge : undefined}
                            onClick={() => void onDelete(account)}
                          >
                            {text.delete}
                          </button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <div className={styles.emptyState}>
            <p className={styles.emptyTitle}>
              {status === 'loading' ? text.loading : text.emptyTitle}
            </p>
            <p className={styles.emptyCopy}>{text.emptyCopy}</p>
          </div>
        )}
      </div>

      {editor && canManage ? (
        <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={text.title}>
          <form className={styles.card} onSubmit={(event) => void onSubmit(event)}>
            <h3 className={styles.cardTitle}>
              {editor.mode === 'create' ? text.newUserTitle : text.editUserTitle}
            </h3>

            <label className={styles.field}>
              <span>{text.username}</span>
              <input
                className={styles.input}
                value={editor.username}
                placeholder={text.usernamePlaceholder}
                autoComplete="off"
                onChange={(event) =>
                  setEditor((prev) => (prev ? { ...prev, username: event.target.value } : prev))
                }
              />
            </label>

            <label className={styles.field}>
              <span>{text.password}</span>
              <input
                className={styles.input}
                type="password"
                value={editor.password}
                placeholder={text.passwordPlaceholder}
                autoComplete="new-password"
                onChange={(event) =>
                  setEditor((prev) => (prev ? { ...prev, password: event.target.value } : prev))
                }
              />
              {editor.mode === 'edit' ? (
                <span className={styles.hint}>{text.passwordKeepHint}</span>
              ) : null}
            </label>

            <label className={styles.field}>
              <span>{text.role}</span>
              <select
                className={styles.select}
                value={editor.role}
                onChange={(event) =>
                  setEditor((prev) => (prev ? { ...prev, role: event.target.value } : prev))
                }
              >
                {ROLE_OPTIONS.map((role) => (
                  <option key={role} value={role}>
                    {roleLabel(text, role)}
                  </option>
                ))}
              </select>
              <span className={styles.hint}>
                {(text.roleHints as Record<string, string>)[editor.role] ?? ''}
              </span>
            </label>

            <label className={styles.checkboxField}>
              <input
                type="checkbox"
                checked={editor.isActive}
                onChange={(event) =>
                  setEditor((prev) => (prev ? { ...prev, isActive: event.target.checked } : prev))
                }
              />
              <span>{text.active}</span>
            </label>

            <div className={styles.cardActions}>
              <button
                className={`${styles.button} glass-lens`}
                type="button"
                disabled={status === 'saving'}
                onClick={() => setEditor(null)}
              >
                {text.cancel}
              </button>
              <button
                className={`${styles.button} ${styles.primaryButton} glass-lens`}
                type="submit"
                disabled={status === 'saving'}
              >
                {status === 'saving'
                  ? text.saving
                  : editor.mode === 'create'
                    ? text.create
                    : text.save}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </section>
  )
}
