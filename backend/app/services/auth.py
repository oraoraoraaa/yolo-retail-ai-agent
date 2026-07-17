"""JWT + password auth for store staff deployment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.config import get_settings
from app.db.models import UserRow
from app.db.session import get_engine, get_session

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    """Authenticated staff principal attached to requests."""

    id: int
    username: str
    role: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(*, user_id: int, username: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.auth_token_ttl_hours),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_access_token(token: str) -> AuthUser:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.auth_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = payload.get("sub")
    username = payload.get("username")
    role = payload.get("role") or "staff"
    if not sub or not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = int(sub)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return AuthUser(id=user_id, username=str(username), role=str(role))


def authenticate_user(username: str, password: str) -> AuthUser | None:
    """Validate credentials against the users table."""
    get_engine()
    with get_session() as session:
        row = session.scalars(select(UserRow).where(UserRow.username == username.strip())).first()
        if row is None or not row.is_active:
            return None
        if not verify_password(password, row.password_hash):
            return None
        return AuthUser(id=row.id, username=row.username, role=row.role)


def ensure_default_admin() -> None:
    """Create the bootstrap admin when the users table is empty."""
    settings = get_settings()
    get_engine()
    with get_session() as session:
        existing = session.scalars(select(UserRow).limit(1)).first()
        if existing is not None:
            return
        session.add(
            UserRow(
                username=settings.auth_admin_username,
                password_hash=hash_password(settings.auth_admin_password),
                role="admin",
                is_active=True,
            )
        )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    """FastAPI dependency requiring a valid Bearer JWT when auth is enabled."""
    settings = get_settings()
    if not settings.auth_enabled:
        # Local/dev convenience: anonymous staff principal.
        return AuthUser(id=0, username="anonymous", role="admin")

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = decode_access_token(credentials.credentials)

    # Confirm the account still exists / is active.
    get_engine()
    with get_session() as session:
        row = session.get(UserRow, user.id)
        if row is None or not row.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User is inactive or missing.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return AuthUser(id=row.id, username=row.username, role=row.role)


def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser | None:
    """Return the user when a valid token is present; None otherwise (no 401)."""
    settings = get_settings()
    if not settings.auth_enabled:
        return AuthUser(id=0, username="anonymous", role="admin")
    if credentials is None or not credentials.credentials:
        return None
    try:
        return decode_access_token(credentials.credentials)
    except HTTPException:
        return None
