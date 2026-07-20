import { useCallback, useEffect, useState } from 'react'

import { fetchAuthMe, fetchAuthStatus, login as apiLogin } from '@/api/auth'
import {
  clearAuthSession,
  getAuthToken,
  getStoredAuthUser,
} from '@/api/client'
import { ApiError } from '@/api/client'

export interface AuthState {
  status: 'loading' | 'ready'
  authEnabled: boolean
  authenticated: boolean
  userId: number | null
  username: string | null
  role: string | null
  canWrite: boolean
  canViewAccounts: boolean
  canManageAccounts: boolean
  errorMessage: string | null
}

const INITIAL: AuthState = {
  status: 'loading',
  authEnabled: false,
  authenticated: false,
  userId: null,
  username: null,
  role: null,
  canWrite: false,
  canViewAccounts: false,
  canManageAccounts: false,
  errorMessage: null,
}

/** Local fallback derivation when /me is unreachable (keeps UI usable). */
function permsFromRole(role: string | null): {
  canWrite: boolean
  canViewAccounts: boolean
  canManageAccounts: boolean
} {
  const r = (role || '').toLowerCase()
  if (r === 'owner') {
    return { canWrite: true, canViewAccounts: true, canManageAccounts: true }
  }
  if (r === 'admin') {
    return { canWrite: true, canViewAccounts: true, canManageAccounts: false }
  }
  // staff / unknown → read-only
  return { canWrite: false, canViewAccounts: false, canManageAccounts: false }
}

export function useAuth() {
  const [state, setState] = useState<AuthState>(INITIAL)

  const applyPermissions = useCallback(
    async (role: string | null, username: string | null) => {
      // Prefer authoritative flags from the backend; fall back to role map.
      try {
        const me = await fetchAuthMe()
        setState((previous) => ({
          ...previous,
          userId: me.id ?? previous.userId,
          username: me.username ?? username,
          role: me.role ?? role,
          canWrite: me.canWrite,
          canViewAccounts: me.canViewAccounts,
          canManageAccounts: me.canManageAccounts,
        }))
      } catch {
        setState((previous) => ({ ...previous, ...permsFromRole(role) }))
      }
    },
    [],
  )

  const refresh = useCallback(async () => {
    setState((previous) => ({ ...previous, status: 'loading', errorMessage: null }))
    try {
      const status = await fetchAuthStatus()
      if (!status.authEnabled) {
        const stored = getStoredAuthUser()
        const role = status.role ?? stored?.role ?? 'owner'
        setState({
          status: 'ready',
          authEnabled: false,
          authenticated: true,
          userId: null,
          username: status.username ?? stored?.username ?? 'anonymous',
          role,
          ...permsFromRole(role),
          errorMessage: null,
        })
        void applyPermissions(role, status.username ?? stored?.username ?? null)
        return
      }

      const token = getAuthToken()
      const stored = getStoredAuthUser()
      if (status.authenticated && token) {
        const role = status.role ?? stored?.role ?? null
        setState({
          status: 'ready',
          authEnabled: true,
          authenticated: true,
          userId: null,
          username: status.username ?? stored?.username ?? null,
          role,
          ...permsFromRole(role),
          errorMessage: null,
        })
        void applyPermissions(role, status.username ?? stored?.username ?? null)
        return
      }

      // Token present but status says not authenticated — clear stale session.
      if (token && !status.authenticated) {
        clearAuthSession()
      }

      setState({
        status: 'ready',
        authEnabled: true,
        authenticated: false,
        userId: null,
        username: null,
        role: null,
        canWrite: false,
        canViewAccounts: false,
        canManageAccounts: false,
        errorMessage: null,
      })
    } catch (error) {
      // If the agent is unreachable, allow offline UI (no auth gate).
      setState({
        status: 'ready',
        authEnabled: false,
        authenticated: true,
        userId: null,
        username: 'offline',
        role: 'owner',
        canWrite: true,
        canViewAccounts: true,
        canManageAccounts: true,
        errorMessage: error instanceof Error ? error.message : 'Auth status unavailable',
      })
    }
  }, [applyPermissions])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function login(username: string, password: string): Promise<boolean> {
    setState((previous) => ({ ...previous, errorMessage: null }))
    try {
      const result = await apiLogin(username, password)
      setState((previous) => ({
        ...previous,
        status: 'ready',
        authEnabled: true,
        authenticated: true,
        username: result.username,
        role: result.role,
        ...permsFromRole(result.role),
        errorMessage: null,
      }))
      void applyPermissions(result.role, result.username)
      return true
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.status === 401
            ? 'invalid'
            : error.message
          : 'failed'
      setState((previous) => ({
        ...previous,
        authenticated: false,
        errorMessage: message,
      }))
      return false
    }
  }

  function logout(): void {
    clearAuthSession()
    setState((previous) => ({
      ...previous,
      authenticated: previous.authEnabled ? false : true,
      username: previous.authEnabled ? null : previous.username,
      role: previous.authEnabled ? null : previous.role,
      canWrite: previous.authEnabled ? false : previous.canWrite,
      canViewAccounts: previous.authEnabled ? false : previous.canViewAccounts,
      canManageAccounts: previous.authEnabled ? false : previous.canManageAccounts,
      errorMessage: null,
    }))
  }

  return {
    ...state,
    login,
    logout,
    refresh,
  }
}
