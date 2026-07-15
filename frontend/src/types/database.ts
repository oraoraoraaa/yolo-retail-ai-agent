export type DatabaseRecordType = 'audit' | 'sku' | 'inventory' | 'chat'

export interface DatabaseRecord {
  id: string
  type: DatabaseRecordType
  title: string
  summary: string
  updatedAt: string
}

export interface DatabaseQueryParams {
  keyword?: string
  type?: DatabaseRecordType | 'all'
}

export interface DatabaseQueryResult {
  records: DatabaseRecord[]
}
