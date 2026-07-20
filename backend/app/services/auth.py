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

# Role hierarchy for the store deployment:
#   owner  → full control, INCLUDING account management (add/edit/delete users).
#   admin  → change everything EXCEPT accounts (accounts are view-only).
#   staff  → chat with the agent + view cameras only; no changes at all.
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_STAFF = "staff"
VALID_ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_STAFF)

# Roles allowed to make changes (writes) anywhere except account management.
WRITE_ROLES = frozenset({ROLE_OWNER, ROLE_ADMIN})
# Roles allowed to VIEW accounts (owner can also edit them).
ACCOUNT_VIEW_ROLES = frozenset({ROLE_OWNER, ROLE_ADMIN})
# Roles allowed to MANAGE (write) accounts.
ACCOUNT_ADMIN_ROLES = frozenset({ROLE_OWNER})


@dataclass(frozen=True)
class AuthUser:
    """Authenticated staff principal attached to requests."""

    id: int
    username: str
    role: str

    @property
    def can_write(self) -> bool:
        """True when the principal may mutate shelf/ticket/planogram state."""
        return self.role in WRITE_ROLES

    @property
    def can_view_accounts(self) -> bool:
        return self.role in ACCOUNT_VIEW_ROLES

    @property
    def can_manage_accounts(self) -> bool:
        return self.role in ACCOUNT_ADMIN_ROLES


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
    """Ensure at least one active owner account exists.

    Called on startup and after backup restore. The owner role is the only one
    that can manage accounts; without an active owner the Accounts panel is
    permanently locked out.

    Rules:
    1. Empty users table → seed the bootstrap owner (AUTH_ADMIN_*).
    2. Inactive owner(s) only → reactivate one (prefer AUTH_ADMIN_USERNAME).
    3. No owner role at all → promote bootstrap username if present, else the
       first existing user, and mark them active.
    """
    settings = get_settings()
    get_engine()
    with get_session() as session:
        existing = session.scalars(select(UserRow).limit(1)).first()
        if existing is None:
            session.add(
                UserRow(
                    username=settings.auth_admin_username,
                    password_hash=hash_password(settings.auth_admin_password),
                    role=ROLE_OWNER,
                    is_active=True,
                )
            )
            return

        active_owner = session.scalars(
            select(UserRow)
            .where(UserRow.role == ROLE_OWNER, UserRow.is_active.is_(True))
            .limit(1)
        ).first()
        if active_owner is not None:
            return

        # Prefer reactivating an existing owner over promoting someone else.
        seed = session.scalars(
            select(UserRow).where(UserRow.username == settings.auth_admin_username)
        ).first()
        inactive_owner = session.scalars(
            select(UserRow).where(UserRow.role == ROLE_OWNER).limit(1)
        ).first()
        # Prefer bootstrap username if that row is already an (inactive) owner.
        if seed is not None and seed.role == ROLE_OWNER:
            seed.is_active = True
            return
        if inactive_owner is not None:
            inactive_owner.is_active = True
            return

        # No owner role at all (older admin-only backups / demoted restores).
        target = seed or existing
        target.role = ROLE_OWNER
        target.is_active = True


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    """FastAPI dependency requiring a valid Bearer JWT when auth is enabled."""
    settings = get_settings()
    if not settings.auth_enabled:
        # Local/dev convenience: full-access owner principal.
        return AuthUser(id=0, username="anonymous", role=ROLE_OWNER)

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
        return AuthUser(id=0, username="anonymous", role=ROLE_OWNER)
    if credentials is None or not credentials.credentials:
        return None
    try:
        user = decode_access_token(credentials.credentials)
    except HTTPException:
        return None

    # Mirror get_current_user: only treat active DB accounts as signed-in so a
    # deleted/disabled user cannot keep a long-lived JWT session forever.
    get_engine()
    with get_session() as session:
        row = session.get(UserRow, user.id)
        if row is None or not row.is_active:
            return None
        return AuthUser(id=row.id, username=row.username, role=row.role)


def require_write(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> AuthUser:
    """Dependency: reject read-only (staff) principals on mutating endpoints."""
    if not user.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role is read-only. Ask an admin or owner to make changes.",
        )
    return user


def require_account_admin(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> AuthUser:
    """Dependency: only owners may add/edit/delete accounts."""
    if not user.can_manage_accounts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner role can manage accounts.",
        )
    return user


def require_account_viewer(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> AuthUser:
    """Dependency: owner + admin may view the account list."""
    if not user.can_view_accounts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view accounts.",
        )
    return user
