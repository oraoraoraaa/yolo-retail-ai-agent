import type {
  AuthMe,
  AuthStatus,
  LoginResult,
  StaffAccount,
  StaffAccountCreatePayload,
  StaffAccountListResult,
  StaffAccountUpdatePayload,
} from '@/types/auth'

import { apiFetch, getApiBaseUrl, setAuthSession } from './client'

const AUTH_STATUS_PATH = '/api/v1/auth/status'
const AUTH_LOGIN_PATH = '/api/v1/auth/login'
const AUTH_ME_PATH = '/api/v1/auth/me'
const AUTH_USERS_PATH = '/api/v1/auth/users'

export async function fetchAuthStatus(): Promise<AuthStatus> {
  if (!getApiBaseUrl()) {
    return {
      authEnabled: false,
      authenticated: true,
      username: 'offline',
      role: 'owner',
    }
  }

  const response = await apiFetch(AUTH_STATUS_PATH)
  return (await response.json()) as AuthStatus
}

export async function login(username: string, password: string): Promise<LoginResult> {
  if (!getApiBaseUrl()) {
    const result: LoginResult = {
      accessToken: 'offline',
      tokenType: 'bearer',
      username,
      role: 'owner',
      expiresInHours: 12,
    }
    setAuthSession(result.accessToken, result.username, result.role)
    return result
  }

  const response = await apiFetch(AUTH_LOGIN_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const result = (await response.json()) as LoginResult
  setAuthSession(result.accessToken, result.username, result.role)
  return result
}

export async function fetchAuthMe(): Promise<AuthMe> {
  if (!getApiBaseUrl()) {
    return {
      id: 0,
      username: 'offline',
      role: 'owner',
      canWrite: true,
      canViewAccounts: true,
      canManageAccounts: true,
    }
  }
  const response = await apiFetch(AUTH_ME_PATH)
  return (await response.json()) as AuthMe
}

// --- Account management (owner writes; owner + admin may view) --------------

export async function listStaffAccounts(): Promise<StaffAccountListResult> {
  const response = await apiFetch(AUTH_USERS_PATH)
  return (await response.json()) as StaffAccountListResult
}

export async function createStaffAccount(
  payload: StaffAccountCreatePayload,
): Promise<StaffAccount> {
  const response = await apiFetch(AUTH_USERS_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return (await response.json()) as StaffAccount
}

export async function updateStaffAccount(
  userId: number,
  payload: StaffAccountUpdatePayload,
): Promise<StaffAccount> {
  const response = await apiFetch(`${AUTH_USERS_PATH}/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return (await response.json()) as StaffAccount
}

export async function deleteStaffAccount(userId: number): Promise<void> {
  await apiFetch(`${AUTH_USERS_PATH}/${userId}`, { method: 'DELETE' })
}
