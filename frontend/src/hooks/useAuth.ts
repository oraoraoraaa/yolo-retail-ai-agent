import { useCallback, useEffect, useState } from 'react'

import { fetchAuthMe, fetchAuthStatus, login as apiLogin } from '@/api/auth'
import {
  AUTH_REQUIRED_EVENT,
  clearAuthSession,
  getApiBaseUrl,
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

/**
 * True offline mode is only for UI work without a backend
 * (`VITE_API_BASE_URL` empty). When a backend origin is configured we must
 * never pretend to be "signed in as offline" — that bypasses LoginPanel while
 * protected APIs still return 401.
 */
function isTrueOfflineMode(): boolean {
  return !getApiBaseUrl()
}

function signedInState(partial: {
  authEnabled: boolean
  username: string | null
  role: string | null
  userId?: number | null
  errorMessage?: string | null
}): AuthState {
  const role = partial.role
  return {
    status: 'ready',
    authEnabled: partial.authEnabled,
    authenticated: true,
    userId: partial.userId ?? null,
    username: partial.username,
    role,
    ...permsFromRole(role),
    errorMessage: partial.errorMessage ?? null,
  }
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
          authenticated: true,
          userId: me.id ?? previous.userId,
          username: me.username ?? username,
          role: me.role ?? role,
          canWrite: me.canWrite,
          canViewAccounts: me.canViewAccounts,
          canManageAccounts: me.canManageAccounts,
        }))
        return true
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          return false
        }
        setState((previous) => ({ ...previous, ...permsFromRole(role) }))
        return true
      }
    },
    [],
  )

  const forceLoginGate = useCallback((errorMessage: string | null = null) => {
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
      errorMessage,
    })
  }, [])

  const refresh = useCallback(async () => {
    setState((previous) => ({ ...previous, status: 'loading', errorMessage: null }))
    const token = getAuthToken()
    const stored = getStoredAuthUser()

    // Optimistic restore: keep the previous session visible while we re-check
    // the backend so a refresh/reopen does not flash the login panel.
    if (token && stored) {
      setState(
        signedInState({
          authEnabled: true,
          username: stored.username,
          role: stored.role,
        }),
      )
    }

    try {
      const status = await fetchAuthStatus()
      if (!status.authEnabled) {
        const role = status.role ?? stored?.role ?? 'owner'
        setState(
          signedInState({
            authEnabled: false,
            username: status.username ?? stored?.username ?? 'anonymous',
            role,
          }),
        )
        void applyPermissions(role, status.username ?? stored?.username ?? null)
        return
      }

      if (status.authenticated && token) {
        const role = status.role ?? stored?.role ?? null
        setState(
          signedInState({
            authEnabled: true,
            username: status.username ?? stored?.username ?? null,
            role,
          }),
        )
        const ok = await applyPermissions(role, status.username ?? stored?.username ?? null)
        if (!ok) {
          clearAuthSession()
          forceLoginGate(null)
        }
        return
      }

      // Status said unauthenticated, but we still have a stored token — verify
      // with /me before wiping the session (covers transient status glitches).
      if (token && stored) {
        const ok = await applyPermissions(stored.role, stored.username)
        if (ok) {
          setState(
            signedInState({
              authEnabled: true,
              username: stored.username,
              role: stored.role,
            }),
          )
          return
        }
        clearAuthSession()
      } else if (token && !status.authenticated) {
        clearAuthSession()
      }

      forceLoginGate(null)
    } catch (error) {
      if (isTrueOfflineMode()) {
        // No backend origin configured — allow local stubs without a login gate.
        setState(
          signedInState({
            authEnabled: false,
            username: 'offline',
            role: 'owner',
            errorMessage: error instanceof Error ? error.message : 'Auth status unavailable',
          }),
        )
        return
      }

      // Backend configured but /auth/status failed. Keep a stored session if
      // /me still accepts the token; only force login when the token is dead.
      if (token && stored) {
        const ok = await applyPermissions(stored.role, stored.username)
        if (ok) {
          setState(
            signedInState({
              authEnabled: true,
              username: stored.username,
              role: stored.role,
              errorMessage: null,
            }),
          )
          return
        }
        clearAuthSession()
      }

      forceLoginGate(
        error instanceof Error
          ? error.message
          : 'Auth status unavailable. Sign in once the agent is reachable.',
      )
    }
  }, [applyPermissions, forceLoginGate])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Any protected API 401 should re-open the login panel when a backend is set.
  useEffect(() => {
    if (isTrueOfflineMode()) {
      return
    }
    function onAuthRequired(): void {
      forceLoginGate(null)
    }
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired)
    return () => {
      window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired)
    }
  }, [forceLoginGate])

  async function login(username: string, password: string): Promise<boolean> {
    setState((previous) => ({ ...previous, errorMessage: null }))
    try {
      const result = await apiLogin(username, password)
      setState(
        signedInState({
          authEnabled: true,
          username: result.username,
          role: result.role,
        }),
      )
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
        status: 'ready',
        authEnabled: true,
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
