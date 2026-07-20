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
  canWrite: boolean
  canViewAccounts: boolean
  canManageAccounts: boolean
}

/** Staff role ids known to the frontend (backend also accepts custom labels). */
export type UserRole = 'owner' | 'admin' | 'staff'

export interface StaffAccount {
  id: number
  username: string
  role: string
  isActive: boolean
  createdAt: string
}

export interface StaffAccountListResult {
  accounts: StaffAccount[]
  total: number
}

export interface StaffAccountCreatePayload {
  username: string
  password: string
  role: string
  isActive: boolean
}

export interface StaffAccountUpdatePayload {
  username?: string
  password?: string
  role?: string
  isActive?: boolean
}
