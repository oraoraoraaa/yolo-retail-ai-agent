/**
 * Shared HTTP helpers for talking to the backend.
 * When VITE_API_BASE_URL is empty, individual API modules use offline stubs.
 * Attaches the JWT Bearer token from localStorage when present.
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export const AUTH_TOKEN_STORAGE_KEY = 'yolo-retail-auth-token'
export const AUTH_USER_STORAGE_KEY = 'yolo-retail-auth-user'

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

export function getAuthToken(): string | null {
  try {
    return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setAuthSession(token: string, username: string, role: string): void {
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token)
  window.localStorage.setItem(AUTH_USER_STORAGE_KEY, JSON.stringify({ username, role }))
}

export function clearAuthSession(): void {
  window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
  window.localStorage.removeItem(AUTH_USER_STORAGE_KEY)
}

export function getStoredAuthUser(): { username: string; role: string } | null {
  try {
    const raw = window.localStorage.getItem(AUTH_USER_STORAGE_KEY)
    if (!raw) {
      return null
    }
    const parsed = JSON.parse(raw) as { username?: string; role?: string }
    if (!parsed.username) {
      return null
    }
    return { username: parsed.username, role: parsed.role || 'staff' }
  } catch {
    return null
  }
}

export function absoluteApiUrl(path: string): string {
  if (!path) {
    return path
  }
  if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('data:')) {
    return path
  }
  if (!API_BASE_URL) {
    return path
  }
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
  const headers = new Headers(init?.headers ?? {})
  const token = getAuthToken()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(url, {
    ...init,
    headers,
  })

  if (response.status === 401) {
    // Token expired / invalid — clear local session so the UI can re-login.
    clearAuthSession()
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new ApiError(detail || `Request failed with status ${response.status}`, response.status)
  }

  return response
}
