import type { DatabaseQueryParams, DatabaseQueryResult, DatabaseRecord } from '@/types'

import { apiFetch, getApiBaseUrl } from './client'

const DATABASE_QUERY_PATH = '/api/v1/database/records'

/**
 * Query saved retail records.
 *
 * Backend contract:
 * - Method: GET
 * - Query: keyword?: string, type?: audit | sku | inventory | chat
 * - Response JSON: { records: DatabaseRecord[] }
 */
export async function queryDatabaseRecords(params: DatabaseQueryParams = {}): Promise<DatabaseQueryResult> {
  if (!getApiBaseUrl()) {
    return { records: [] }
  }

  const search = new URLSearchParams()
  if (params.keyword) {
    search.set('keyword', params.keyword)
  }
  if (params.type && params.type !== 'all') {
    search.set('type', params.type)
  }

  const query = search.toString()
  const response = await apiFetch(`${DATABASE_QUERY_PATH}${query ? `?${query}` : ''}`)

  return (await response.json()) as DatabaseQueryResult
}

export async function getDatabaseRecord(recordId: string): Promise<DatabaseRecord> {
  const response = await apiFetch(`${DATABASE_QUERY_PATH}/${encodeURIComponent(recordId)}`)
  return (await response.json()) as DatabaseRecord
}

export async function clearDatabaseRecords(): Promise<{
  deleted: number
  mediaDeleted?: number
  message?: string
}> {
  if (!getApiBaseUrl()) {
    return { deleted: 0 }
  }
  const response = await apiFetch(DATABASE_QUERY_PATH, { method: 'DELETE' })
  return (await response.json()) as { deleted: number; mediaDeleted?: number; message?: string }
}

export async function downloadSystemBackup(): Promise<Blob> {
  const response = await apiFetch('/api/v1/database/backup')
  return await response.blob()
}

export async function restoreSystemBackup(
  file: File,
): Promise<{ ok: boolean; message: string; restored?: Record<string, number> }> {
  const form = new FormData()
  form.append('file', file)
  const response = await apiFetch('/api/v1/database/backup/restore', {
    method: 'POST',
    body: form,
  })
  return (await response.json()) as {
    ok: boolean
    message: string
    restored?: Record<string, number>
  }
}
