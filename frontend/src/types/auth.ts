export interface AuthStatus {
  authEnabled: boolean
  authenticated: boolean
  username?: string | null
  role?: string | null
}

export interface LoginResult {
  accessToken: string
  tokenType: string
  username: string
  role: string
  expiresInHours: number
}

export interface AuthMe {
  id: number
  username: string
  role: string
}
