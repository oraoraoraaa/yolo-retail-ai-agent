import { useEffect, useState, type FormEvent } from 'react'

import { queryDatabaseRecords } from '@/api'
import type { DatabaseRecord, DatabaseRecordType } from '@/types'

import styles from './DatabasePanel.module.css'

type FilterValue = DatabaseRecordType | 'all'

const FILTER_OPTIONS: Array<{ value: FilterValue; label: string }> = [
  { value: 'all', label: 'All records' },
  { value: 'audit', label: 'Audit results' },
  { value: 'sku', label: 'SKU data' },
  { value: 'inventory', label: 'Inventory' },
  { value: 'chat', label: 'Chat logs' },
]

const TYPE_LABELS: Record<DatabaseRecordType, string> = {
  audit: 'Audit',
  sku: 'SKU',
  inventory: 'Inventory',
  chat: 'Chat',
}

function formatDate(value: string): string {
  if (!value) {
    return '-'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleString()
}

export function DatabasePanel() {
  const [keyword, setKeyword] = useState('')
  const [filter, setFilter] = useState<FilterValue>('all')
  const [records, setRecords] = useState<DatabaseRecord[]>([])
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  async function loadRecords(nextKeyword = keyword, nextFilter = filter): Promise<void> {
    setStatus('loading')
    setErrorMessage(null)

    try {
      const result = await queryDatabaseRecords({
        keyword: nextKeyword.trim() || undefined,
        type: nextFilter,
      })
      setRecords(result.records)
      setStatus('idle')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to query database records.'
      setErrorMessage(message)
      setStatus('error')
    }
  }

  useEffect(() => {
    void loadRecords('', 'all')
    // Database backend is planned; load once so the page is ready when configured.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function onSubmit(event: FormEvent): void {
    event.preventDefault()
    void loadRecords()
  }

  function onFilterChange(nextFilter: FilterValue): void {
    setFilter(nextFilter)
    void loadRecords(keyword, nextFilter)
  }

  const isLoading = status === 'loading'

  return (
    <section className={styles.panel} aria-labelledby="database-panel-title">
      <header className={styles.header}>
        <div>
          <h2 id="database-panel-title" className={styles.title}>
            Database workspace
          </h2>
          <p className={styles.subtitle}>
            Reserved page for saved audit results, SKU inventory, and conversation records.
          </p>
        </div>
        <button className={styles.refreshButton} type="button" disabled={isLoading} onClick={() => void loadRecords()}>
          {isLoading ? 'Loading' : 'Refresh'}
        </button>
      </header>

      <form className={styles.toolbar} onSubmit={onSubmit}>
        <label className={styles.searchLabel}>
          <span>Search</span>
          <input
            className={styles.searchInput}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="SKU, shelf, audit id, or note"
          />
        </label>
        <div className={styles.filters} aria-label="Record type filter">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`${styles.filterButton} ${filter === option.value ? styles.filterButtonActive : ''}`}
              aria-pressed={filter === option.value}
              onClick={() => onFilterChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <button className={styles.queryButton} type="submit" disabled={isLoading}>
          Query
        </button>
      </form>

      {errorMessage ? <p className={styles.errorLine}>{errorMessage}</p> : null}

      <div className={styles.tableWrap}>
        {records.length > 0 ? (
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Type</th>
                <th scope="col">Title</th>
                <th scope="col">Summary</th>
                <th scope="col">Updated</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.id}>
                  <td>
                    <span className={styles.typeBadge}>{TYPE_LABELS[record.type]}</span>
                  </td>
                  <td>{record.title}</td>
                  <td>{record.summary}</td>
                  <td>{formatDate(record.updatedAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className={styles.emptyState}>
            <p className={styles.emptyTitle}>{isLoading ? 'Loading records' : 'No records to display'}</p>
            <p className={styles.emptyCopy}>
              Connect the database endpoint to show saved shelf audits, SKU records, inventory changes, and chat logs.
            </p>
          </div>
        )}
      </div>
    </section>
  )
}
