/**
 * Shared HTTP helpers for talking to the agent backend.
 * When VITE_API_BASE_URL is empty, individual API modules use offline stubs.
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function getApiBaseUrl(): string {
  return API_BASE_URL
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
  const response = await fetch(url, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new ApiError(detail || `Request failed with status ${response.status}`, response.status)
  }

  return response
}
