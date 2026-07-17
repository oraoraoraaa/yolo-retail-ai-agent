import { useEffect, useState, type FormEvent } from 'react'

import { queryDatabaseRecords, getDatabaseRecord } from '@/api'
import { absoluteApiUrl, getAuthToken } from '@/api/client'
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

function mediaSrc(url: string | null | undefined): string | null {
  if (!url) {
    return null
  }
  return absoluteApiUrl(url)
}

interface DatabasePanelProps {
  text: (typeof UI_TEXT)[Language]['database']
}

export function DatabasePanel({ text }: DatabasePanelProps) {
  const [keyword, setKeyword] = useState('')
  const [filter, setFilter] = useState<FilterValue>('all')
  const [records, setRecords] = useState<DatabaseRecord[]>([])
  const [selected, setSelected] = useState<DatabaseRecord | null>(null)
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
    } catch {
      setErrorMessage(text.errors.queryFailed)
      setStatus('error')
    }
  }

  useEffect(() => {
    void loadRecords('', 'all')
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

  async function openRecord(record: DatabaseRecord): Promise<void> {
    // List payloads already include JSON fields; fetch detail for freshest data.
    try {
      const detail = await getDatabaseRecord(record.id)
      setSelected(detail)
    } catch {
      setSelected(record)
    }
  }

  const isLoading = status === 'loading'
  const typeLabels = text.typeLabels
  const selectedImage = mediaSrc(selected?.imageUrl)
  const token = getAuthToken()

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
                <tr key={record.id} className={styles.rowClickable} onClick={() => void openRecord(record)}>
                  <td>
                    <span className={styles.typeBadge}>{typeLabels[record.type]}</span>
                  </td>
                  <td>
                    <div className={styles.titleCell}>
                      <span>{record.title}</span>
                      {record.imageUrl ? <span className={styles.imageChip}>{text.hasImage}</span> : null}
                      {record.detectionJson ? <span className={styles.jsonChip}>{text.hasDetections}</span> : null}
                    </div>
                  </td>
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

      {selected ? (
        <div className={styles.detailOverlay} role="dialog" aria-modal="true" aria-label={text.detailTitle}>
          <div className={styles.detailCard}>
            <header className={styles.detailHeader}>
              <div>
                <p className={styles.detailEyebrow}>{typeLabels[selected.type]}</p>
                <h3 className={styles.detailTitle}>{selected.title}</h3>
                <p className={styles.detailMeta}>
                  {selected.id} · {formatDate(selected.updatedAt)}
                </p>
              </div>
              <button className={styles.closeButton} type="button" onClick={() => setSelected(null)}>
                {text.close}
              </button>
            </header>

            <p className={styles.detailSummary}>{selected.summary}</p>

            {selectedImage ? (
              <div className={styles.detailImageWrap}>
                {/* Token-aware fetch via query not possible for <img>; use Authorization-less public path when auth off.
                    When auth is on, browsers can't set Authorization on <img>, so we fetch as blob if needed. */}
                <AuthImage src={selectedImage} token={token} alt={selected.title} className={styles.detailImage} />
              </div>
            ) : null}

            {selected.detectionJson ? (
              <section className={styles.jsonBlock}>
                <h4 className={styles.jsonTitle}>{text.detectionJson}</h4>
                <pre className={styles.jsonPre}>{JSON.stringify(selected.detectionJson, null, 2)}</pre>
              </section>
            ) : null}

            {selected.planogramJson ? (
              <section className={styles.jsonBlock}>
                <h4 className={styles.jsonTitle}>{text.planogramJson}</h4>
                <pre className={styles.jsonPre}>{JSON.stringify(selected.planogramJson, null, 2)}</pre>
              </section>
            ) : null}

            {selected.extraJson ? (
              <section className={styles.jsonBlock}>
                <h4 className={styles.jsonTitle}>{text.extraJson}</h4>
                <pre className={styles.jsonPre}>{JSON.stringify(selected.extraJson, null, 2)}</pre>
              </section>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}

function AuthImage({
  src,
  token,
  alt,
  className,
}: {
  src: string
  token: string | null
  alt: string
  className?: string
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)

  useEffect(() => {
    let revoked: string | null = null
    let cancelled = false

    async function load(): Promise<void> {
      if (!token) {
        setBlobUrl(null)
        return
      }
      try {
        const response = await fetch(src, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!response.ok) {
          return
        }
        const blob = await response.blob()
        if (cancelled) {
          return
        }
        const url = URL.createObjectURL(blob)
        revoked = url
        setBlobUrl(url)
      } catch {
        // Fall back to direct src (works when auth is disabled).
        setBlobUrl(null)
      }
    }

    void load()
    return () => {
      cancelled = true
      if (revoked) {
        URL.revokeObjectURL(revoked)
      }
    }
  }, [src, token])

  return <img className={className} src={blobUrl ?? src} alt={alt} />
}
