export type DatabaseRecordType = 'audit' | 'sku' | 'inventory' | 'chat'

export interface DatabaseRecord {
  id: string
  type: DatabaseRecordType
  title: string
  summary: string
  updatedAt: string
  imageRef?: string | null
  imageUrl?: string | null
  detectionJson?: Record<string, unknown> | null
  planogramJson?: Record<string, unknown> | null
  extraJson?: Record<string, unknown> | null
}

export interface DatabaseQueryParams {
  keyword?: string
  type?: DatabaseRecordType | 'all'
}

export interface DatabaseQueryResult {
  records: DatabaseRecord[]
}
