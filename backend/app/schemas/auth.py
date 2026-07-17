"""Auth request / response schemas."""

from __future__ import annotations

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
