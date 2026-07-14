import type { DatabaseQueryParams, DatabaseQueryResult } from '@/types'

import { apiFetch, getApiBaseUrl } from './client'

const DATABASE_QUERY_PATH = '/api/v1/database/records'

/**
 * Query saved retail records.
 *
 * Backend contract (planned):
 * - Method: GET
 * - Query: keyword?: string, type?: audit | sku | inventory | chat
 * - Response JSON: { records: DatabaseRecord[] }
 *
 * Until the backend exists this returns an empty result set.
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
