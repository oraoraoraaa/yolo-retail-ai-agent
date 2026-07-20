"""SQL-backed staff-account store for owner-managed user administration.

Only the ``owner`` role may create/update/delete accounts; ``admin`` may view
the list (enforced in the router). This module is storage-only and keeps
password hashing centralized via ``app.services.auth``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from app.db.models import UserRow
from app.db.session import get_engine, get_session
from app.services.auth import VALID_ROLES, hash_password


@dataclass(frozen=True)
class StaffAccount:
    """Account view returned to the API (never includes the password hash)."""

    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime


class UserExistsError(ValueError):
    """Raised when creating/renaming to a username that already exists."""


class UserNotFoundError(KeyError):
    """Raised when a target account id does not exist."""


class InvalidRoleError(ValueError):
    """Raised when an unknown role id is supplied."""


class LastOwnerError(ValueError):
    """Raised when an operation would remove/deactivate the final owner."""


def _row_to_account(row: UserRow) -> StaffAccount:
    return StaffAccount(
        id=row.id,
        username=row.username,
        role=row.role,
        is_active=bool(row.is_active),
        created_at=row.created_at,
    )


def _validate_role(role: str) -> str:
    cleaned = (role or "").strip().lower()
    if cleaned not in VALID_ROLES:
        raise InvalidRoleError(
            f"Unknown role '{role}'. Expected one of {', '.join(VALID_ROLES)}."
        )
    return cleaned


class UserStore:
    """CRUD for staff login accounts."""

    def list(self) -> list[StaffAccount]:
        get_engine()
        with get_session() as session:
            rows = session.scalars(
                select(UserRow).order_by(UserRow.created_at.asc())
            ).all()
            return [_row_to_account(row) for row in rows]

    def get(self, user_id: int) -> StaffAccount | None:
        get_engine()
        with get_session() as session:
            row = session.get(UserRow, user_id)
            return _row_to_account(row) if row else None

    def _owner_count(self, session) -> int:  # type: ignore[no-untyped-def]
        return int(
            session.scalar(
                select(func.count())
                .select_from(UserRow)
                .where(UserRow.role == "owner", UserRow.is_active.is_(True))
            )
            or 0
        )

    def create(
        self,
        *,
        username: str,
        password: str,
        role: str = "staff",
        is_active: bool = True,
    ) -> StaffAccount:
        clean_username = (username or "").strip()
        if not clean_username:
            raise ValueError("Username is required.")
        if not password:
            raise ValueError("Password is required.")
        clean_role = _validate_role(role)
        get_engine()
        with get_session() as session:
            existing = session.scalars(
                select(UserRow).where(UserRow.username == clean_username)
            ).first()
            if existing is not None:
                raise UserExistsError(f"Username '{clean_username}' already exists.")
            row = UserRow(
                username=clean_username,
                password_hash=hash_password(password),
                role=clean_role,
                is_active=bool(is_active),
            )
            session.add(row)
            session.flush()
            return _row_to_account(row)

    def update(
        self,
        user_id: int,
        *,
        username: str | None = None,
        password: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> StaffAccount:
        get_engine()
        with get_session() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise UserNotFoundError(str(user_id))

            was_active_owner = row.role == "owner" and row.is_active

            if username is not None:
                clean_username = username.strip()
                if not clean_username:
                    raise ValueError("Username cannot be empty.")
                if clean_username != row.username:
                    clash = session.scalars(
                        select(UserRow).where(UserRow.username == clean_username)
                    ).first()
                    if clash is not None:
                        raise UserExistsError(
                            f"Username '{clean_username}' already exists."
                        )
                    row.username = clean_username

            if role is not None:
                row.role = _validate_role(role)

            if is_active is not None:
                row.is_active = bool(is_active)

            if password:
                row.password_hash = hash_password(password)

            # Guard: never leave the system without an active owner.
            if was_active_owner and (row.role != "owner" or not row.is_active):
                if self._owner_count(session) == 0:
                    raise LastOwnerError(
                        "Cannot remove the last owner. Assign owner to another "
                        "account first."
                    )

            session.flush()
            return _row_to_account(row)

    def delete(self, user_id: int) -> None:
        get_engine()
        with get_session() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise UserNotFoundError(str(user_id))
            if row.role == "owner" and row.is_active:
                # Deleting this owner is only allowed if another owner remains.
                remaining = int(
                    session.scalar(
                        select(func.count())
                        .select_from(UserRow)
                        .where(
                            UserRow.role == "owner",
                            UserRow.is_active.is_(True),
                            UserRow.id != user_id,
                        )
                    )
                    or 0
                )
                if remaining == 0:
                    raise LastOwnerError(
                        "Cannot delete the last owner. Assign owner to another "
                        "account first."
                    )
            session.delete(row)
            session.flush()


_store: UserStore | None = None


def get_user_store() -> UserStore:
    global _store
    if _store is None:
        _store = UserStore()
    return _store


def reset_user_store() -> None:
    global _store
    _store = None
