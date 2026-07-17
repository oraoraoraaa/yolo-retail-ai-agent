import { useEffect, useState, type FormEvent } from 'react'

import { queryDatabaseRecords } from '@/api'
import type { Language, UI_TEXT } from '@/lib/i18n'
import type { DatabaseRecord, DatabaseRecordType } from '@/types'

import styles from './DatabasePanel.module.css'

type FilterValue = DatabaseRecordType | 'all'

const FILTER_VALUES: FilterValue[] = ['all', 'audit', 'sku', 'inventory', 'chat']

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

interface DatabasePanelProps {
  text: (typeof UI_TEXT)[Language]['database']
}

export function DatabasePanel({ text }: DatabasePanelProps) {
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
      const message = text.errors.queryFailed
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
  const typeLabels = text.typeLabels

  return (
    <section className={styles.panel} aria-labelledby="database-panel-title">
      <header className={styles.header}>
        <div>
          <h2 id="database-panel-title" className={styles.title}>
            {text.title}
          </h2>
          <p className={styles.subtitle}>{text.subtitle}</p>
        </div>
        <button className={styles.refreshButton} type="button" disabled={isLoading} onClick={() => void loadRecords()}>
          {isLoading ? text.loading : text.refresh}
        </button>
      </header>

      <form className={styles.toolbar} onSubmit={onSubmit}>
        <label className={styles.searchLabel}>
          <span>{text.search}</span>
          <input
            className={styles.searchInput}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder={text.placeholder}
          />
        </label>
        <div className={styles.filters} aria-label={text.recordTypeLabel}>
          {FILTER_VALUES.map((value, index) => (
            <button
              key={value}
              type="button"
              className={`${styles.filterButton} ${filter === value ? styles.filterButtonActive : ''}`}
              aria-pressed={filter === value}
              onClick={() => onFilterChange(value)}
            >
              {text.filters[index]}
            </button>
          ))}
        </div>
        <button className={styles.queryButton} type="submit" disabled={isLoading}>
          {text.query}
        </button>
      </form>

      {errorMessage ? <p className={styles.errorLine}>{errorMessage}</p> : null}

      <div className={styles.tableWrap}>
        {records.length > 0 ? (
          <table className={styles.table}>
            <thead>
              <tr>
                {text.columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.id}>
                  <td>
                    <span className={styles.typeBadge}>{typeLabels[record.type]}</span>
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
            <p className={styles.emptyTitle}>{isLoading ? text.loadingRecords : text.emptyTitle}</p>
            <p className={styles.emptyCopy}>{text.emptyCopy}</p>
          </div>
        )}
      </div>
    </section>
  )
}
