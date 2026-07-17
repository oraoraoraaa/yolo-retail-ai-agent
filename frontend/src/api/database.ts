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
