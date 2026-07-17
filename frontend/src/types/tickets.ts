/** Action tickets + closed-loop board types (mirrors backend schemas/tickets.py). */

export type IssueType =
  | 'out_of_stock'
  | 'shelf_empty'
  | 'misplaced'
  | 'low_stock'
  | 'camera_issue'
  | 'low_stock_warning'
export type TicketPriority = 'critical' | 'high' | 'medium' | 'low'
export type TicketStatus =
  | 'open'
  | 'dispatched'
  | 'in_progress'
  | 'done'
  | 'verified'
  | 'escalated'
  | 'cancelled'
/** Built-in defaults; custom roles are free-form strings. */
export type AssigneeRole = string
export type WebhookChannel = 'slack' | 'wecom' | 'generic'

export const FIXED_ISSUE_TYPES: IssueType[] = [
  'low_stock',
  'low_stock_warning',
  'out_of_stock',
  'shelf_empty',
  'camera_issue',
]

export interface StaffRole {
  id: string
  label: string
}

export interface TicketHistoryEvent {
  at: string
  event: string
  note?: string
  status?: string
  [key: string]: unknown
}

export interface Ticket {
  id: string
  issueType: IssueType | string
  priority: TicketPriority
  status: TicketStatus
  assigneeRole: AssigneeRole
  assigneeRoles?: AssigneeRole[]
  title: string
  description: string
  sku?: string | null
  itemName?: string | null
  shelfLabel?: string | null
  planogramId?: string | null
  slotId?: string | null
  auditRecordId?: string | null
  evidence?: Record<string, unknown> | null
  history: TicketHistoryEvent[]
  fingerprint?: string | null
  escalateCount: number
  dispatchedAt?: string | null
  doneAt?: string | null
  verifiedAt?: string | null
  createdAt: string
  updatedAt: string
}

export interface TicketListResult {
  tickets: Ticket[]
  total: number
}

export interface TicketStatusUpdate {
  status: TicketStatus
  note?: string
}

export interface ClosedLoopRunResult {
  stage: string
  narrative: string
  findings: Record<string, unknown>[]
  ticketsCreated: Ticket[]
  ticketsUpdated: Ticket[]
  dispatched: Record<string, unknown>[]
  skipped: Record<string, unknown>[]
  notifications?: Record<string, unknown>[]
}

export interface VerifyTicketResult {
  ticket: Ticket
  verified: boolean
  escalated: boolean
  narrative: string
  remainingIssues: Record<string, unknown>[]
}

export interface WebhookEndpoint {
  id: string
  name: string
  url: string
  enabled: boolean
}

export interface WebhookProviderConfig {
  enabled: boolean
  endpoints: WebhookEndpoint[]
}

export interface WebhookSettings {
  activeChannel: WebhookChannel
  slack: WebhookProviderConfig
  wecom: WebhookProviderConfig
  generic: WebhookProviderConfig
  defaultEndpointId?: string | null
  roles: StaffRole[]
  /** Fixed issue types → one or more role ids (issue keys are not user-editable). */
  issueRoleMap: Partial<Record<IssueType, string[]>>
  roleRoutes: Partial<Record<string, string>>
}
