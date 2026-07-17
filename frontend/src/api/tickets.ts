/**
 * Action ticket board + closed-loop agent + webhook admin API client.
 */
import type { Language } from '@/lib/i18n'
import type {
  ClosedLoopRunResult,
  Ticket,
  TicketListResult,
  TicketStatus,
  VerifyTicketResult,
  WebhookChannel,
  WebhookSettings,
} from '@/types/tickets'

import { apiFetch, getApiBaseUrl } from './client'

export interface TicketQueryParams {
  status?: string
  issueType?: string
  priority?: string
  assigneeRole?: string
  keyword?: string
  limit?: number
  offset?: number
}

export async function listTickets(params: TicketQueryParams = {}): Promise<TicketListResult> {
  if (!getApiBaseUrl()) {
    return { tickets: [], total: 0 }
  }
  const search = new URLSearchParams()
  if (params.status && params.status !== 'all') search.set('status', params.status)
  if (params.issueType && params.issueType !== 'all') search.set('issueType', params.issueType)
  if (params.priority && params.priority !== 'all') search.set('priority', params.priority)
  if (params.assigneeRole && params.assigneeRole !== 'all') {
    search.set('assigneeRole', params.assigneeRole)
  }
  if (params.keyword) search.set('keyword', params.keyword)
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  const qs = search.toString()
  const response = await apiFetch(`/api/v1/tickets${qs ? `?${qs}` : ''}`)
  return (await response.json()) as TicketListResult
}

export async function clearTickets(): Promise<{ deleted: number; message?: string }> {
  const response = await apiFetch('/api/v1/tickets', { method: 'DELETE' })
  return (await response.json()) as { deleted: number; message?: string }
}

export async function getTicket(ticketId: string): Promise<Ticket> {
  const response = await apiFetch(`/api/v1/tickets/${ticketId}`)
  return (await response.json()) as Ticket
}

export async function updateTicketStatus(
  ticketId: string,
  status: TicketStatus,
  note?: string,
): Promise<Ticket> {
  const response = await apiFetch(`/api/v1/tickets/${ticketId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, note }),
  })
  return (await response.json()) as Ticket
}

export async function redispatchTicket(
  ticketId: string,
  language?: Language,
): Promise<Record<string, unknown>> {
  const search = new URLSearchParams()
  if (language) search.set('language', language)
  const qs = search.toString()
  const response = await apiFetch(`/api/v1/tickets/${ticketId}/dispatch${qs ? `?${qs}` : ''}`, {
    method: 'POST',
  })
  return (await response.json()) as Record<string, unknown>
}

export async function runClosedLoop(payload: {
  visionModelResponse: Record<string, unknown>
  planogramResponse?: Record<string, unknown> | null
  language?: Language
  sourceLabel?: string
  auditRecordId?: string
  dispatch?: boolean
  dedupe?: boolean
}): Promise<ClosedLoopRunResult> {
  const response = await apiFetch('/api/v1/agent/closed-loop/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return (await response.json()) as ClosedLoopRunResult
}

export async function verifyTicket(
  ticketId: string,
  payload: {
    visionModelResponse: Record<string, unknown>
    planogramResponse?: Record<string, unknown> | null
    language?: Language
    sourceLabel?: string
  },
): Promise<VerifyTicketResult> {
  const response = await apiFetch(`/api/v1/agent/closed-loop/verify/${ticketId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return (await response.json()) as VerifyTicketResult
}

export async function getWebhookSettings(): Promise<WebhookSettings> {
  const response = await apiFetch('/api/v1/admin/webhooks')
  return (await response.json()) as WebhookSettings
}

export async function saveWebhookSettings(settings: WebhookSettings): Promise<WebhookSettings> {
  const response = await apiFetch('/api/v1/admin/webhooks', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
  return (await response.json()) as WebhookSettings
}

export async function testWebhook(
  channel?: WebhookChannel,
  message?: string,
  settings?: WebhookSettings,
  endpointId?: string,
  language?: Language,
): Promise<Record<string, unknown>> {
  const response = await apiFetch('/api/v1/admin/webhooks/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel, message, settings, endpointId, language }),
  })
  return (await response.json()) as Record<string, unknown>
}
