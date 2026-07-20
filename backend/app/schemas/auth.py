"""Auth request / response schemas."""

from __future__ import annotations

from datetime import datetime

from app.schemas.common import CamelModel


class LoginRequest(CamelModel):
    username: str
    password: str


class LoginResponse(CamelModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    expires_in_hours: int


class AuthStatusResponse(CamelModel):
    auth_enabled: bool
    authenticated: bool = False
    username: str | None = None
    role: str | None = None


class AuthMeResponse(CamelModel):
    id: int
    username: str
    role: str
    # Convenience permission flags mirrored on the frontend for gating UI.
    can_write: bool = False
    can_view_accounts: bool = False
    can_manage_accounts: bool = False


class StaffAccountResponse(CamelModel):
    """A staff account as shown in the Accounts panel (no password hash)."""

    id: int
    username: str
    role: str
    is_active: bool = True
    created_at: datetime


class StaffAccountListResponse(CamelModel):
    accounts: list[StaffAccountResponse]
    total: int


class StaffAccountCreate(CamelModel):
    username: str
    password: str
    role: str = "staff"
    is_active: bool = True


class StaffAccountUpdate(CamelModel):
    """Partial update. Only provided fields change; empty password is ignored."""

    username: str | None = None
    password: str | None = None
    role: str | None = None
    is_active: bool | None = None
