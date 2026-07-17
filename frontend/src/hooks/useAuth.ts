import { useCallback, useEffect, useState } from 'react'

import { fetchAuthStatus, login as apiLogin } from '@/api/auth'
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
  username: string | null
  role: string | null
  errorMessage: string | null
}

const INITIAL: AuthState = {
  status: 'loading',
  authEnabled: false,
  authenticated: false,
  username: null,
  role: null,
  errorMessage: null,
}

export function useAuth() {
  const [state, setState] = useState<AuthState>(INITIAL)

  const refresh = useCallback(async () => {
    setState((previous) => ({ ...previous, status: 'loading', errorMessage: null }))
    try {
      const status = await fetchAuthStatus()
      if (!status.authEnabled) {
        const stored = getStoredAuthUser()
        setState({
          status: 'ready',
          authEnabled: false,
          authenticated: true,
          username: status.username ?? stored?.username ?? 'anonymous',
          role: status.role ?? stored?.role ?? 'admin',
          errorMessage: null,
        })
        return
      }

      const token = getAuthToken()
      const stored = getStoredAuthUser()
      if (status.authenticated && token) {
        setState({
          status: 'ready',
          authEnabled: true,
          authenticated: true,
          username: status.username ?? stored?.username ?? null,
          role: status.role ?? stored?.role ?? null,
          errorMessage: null,
        })
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
        username: null,
        role: null,
        errorMessage: null,
      })
    } catch (error) {
      // If the agent is unreachable, allow offline UI (no auth gate).
      setState({
        status: 'ready',
        authEnabled: false,
        authenticated: true,
        username: 'offline',
        role: 'admin',
        errorMessage: error instanceof Error ? error.message : 'Auth status unavailable',
      })
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function login(username: string, password: string): Promise<boolean> {
    setState((previous) => ({ ...previous, errorMessage: null }))
    try {
      const result = await apiLogin(username, password)
      setState({
        status: 'ready',
        authEnabled: true,
        authenticated: true,
        username: result.username,
        role: result.role,
        errorMessage: null,
      })
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
